"""
MoCA Task 1 — Trail Making (Visuospatial/Executive, alternating trail)
=======================================================================

How it works (real-time version)
---------------------------------
1. A diagram of circles labelled 1, A, 2, B, 3, C, 4, D, 5, E is shown.
   The on-screen instructions explain the RULE with a short example only
   (connect 1 -> A -> 2, then keep alternating number/letter the same
   way all the way to E) -- the full answer sequence is never displayed.
2. The patient studies the diagram, then speaks the path out loud -- one
   step at a time with pauses, or several steps in one go; both work.
3. The microphone is recorded CONTINUOUSLY (nothing is dropped while the
   computer is busy transcribing). A voice-activity detector (Silero VAD)
   finds where each spoken phrase starts and ends -- it waits for a real
   pause (about 1.2 s) instead of cutting the speaker off, and it adapts to
   quiet / loud voices instead of using one fixed volume threshold.
4. Each phrase is transcribed OFFLINE by Whisper (faster-whisper), which
   copes much better with different accents, speeds and pronunciations
   than the old web recogniser. As soon as a phrase is recognised, arrows
   are drawn from circle to circle -- green if it's the correct next step,
   red if it's a mistake -- so the path grows on screen in real time.
5. When the patient says "E" (or stops talking for ~10 s), listening stops.
   The WHOLE recording is then transcribed once more in one pass (more
   context = more accurate) and that final transcript is what is scored:
       1/1  only if the spoken path is exactly 1-A-2-B-3-C-4-D-5-E AND every
            step was recognised with good confidence
       0/1  otherwise (a wrong / missing / extra step, or speech that could
            not be recognised reliably -- the system never guesses a 1).
   Saying the same step twice in a row (e.g. repeating after a pause) is
   treated as one step.

Setup
-----
    pip install faster-whisper sounddevice matplotlib numpy
    # The Whisper model (~250-480 MB for "small.en") is downloaded once on
    # first run and then works offline. Set MOCA_WHISPER_MODEL=base.en for a
    # smaller/faster model on slow computers.

Run
---
    python task1_trail_making.py

Troubleshooting "it's not listening at all"
--------------------------------------------
- Check your OS actually granted microphone permission to your
  terminal / VS Code (Mac: System Settings > Privacy & Security >
  Microphone; Windows: Settings > Privacy > Microphone).
- Run:
    python -c "import sounddevice as sd; print(sd.query_devices())"
  to confirm a microphone is detected. Set MOCA_MIC_DEVICE=<number> to pick
  a specific one.
- The console prints "[info] Ready — speak ..." once the mic stream opens
  successfully -- if you never see that, check the traceback printed above
  it for the real cause.
- If faster-whisper / sounddevice are not installed, the script falls back
  to the previous Google web recogniser (needs internet, less reliable).
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import wave

import numpy as np
import matplotlib.pyplot as plt

from moca_common import get_session_dir, make_task_result, save_task_result

try:
    import audioop
except ImportError:  # pragma: no cover
    audioop = None

TASK_ID = "task1_trail_making"

from moca_voice import speak_instruction, HAS_MAC_VOICE as HAS_VOICE


def say(text, wait=True, rate=150):
    """Speak an instruction through the shared moca_voice module."""
    return speak_instruction(text, wait=wait, rate=rate)


# --------------------------------------------------------------------------
# 1. Layout + correct answer (kept internal -- never shown to the patient)
# --------------------------------------------------------------------------
CORRECT_SEQUENCE = ["1", "A", "2", "B", "3", "C", "4", "D", "5", "E"]

NODE_POSITIONS = {
    "1": (1.0, 6.0),
    "A": (3.0, 8.5),
    "2": (2.0, 3.5),
    "B": (4.5, 6.5),
    "3": (3.5, 1.0),
    "C": (6.5, 3.0),
    "4": (5.5, 8.5),
    "D": (8.0, 5.5),
    "5": (7.5, 1.5),
    "E": (9.0, 8.0),
}

MAX_TOKENS = 14                # safety cap so a rambling answer can't loop forever
MAX_CONSECUTIVE_RETRIES = 4    # consecutive unclear attempts before an extra hint

# Official MoCA allows an error that is *immediately* self-corrected. Kept OFF
# (strict: any wrong step = 0). Set True to accept "..., C, no sorry, B, ...".
ALLOW_SELF_CORRECTION = False

# --- speech settings --------------------------------------------------------
SAMPLE_RATE = 16000
WHISPER_MODEL = os.environ.get("MOCA_WHISPER_MODEL", "small.en")
MIC_DEVICE = os.environ.get("MOCA_MIC_DEVICE")            # None = system default
MIN_WORD_PROB = 0.25            # every step must be recognised at least this confidently
MIN_AGREED_WORD_PROB = 0.02     # ... unless live + final passes agree on the whole path
END_OF_PHRASE_SILENCE_S = 1.2   # pause that ends one spoken phrase (not the task)
END_OF_TASK_SILENCE_S = 10.0    # silence after speaking that ends the task
NO_SPEECH_REMINDER_S = 15.0     # remind the patient to speak if nothing heard
MAX_TASK_SECONDS = 150.0        # hard stop
GRACE_AFTER_E_S = 1.0           # keep recording briefly after "E" so it isn't clipped
# Vocabulary hint for Whisper. Deliberately NOT in answer order, so it can't
# nudge a wrong answer into the right sequence.
VOCAB_PROMPT = "Letters: A, B, C, D, E. Numbers: one, two, three, four, five."


# --------------------------------------------------------------------------
# 2. Word -> token normalisation (handles common speech-to-text spellings)
# --------------------------------------------------------------------------
# Only the 10 circles are valid; any OTHER number or letter the patient says
# becomes an invalid step ("6", "F", ...) so it counts as a mistake instead of
# being silently ignored.
WORD_TO_TOKEN = {
    "one": "1", "won": "1",
    "two": "2",
    "three": "3", "tree": "3", "free": "3",
    "four": "4", "fore": "4",
    "five": "5", "fife": "5",
    "six": "6", "seven": "7", "eight": "8", "ate": "8", "nine": "9", "ten": "10",
    "zero": "0",
    "a": "A", "ay": "A", "eh": "A", "aye": "A", "hey": "A",
    "b": "B", "be": "B", "bee": "B", "bea": "B",
    "c": "C", "see": "C", "sea": "C", "si": "C", "cee": "C",
    "d": "D", "dee": "D", "de": "D", "dea": "D",
    "e": "E", "ee": "E", "ea": "E",
}
# "to", "too", "for" are usually connecting words ("one to A to two"): they
# count as 2 / 4 only when said on their own, never between two other steps.
AMBIGUOUS_WORDS = {"to": "2", "too": "2", "for": "4"}
FILLER_WORDS = {
    "and", "then", "next", "now", "um", "uh", "er", "erm", "hmm", "mm", "okay", "ok",
    "so", "goes", "go", "going", "after", "that", "is", "it's", "its", "letter",
    "number", "the", "from", "let's", "lets", "yeah", "yes", "right",
    "well", "i", "think", "circle", "start", "at", "end", "with", "on", "of",
}
CORRECTION_WORDS = {"no", "sorry", "wait", "oops", "correction", "mean"}


def _split_word(w):
    """'1A2B' -> ['1','A','2','B'];  'b.' -> ['b'];  '12' -> ['1','2']."""
    w = w.strip().strip(".,!?;:\"'()-").lower()
    if not w:
        return []
    if re.fullmatch(r"[0-9a-z]+", w) and re.search(r"\d", w):
        return re.findall(r"\d|[a-z]+", w)
    return [w]


def parse_word_list(words, with_times=False):
    """
    words: list of dicts {"word": str, "prob": float}. Returns list of
    (token, prob, word_text). Unknown non-step words are ignored.
    """
    pieces = []
    for w in words:
        for p in _split_word(w["word"]):
            pieces.append({"text": p, "prob": float(w.get("prob", 1.0)),
                           "start": w.get("start"), "end": w.get("end")})

    def is_step(t):
        return (t in WORD_TO_TOKEN or t.isdigit()
                or (len(t) == 1 and t.isalpha()))

    out = []
    pending_correction = False
    for i, p in enumerate(pieces):
        t = p["text"]
        if t in CORRECTION_WORDS:
            pending_correction = True
            continue
        if t in AMBIGUOUS_WORDS:
            prev_step = i > 0 and is_step(pieces[i - 1]["text"])
            next_step = i + 1 < len(pieces) and is_step(pieces[i + 1]["text"])
            if prev_step or next_step:
                continue            # connector: "one to A"
            tok = AMBIGUOUS_WORDS[t]
        elif t in WORD_TO_TOKEN:
            tok = WORD_TO_TOKEN[t]
        elif t.isdigit():
            tok = t
        elif len(t) == 1 and t.isalpha():
            tok = t.upper()          # any other letter -> invalid step
        else:
            continue                 # filler / unrelated word
        if pending_correction and ALLOW_SELF_CORRECTION and out:
            out.pop()                # "C, no, B" -> replace C by B
        pending_correction = False
        out.append((tok, p["prob"], p["text"], p["start"], p["end"]) if with_times
                   else (tok, p["prob"], p["text"]))
    return out


def unexplained_words(words):
    """Words that are neither a path step nor a known filler (e.g. 'yay', 'sing')."""
    out = []
    for w in words:
        for t in _split_word(w["word"]):
            if (t in WORD_TO_TOKEN or t in AMBIGUOUS_WORDS or t in FILLER_WORDS
                    or t in CORRECTION_WORDS or t.isdigit() or (len(t) == 1 and t.isalpha())):
                continue
            out.append(t)
    return out


def parse_tokens(text):
    """Turn one transcribed phrase into a list of node tokens (e.g. ['1'] or ['1','A'])."""
    return [t for t, _, _ in parse_word_list([{"word": w, "prob": 1.0} for w in text.split()])]


def collapse_repeats(steps):
    """Saying the same circle twice in a row (repeating yourself) is one step."""
    out = []
    for s in steps:
        tok = s[0] if isinstance(s, tuple) else s
        if out and (out[-1][0] if isinstance(out[-1], tuple) else out[-1]) == tok:
            if isinstance(s, tuple) and s[1] > out[-1][1]:
                out[-1] = s          # keep the more confident recognition
            continue
        out.append(s)
    return out


def evaluate_path(steps, min_prob=MIN_WORD_PROB):
    """
    steps: [(token, prob, word)] from the FINAL transcript.
    Returns (score 0/1, reason, details). All-or-nothing; uncertain -> 0.
    """
    steps = collapse_repeats(steps)
    tokens = [t for t, _, _ in steps]
    low = [(t, round(p, 2)) for t, p, _ in steps if p < min_prob]
    details = {"spoken_sequence": tokens, "expected_sequence": CORRECT_SEQUENCE,
               "low_confidence_steps": low}
    if not tokens:
        return 0, "no path steps were recognised", details
    first_error = next((i for i, t in enumerate(tokens)
                        if i >= len(CORRECT_SEQUENCE) or t != CORRECT_SEQUENCE[i]), None)
    if first_error is not None:
        details["first_mistake_step"] = first_error + 1
        return 0, (f"incorrect path: step {first_error + 1} was '{tokens[first_error]}'"
                   + (f", expected '{CORRECT_SEQUENCE[first_error]}'"
                      if first_error < len(CORRECT_SEQUENCE) else " (extra step)")), details
    if len(tokens) < len(CORRECT_SEQUENCE):
        details["first_mistake_step"] = len(tokens) + 1
        return 0, f"incomplete path: stopped after '{tokens[-1]}'", details
    if low:
        return 0, f"path matched but could not be verified reliably (low-confidence steps {low})", details
    return 1, "correct path 1-A-2-B-3-C-4-D-5-E", details


# --------------------------------------------------------------------------
# 3. Diagram — draws the nodes once, then the path grows in real time
# --------------------------------------------------------------------------
class TrailDiagram:
    def __init__(self):
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(7, 7))
        self._path_artists = []
        self._draw_nodes()
        self.status_text = self.ax.text(
            5, -0.6, "", ha="center", va="center", fontsize=12, color="black",
            bbox=dict(boxstyle="round", fc="lightyellow", ec="gray"),
        )
        self.fig.canvas.draw()
        self.fig.canvas.flush_events()

    def _draw_nodes(self):
        for label, (x, y) in NODE_POSITIONS.items():
            circle = plt.Circle((x, y), 0.5, fill=False, linewidth=2)
            self.ax.add_patch(circle)
            self.ax.text(x, y, label, ha="center", va="center", fontsize=16, weight="bold")
        self.ax.set_xlim(-0.5, 10)
        self.ax.set_ylim(-1.2, 10)
        self.ax.set_aspect("equal")
        self.ax.axis("off")
        self.ax.set_title(
            "Connect the circles, alternating numbers and letters.\n"
            "Example: 1 -> A -> 2 ... keep alternating the same way, all the way to E.\n"
            "Speak each step out loud.",
            fontsize=11,
        )

    def mark_start(self, label, correct):
        if label not in NODE_POSITIONS:
            return
        color = "green" if correct else "red"
        x, y = NODE_POSITIONS[label]
        circle = plt.Circle((x, y), 0.5, fill=True, color=color, alpha=0.35)
        self.ax.add_patch(circle)
        self._path_artists.append(circle)
        self._refresh()

    def draw_step(self, from_label, to_label, correct):
        if from_label not in NODE_POSITIONS or to_label not in NODE_POSITIONS:
            return   # an invalid word (e.g. "six") can't be drawn, but still counts as a mistake
        color = "green" if correct else "red"
        x1, y1 = NODE_POSITIONS[from_label]
        x2, y2 = NODE_POSITIONS[to_label]
        arrow = self.ax.annotate(
            "", xy=(x2, y2), xytext=(x1, y1),
            arrowprops=dict(arrowstyle="->", color=color, lw=2.5,
                             shrinkA=22, shrinkB=22),
        )
        to_circle = plt.Circle((x2, y2), 0.5, fill=True, color=color, alpha=0.35)
        self.ax.add_patch(to_circle)
        self._path_artists += [arrow, to_circle]
        self._refresh()

    def clear_path(self):
        for a in self._path_artists:
            try:
                a.remove()
            except Exception:
                pass
        self._path_artists = []
        self._refresh()

    def draw_path(self, tokens):
        """Redraw the whole path (used after the final, more accurate transcription)."""
        self.clear_path()
        last = None
        for i, tok in enumerate(tokens):
            correct = i < len(CORRECT_SEQUENCE) and tok == CORRECT_SEQUENCE[i]
            if last is None:
                self.mark_start(tok, correct)
            else:
                self.draw_step(last, tok, correct)
            last = tok

    def show_status(self, message, color="orange"):
        self.status_text.set_text(message)
        self.status_text.set_bbox(dict(boxstyle="round", fc=color, ec="gray"))
        self._refresh()

    def clear_status(self):
        self.status_text.set_text("")
        self._refresh()

    def show_final_score(self, score, max_score):
        passed = score == max_score
        color = "lightgreen" if passed else "lightcoral"
        self.ax.set_title(f"SCORE: {score} / {max_score}", fontsize=20,
                           color="darkgreen" if passed else "darkred", weight="bold")
        self.fig.patch.set_facecolor(color)
        self._refresh()

    def _refresh(self):
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()

    def pump(self):
        """Call frequently from the main loop to keep the window responsive."""
        plt.pause(0.05)


# --------------------------------------------------------------------------
# 4. Speech engine: offline Whisper (faster-whisper) + Silero VAD
# --------------------------------------------------------------------------
class SpeechEngine:
    """Loads Whisper once; transcribes float32 16 kHz mono audio."""

    supports_constrained = True

    def __init__(self, model_size=WHISPER_MODEL):
        from faster_whisper import WhisperModel
        self.model_size = model_size
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self._suppress = None

    def _constrained_suppress_list(self):
        """
        Token ids Whisper may NOT output in constrained mode: everything except
        single letters (A-Z, so a wrong letter like "F" can still be heard),
        digits, number words one..ten, a few connecting words and punctuation.
        This stops a letter from being turned into a word ("A" -> "Yay!").
        """
        if self._suppress is None:
            tok = self.model.hf_tokenizer
            eot = tok.token_to_id("<|endoftext|>")
            keep_words = {"one", "two", "three", "four", "five", "six", "seven", "eight",
                          "nine", "ten", "and", "then", "to"}
            suppress = []
            for i in range(eot):
                raw = tok.decode([i])
                core = raw.strip()
                low = core.lower()
                spaced = raw == " " + core          # starts a new word
                ok = (core in {",", ".", "?", "!"} and raw in (core, " " + core)
                      or (core.isdigit() and len(core) <= 2 and raw in (core, " " + core))
                      # letters / words only as whole new words, so pieces can't
                      # be glued into other words ("Y"+"ay" -> "Yay")
                      or (spaced and len(core) == 1 and core.isalpha())
                      or (spaced and low in keep_words))
                if not ok:
                    suppress.append(i)
            self._suppress = suppress
        return self._suppress

    def transcribe(self, audio, whole_session=False, constrained=False, prompt=VOCAB_PROMPT):
        audio = _normalise_level(audio)
        opts = dict(language="en", beam_size=5, best_of=5, temperature=[0.0, 0.2, 0.4],
                    condition_on_previous_text=False, initial_prompt=prompt,
                    word_timestamps=True, no_speech_threshold=0.6)
        if whole_session:
            opts.update(vad_filter=True, vad_parameters=dict(
                threshold=0.35, min_silence_duration_ms=500, speech_pad_ms=300))
        if constrained:
            opts["suppress_tokens"] = self._constrained_suppress_list()
        segments, _info = self.model.transcribe(audio, **opts)
        words, texts = [], []
        for seg in segments:
            # skip likely hallucinations on noise/silence
            if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
                continue
            texts.append(seg.text.strip())
            for w in (seg.words or []):
                words.append({"word": w.word, "prob": float(w.probability),
                              "start": float(w.start), "end": float(w.end)})
        return {"text": " ".join(texts).strip(), "words": words}


def _normalise_level(audio):
    """Bring quiet recordings up to a normal level (Whisper is fine with loud ones)."""
    audio = np.asarray(audio, dtype=np.float32)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if 1e-4 < peak < 0.5:
        audio = audio * min(0.9 / peak, 20.0)
    return audio


def _steps_from(res):
    if res["words"]:
        return parse_word_list(res["words"])
    return [(t, 1.0, t) for t in parse_tokens(res["text"])]


def find_speech(audio, min_silence_s=END_OF_PHRASE_SILENCE_S):
    """Silero VAD over `audio` -> list of (start_sample, end_sample)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    opts = VadOptions(threshold=0.35, min_speech_duration_ms=120,
                      min_silence_duration_ms=int(min_silence_s * 1000), speech_pad_ms=250)
    return [(t["start"], t["end"]) for t in get_speech_timestamps(_normalise_level(audio), opts)]


class MicRecorder:
    """Continuous microphone capture into memory (callback thread: nothing is dropped)."""

    def __init__(self, device=MIC_DEVICE):
        import sounddevice as sd
        self._chunks = queue.Queue()
        self.audio = np.zeros(0, np.float32)
        dev = int(device) if device not in (None, "") and str(device).isdigit() else device
        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                     blocksize=int(SAMPLE_RATE * 0.03), device=dev,
                                     callback=self._callback)
        self.overflows = 0

    def _callback(self, indata, frames, time_info, status):
        if status and status.input_overflow:
            self.overflows += 1
        self._chunks.put(indata[:, 0].copy())

    def start(self):
        self.stream.start()

    def stop(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass

    def pull(self):
        """Move newly captured audio into self.audio; returns total seconds."""
        parts = []
        while True:
            try:
                parts.append(self._chunks.get_nowait())
            except queue.Empty:
                break
        if parts:
            self.audio = np.concatenate([self.audio] + parts)
        return len(self.audio) / SAMPLE_RATE


def save_wav(path, audio):
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())


class LiveSession:
    """
    Drives one recording session: pulls audio, finds finished phrases with
    the VAD, transcribes them, and decides when the task is over. Separated
    from the microphone so it can be tested with recorded audio files.
    """

    def __init__(self, engine, emit):
        self.engine = engine
        self.emit = emit                  # emit(kind, payload)
        self.audio = np.zeros(0, np.float32)
        self.processed_until = 0          # samples already transcribed
        self.last_voice_end = None        # sample index of the last detected speech
        self.live_steps = []
        self.said_e_at = None
        self.consecutive_unclear = 0
        self.done_reason = None
        self._last_reminder = 0.0

    def feed(self, audio_so_far):
        """Call periodically with the whole recording so far. Returns True when finished."""
        self.audio = audio_so_far
        n = len(self.audio)
        now_s = n / SAMPLE_RATE
        if self.said_e_at is not None and now_s - self.said_e_at >= GRACE_AFTER_E_S:
            self.done_reason = "patient said E"
            return True
        start = max(0, min(self.processed_until, n - int(20 * SAMPLE_RATE)))
        window = self.audio[start:]
        if window.size < int(0.3 * SAMPLE_RATE):
            return False
        segs = [(s + start, e + start) for s, e in find_speech(window)]
        if segs:
            self.last_voice_end = segs[-1][1]
        for s, e in segs:
            finished = e <= n - int(0.25 * SAMPLE_RATE)   # followed by a real pause
            if not finished or e <= self.processed_until:
                continue
            clip = self.audio[max(s, self.processed_until):e]
            self.processed_until = e
            if clip.size < int(0.15 * SAMPLE_RATE):
                continue
            self._handle_phrase(clip)
            if self.said_e_at is not None:
                break
        if self.said_e_at is None and self.last_voice_end is not None:
            if (n - self.last_voice_end) / SAMPLE_RATE >= END_OF_TASK_SILENCE_S:
                self.done_reason = "patient stopped speaking"
                return True
        if now_s >= MAX_TASK_SECONDS:
            self.done_reason = "time limit reached"
            return True
        if (not self.live_steps and self.last_voice_end is None
                and now_s - self._last_reminder >= NO_SPEECH_REMINDER_S):
            self._last_reminder = now_s
            self.emit("status", "I haven't heard anything yet -- please say the path out loud.")
        return False

    def _transcribe_best(self, audio, whole_session=False):
        """
        Normal Whisper pass; if it produced words that are not path steps
        (e.g. "Yay!" for "A"), re-decode restricted to letters/numbers.
        Returns (result, steps, used_constrained).
        """
        res = self.engine.transcribe(audio, whole_session=whole_session)
        steps = _steps_from(res)
        if (unexplained_words(res["words"] or [{"word": w} for w in res["text"].split()])
                and getattr(self.engine, "supports_constrained", False)):
            try:
                res2 = self.engine.transcribe(audio, whole_session=whole_session, constrained=True)
            except Exception as e:  # never let the fallback break the task
                print(f"[warn] constrained re-decode failed: {e}")
                return res, steps, False
            steps2 = _steps_from(res2)
            print(f"[re-check] \"{res['text']}\" -> letters/numbers only: \"{res2['text']}\"")
            if steps2:
                res2["unconstrained_text"] = res["text"]
                return res2, steps2, True
        return res, steps, False

    def _handle_phrase(self, clip):
        res, steps, _ = self._transcribe_best(clip)
        print(f"[heard] \"{res['text']}\" -> {[t for t, _, _ in steps]}")
        if not steps:
            self.consecutive_unclear += 1
            msg = (f"Heard \"{res['text']}\" — that's not a circle on the diagram. "
                   if res["text"] else "I couldn't understand that — ")
            msg += "Please say the next step clearly."
            if self.consecutive_unclear >= MAX_CONSECUTIVE_RETRIES:
                msg += " Try moving closer to the microphone."
            self.emit("status", msg)
            return
        self.consecutive_unclear = 0
        for tok, prob, _ in steps:
            if self.live_steps and self.live_steps[-1][0] == tok:
                continue   # repeated the same step
            self.live_steps.append((tok, prob, tok))
            self.emit("token", tok)
            if tok == "E" and prob >= MIN_WORD_PROB:
                self.said_e_at = len(self.audio) / SAMPLE_RATE
                break
            if len(self.live_steps) >= MAX_TOKENS:
                self.said_e_at = len(self.audio) / SAMPLE_RATE
                break

    def _recheck_low_steps(self, final, steps):
        timed = collapse_repeats([(t, p, w, a, b) for t, p, w, a, b in
                                  parse_word_list(final.get("words") or [], with_times=True)])
        if len(timed) != len(steps):
            return steps
        out = []
        for (tok, prob, word), (_, _, _, start, end) in zip(steps, timed):
            if prob < MIN_WORD_PROB and start is not None and end is not None:
                a = max(0, int((start - 0.3) * SAMPLE_RATE))
                b = min(len(self.audio), int((end + 0.3) * SAMPLE_RATE))
                clip = self.audio[a:b]
                try:
                    kw = {"constrained": True} if getattr(self.engine, "supports_constrained", False) else {}
                    res = self.engine.transcribe(clip, **kw)
                    again = collapse_repeats(_steps_from(res))
                except Exception as e:
                    print(f"[warn] re-check failed: {e}")
                    again = []
                print(f"[re-check] step '{tok}' (score {prob:.2f}) heard again as "
                      f"{[(t, round(p, 2)) for t, p, _ in again]}")
                if len(again) == 1 and again[0][0] == tok:
                    prob = max(prob, again[0][1])
            out.append((tok, prob, word))
        return out

    def final_result(self):
        """Transcribe the whole recording in one pass and score it."""
        constrained = False
        if not self.audio.size or np.max(np.abs(self.audio)) < 1e-4:
            final, steps = {"text": "", "words": []}, []
        else:
            final, steps, constrained = self._transcribe_best(self.audio, whole_session=True)
        # Two independent recognitions of the same answer (live, phrase by
        # phrase, and the final whole-recording pass). When they agree on the
        # exact same sequence, a step counts as confident if EITHER pass was
        # confident about it (Whisper often gives the very first word of a
        # recording a low score even when it is clearly right).
        final_c = collapse_repeats(steps)
        live_c = collapse_repeats(self.live_steps)
        agreed = bool(final_c) and [t for t, _, _ in final_c] == [t for t, _, _ in live_c]
        if agreed:
            steps = [(t, max(p, lp), w) for (t, p, w), (_, lp, _) in zip(final_c, live_c)]
        # Whisper often gives a clearly-heard word a tiny score when the same
        # word could be written several ways ("One" / "one" / "1") -- this
        # happens most to the first word. When the live pass and the final
        # whole-recording pass independently produce the SAME full path, a
        # much lower per-step score is accepted (near-zero still fails).
        score, reason, details = evaluate_path(
            steps, min_prob=MIN_AGREED_WORD_PROB if agreed else MIN_WORD_PROB)
        if score == 0 and details.get("low_confidence_steps") and "first_mistake_step" not in details:
            # right path, but some step was recognised with a low score:
            # listen to just that word again (letters/numbers only) as a check
            steps = self._recheck_low_steps(final, steps)
            score, reason, details = evaluate_path(
                steps, min_prob=MIN_AGREED_WORD_PROB if agreed else MIN_WORD_PROB)
        details["live_and_final_agree"] = agreed
        details["live_steps"] = [(t, round(p, 3)) for t, p, _ in self.live_steps]
        details["letters_numbers_only_redecode"] = constrained
        if constrained:
            details["unconstrained_transcript"] = final.get("unconstrained_text")
        live_tokens = [t for t, _, _ in collapse_repeats(self.live_steps)]
        details.update({"final_transcript": final["text"], "live_sequence": live_tokens,
                        "words": final["words"], "end_reason": self.done_reason})
        return score, reason, details


# --------------------------------------------------------------------------
# 5. Background listener thread
#    Puts ("token", label) or ("status", message) items on the queue for
#    the main thread (which owns the matplotlib window) to consume.
# --------------------------------------------------------------------------
def listener_thread_fn(event_queue: "queue.Queue", stop_event: "threading.Event", holder: dict):
    """Whisper-based listener. Leaves the LiveSession in holder['session']."""
    def emit(kind, payload):
        event_queue.put((kind, payload))

    try:
        emit("status", f"Loading speech recogniser ({WHISPER_MODEL})... first run downloads it.")
        engine = SpeechEngine()
        recorder = MicRecorder()
    except Exception as e:
        emit("fatal_error", f"Could not start speech recognition / microphone ({e}). "
                            f"Check that faster-whisper and sounddevice are installed and "
                            f"microphone permission is granted.")
        return
    session = LiveSession(engine, emit)
    holder["session"], holder["recorder"] = session, recorder
    try:
        recorder.start()
    except Exception as e:
        emit("fatal_error", f"Could not open the microphone ({e}).")
        return
    emit("status", "Ready — speak the path out loud (e.g. \"one\").")
    try:
        while not stop_event.is_set():
            time.sleep(0.25)
            recorder.pull()
            if session.feed(recorder.audio):
                break
    except Exception as e:  # never leave the UI hanging
        emit("fatal_error", f"Speech processing failed ({e}).")
    finally:
        recorder.stop()
        recorder.pull()
        session.audio = recorder.audio
        if recorder.overflows:
            print(f"[mic] warning: {recorder.overflows} input overflows")
        emit("listening_done", session.done_reason or "stopped")


def listener_thread_fn_google(event_queue: "queue.Queue", stop_event: "threading.Event"):
    """ORIGINAL listener (Google web API via SpeechRecognition) -- fallback only."""
    import speech_recognition as sr

    try:
        recognizer = sr.Recognizer()
        mic = sr.Microphone()
    except Exception as e:
        event_queue.put(("fatal_error",
                          f"Could not access the microphone ({e}). "
                          f"Check that PyAudio is installed and mic permission is granted."))
        return

    with mic as source:
        event_queue.put(("status", "Calibrating for background noise... stay quiet a moment."))
        recognizer.adjust_for_ambient_noise(source, duration=1)
        recognizer.dynamic_energy_threshold = False
        print(f"[mic] Calibrated ambient energy threshold: {recognizer.energy_threshold:.0f}")
        event_queue.put(("status", "Ready — speak the first step (e.g. \"one\")."))

        consecutive_retries = 0
        while not stop_event.is_set():
            try:
                audio = recognizer.listen(source, timeout=8, phrase_time_limit=4)
            except sr.WaitTimeoutError:
                event_queue.put(("status", "I didn't hear anything — please speak out loud."))
                continue

            if audioop is not None:
                try:
                    rms = audioop.rms(audio.get_raw_data(), audio.sample_width)
                    print(f"[mic] captured clip, level={rms}")
                except Exception:
                    pass

            try:
                text = recognizer.recognize_google(audio)
            except sr.UnknownValueError:
                consecutive_retries += 1
                msg = ("I heard you but couldn't understand that clearly — "
                       "please speak louder and clearly, one step at a time.")
                if consecutive_retries >= MAX_CONSECUTIVE_RETRIES:
                    msg += " Try moving closer to the microphone."
                event_queue.put(("status", msg))
                continue
            except sr.RequestError as e:
                event_queue.put(("fatal_error",
                                  f"Speech recognition service unavailable ({e}). "
                                  f"Check your internet connection."))
                return

            tokens = parse_tokens(text)
            if not tokens:
                consecutive_retries += 1
                event_queue.put(("status",
                                  f"Heard \"{text}\" — that's not a number or letter on the "
                                  f"diagram. Please say the next step clearly."))
                continue

            consecutive_retries = 0
            for tok in tokens:
                event_queue.put(("token", tok))
                if tok == "E":
                    stop_event.set()
                    return


def _whisper_available():
    try:
        import faster_whisper  # noqa: F401
        import sounddevice  # noqa: F401
        return True, ""
    except Exception as e:
        return False, str(e)


# --------------------------------------------------------------------------
# 6. Main — owns the matplotlib window, drains the queue, draws in real time
# --------------------------------------------------------------------------
def run_task1(show_result=True):
    print("=" * 60)
    print("MoCA Task 1: Trail Making (real-time spoken)")
    print("=" * 60)

    # Voice instruction
    say("I will show you a diagram with circles labeled with numbers and letters. "
        "Your task is to connect them by saying the path out loud, alternating between "
        "numbers and letters: one, A, two, B, three, C, and so on, all the way to E. "
        "Start at one, and keep alternating.")

    use_whisper, why = _whisper_available()
    if not use_whisper:
        print(f"[warn] faster-whisper/sounddevice not available ({why}); "
              f"falling back to the old Google recogniser.")

    diagram = TrailDiagram()
    event_queue = queue.Queue()
    stop_event = threading.Event()
    holder = {}
    if use_whisper:
        listener = threading.Thread(target=listener_thread_fn,
                                    args=(event_queue, stop_event, holder), daemon=True)
    else:
        listener = threading.Thread(target=listener_thread_fn_google,
                                    args=(event_queue, stop_event), daemon=True)
    listener.start()

    path_tokens = []
    last_label = None
    fatal_error = None

    while True:
        try:
            kind, payload = event_queue.get(timeout=0.05)
        except queue.Empty:
            kind = None
            if not use_whisper and not listener.is_alive() and event_queue.empty():
                break

        if kind == "fatal_error":
            fatal_error = payload
            print(f"[ERROR] {payload}")
            diagram.show_status(payload, color="lightcoral")
            break

        elif kind == "status":
            print(f"[info] {payload}")
            diagram.show_status(payload)

        elif kind == "listening_done":
            print(f"[info] Listening finished ({payload}).")
            break

        elif kind == "token":
            label = payload
            expected_index = len(path_tokens)
            correct = (expected_index < len(CORRECT_SEQUENCE)
                       and label == CORRECT_SEQUENCE[expected_index])
            print(f"[step] \"{label}\"  ->  {'correct' if correct else 'MISTAKE'}")

            if last_label is None:
                diagram.mark_start(label, correct)
            else:
                diagram.draw_step(last_label, label, correct)
            diagram.clear_status()

            path_tokens.append(label)
            last_label = label

            if not use_whisper and (label == "E" or len(path_tokens) >= MAX_TOKENS):
                stop_event.set()
                break

        diagram.pump()  # keep the window responsive every loop iteration

    if not use_whisper:
        stop_event.set()
    listener.join(timeout=5 if not use_whisper else 30)

    if fatal_error:
        print("\nCould not complete the task due to a microphone/recognition error above.")
        std = make_task_result(TASK_ID, 0, reason=f"not scored: {fatal_error}", completed=False)
        save_task_result(std)
        if show_result:
            plt.ioff()
            plt.show()
        return std

    # -- final scoring -------------------------------------------------------
    evidence = []
    if use_whisper and holder.get("session") is not None:
        session = holder["session"]
        diagram.show_status("Checking the full recording...", color="lightyellow")
        diagram.pump()
        score, reason, details = session.final_result()
        session_dir = get_session_dir()
        wav = session_dir / "task1_audio.wav"
        save_wav(wav, session.audio)
        (session_dir / "task1_transcript.json").write_text(json.dumps(
            {k: v for k, v in details.items()}, indent=2, default=str))
        evidence = [wav, session_dir / "task1_transcript.json"]
        final_tokens = details["spoken_sequence"]
        if final_tokens != [t for t in collapse_repeats(path_tokens)]:
            print(f"[info] Final transcript differs from live view; showing final: {final_tokens}")
            diagram.draw_path(final_tokens)
    else:
        steps = [(t, 1.0, t) for t in path_tokens]
        score, reason, details = evaluate_path(steps)
        details["backend"] = "google (fallback)"
    diagram.clear_status()
    diagram.show_final_score(score, 1)

    print("\n--- RESULT ---")
    print(f"Expected: {' -> '.join(CORRECT_SEQUENCE)}")
    print(f"Spoken:   {' -> '.join(details['spoken_sequence']) or '(nothing recognized)'}")
    if details.get("final_transcript") is not None:
        print(f"Transcript: \"{details['final_transcript']}\"")
    print(f"Decision: {reason}")
    print(f"SCORE: {score} / 1")

    std = make_task_result(TASK_ID, score, reason=reason, details=details, evidence_files=evidence)
    saved = save_task_result(std)
    print(f"Result saved to: {saved}")

    if show_result:
        plt.ioff()
        plt.show()  # keep the final scored diagram on screen until the window is closed
    else:
        plt.pause(5)   # show the score for a few seconds, then move on
        plt.close(diagram.fig)
    # keep the original keys too
    std.update({"spoken_sequence": details["spoken_sequence"],
                "expected_sequence": CORRECT_SEQUENCE})
    return std


if __name__ == "__main__":
    run_task1()
