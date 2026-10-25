"""
Shared voice helpers for the spoken MoCA tasks (Naming, Memory, ...)
====================================================================

Re-uses Task 1's speech pipeline (continuous microphone recording, Silero
voice-activity detection, offline Whisper) and adds:

* `listen_for_answer()` - record ONE spoken answer: waits for the person to
  start, lets them pause and correct themselves, stops after a real pause,
  then re-transcribes the whole answer in one pass for accuracy.
* word matching that tolerates accents / pronunciation / spelling variants
  (alias lists + "one letter off" fuzzy matching), used by the tasks to
  decide whether an expected word was said.
"""

import re
import subprocess
import sys
import time

import numpy as np

from moca_voice import speak_instruction
from task1_trail_making import (SAMPLE_RATE, MicRecorder, SpeechEngine, find_speech,
                                save_wav)

_ENGINE = None


def get_engine():
    """Load Whisper once and share it between tasks."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = SpeechEngine()
    return _ENGINE


def speak(text):
    """Read text aloud (shared moca_voice module)."""
    speak_instruction(text)


# --------------------------------------------------------------------------
# Word normalisation + fuzzy matching
# --------------------------------------------------------------------------
def words_of(text):
    """'It's a Lion!' -> ['it's', 'a', 'lion']"""
    return [w for w in re.findall(r"[a-z']+", text.lower().replace("’", "'")) if w.strip("'")]


def damerau(a, b):
    """Edit distance counting a swap of two neighbouring letters as one edit."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def find_mentions(words, vocab):
    """
    Find which vocabulary items were said, in order.

    vocab: {key: {"accept": set_of_exact_words, "fuzzy": [base words],
                  "max_edit": int, "reject": set_of_similar_real_words}}
    Also joins neighbouring words, so "lie on" -> "lion", "rhino ceros" ->
    "rhinoceros". Returns list of (key, index_of_word, heard_text).
    """
    out = []
    i = 0
    while i < len(words):
        hit = None
        for span in (2, 1):                      # prefer the longer join
            if i + span > len(words):
                continue
            cand = "".join(words[i:i + span]).replace("'", "")
            key = _match_one(cand, vocab, allow_fuzzy=(span == 1 or len(cand) >= 6))
            if key:
                hit = (key, i, " ".join(words[i:i + span]))
                i += span
                break
        if hit:
            out.append(hit)
        else:
            i += 1
    return out


def _match_one(w, vocab, allow_fuzzy=True):
    for key, v in vocab.items():
        if w in v["accept"]:
            return key
    if not allow_fuzzy or len(w) < 4:
        return None
    best = None
    for key, v in vocab.items():
        if w in v.get("reject", ()):
            continue
        for base in v.get("fuzzy", ()):
            limit = v.get("max_edit", 1) if len(base) >= 7 else 1
            dist = damerau(w, base)
            if dist <= limit and (best is None or dist < best[0]):
                best = (dist, key)
    return best[1] if best else None


# --------------------------------------------------------------------------
# Recording one spoken answer
# --------------------------------------------------------------------------
def listen_for_answer(engine, prompt, pump=None, status=None, max_seconds=20.0,
                      end_silence=2.0, no_speech_timeout=12.0, is_done=None,
                      grace_after_done=1.5, reminder=None, recorder=None):
    """
    Record one spoken answer and transcribe it.

    * waits up to `no_speech_timeout` s for the person to start talking,
    * lets them pause (a phrase ends after ~1.2 s of silence, the answer after
      `end_silence` s) and correct themselves,
    * `is_done(phrase_texts)` can end early (e.g. an animal name was heard),
    * finally re-transcribes the whole answer in one pass.

    Returns dict(audio, phrases=[{"text", "words"}], final={"text","words"}|None,
                 end_reason, heard_speech).
    `pump()` is called often to keep the window responsive.
    """
    own_recorder = recorder is None
    if own_recorder:
        recorder = MicRecorder()
        recorder.start()
    t0 = time.time()
    phrases = []
    processed = 0
    last_voice_end = None
    done_at = None
    reminded = False
    end_reason = "time limit reached"
    try:
        while True:
            if pump:
                pump()
            time.sleep(0.1)
            recorder.pull()
            audio = recorder.audio
            n = len(audio)
            now = n / SAMPLE_RATE
            if done_at is not None and time.time() - done_at >= grace_after_done:
                end_reason = "answer given"
                break
            start = max(0, min(processed, n - int(20 * SAMPLE_RATE)))
            window = audio[start:]
            if window.size >= int(0.3 * SAMPLE_RATE):
                segs = [(s + start, e + start) for s, e in find_speech(window)]
                if segs:
                    last_voice_end = segs[-1][1]
                for s, e in segs:
                    if e > n - int(0.25 * SAMPLE_RATE) or e <= processed:
                        continue          # still talking / already done
                    clip = audio[max(s, processed):e]
                    processed = e
                    if clip.size < int(0.15 * SAMPLE_RATE):
                        continue
                    res = engine.transcribe(clip, prompt=prompt)
                    print(f"[heard] \"{res['text']}\"")
                    if res["text"]:
                        phrases.append(res)
                        if status:
                            status(f"Heard: \"{res['text']}\"")
                    if is_done and done_at is None and is_done([p["text"] for p in phrases]):
                        done_at = time.time()
            if last_voice_end is not None and done_at is None and \
                    (n - last_voice_end) / SAMPLE_RATE >= end_silence and \
                    processed >= last_voice_end - int(0.3 * SAMPLE_RATE):
                end_reason = "person stopped speaking"
                break
            if last_voice_end is None and reminder and not reminded and now >= no_speech_timeout / 2:
                reminded = True
                reminder()
            if last_voice_end is None and now >= no_speech_timeout:
                end_reason = "no answer"
                break
            if time.time() - t0 >= max_seconds:
                break
    finally:
        if own_recorder:
            recorder.stop()
            recorder.pull()
    audio = recorder.audio
    heard = last_voice_end is not None
    final = None
    if heard and audio.size:
        try:
            final = engine.transcribe(audio, whole_session=True, prompt=prompt)
        except Exception as e:
            print(f"[warn] final transcription failed: {e}")
    return {"audio": audio, "phrases": phrases, "final": final, "end_reason": end_reason,
            "heard_speech": heard}


def word_prob(result, index_in_words_of_text):
    """Whisper's confidence for the n-th word of result['text'] (1.0 if unknown)."""
    wl = result.get("words") or []
    flat = []
    for w in wl:
        for piece in words_of(w["word"]):
            flat.append(float(w.get("prob", 1.0)))
    if 0 <= index_in_words_of_text < len(flat):
        return flat[index_in_words_of_text]
    return 1.0


__all__ = ["get_engine", "speak", "words_of", "damerau", "find_mentions",
           "listen_for_answer", "word_prob", "save_wav", "SAMPLE_RATE"]


# --------------------------------------------------------------------------
# Spoken numbers -> integers / digits
# --------------------------------------------------------------------------
_UNITS = {"zero": 0, "oh": 0, "o": 0, "one": 1, "won": 1, "two": 2, "to": 2, "too": 2,
          "three": 3, "tree": 3, "four": 4, "for": 4, "fore": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "ate": 8, "nine": 9}
_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_STRONG_UNITS = {k: v for k, v in _UNITS.items() if k not in ("to", "too", "for", "o", "ate")}


def _tokens(text):
    t = text.lower().replace("-", " ").replace(",", " ").replace(".", " ")
    return [w for w in re.findall(r"[a-z]+|\d+", t)]


def numbers_of(text):
    """
    'ninety-three, 86, seventy nine' -> [93, 86, 79].  Handles digits, number
    words, 'one hundred', 'ninety three'. Ambiguous words ('to', 'for') only
    count when they are clearly numbers (not between two other numbers).
    """
    toks = _tokens(text)
    out = []
    i = 0
    while i < len(toks):
        w = toks[i]
        if w.isdigit():
            out.append(int(w))
            i += 1
            continue
        if w in _TENS:
            val = _TENS[w]
            if i + 1 < len(toks) and toks[i + 1] in _STRONG_UNITS and _STRONG_UNITS[toks[i + 1]] > 0:
                val += _STRONG_UNITS[toks[i + 1]]
                i += 1
            out.append(val)
            i += 1
            continue
        if w in _TEENS:
            out.append(_TEENS[w])
            i += 1
            continue
        if w == "hundred":
            if out and out[-1] < 10:
                out[-1] *= 100
            else:
                out.append(100)
            i += 1
            continue
        if w in _STRONG_UNITS:
            out.append(_STRONG_UNITS[w])
            i += 1
            continue
        i += 1
    # "one hundred" -> [100] ; "hundred and" etc. handled above
    return out


def digits_of(text):
    """
    Spoken digit sequence -> list of single digits.
    '2 1 8 5 4' / '21854' / 'two, one, eight, five, four' -> [2, 1, 8, 5, 4]
    """
    out = []
    toks = _tokens(text)
    for i, w in enumerate(toks):
        if w.isdigit():
            out.extend(int(c) for c in w)
        elif w in _UNITS and w != "o":
            # in a spoken digit list, "to"/"too"/"for"/"ate" are almost always 2/2/4/8
            out.append(_UNITS[w])
        elif w in _TEENS:
            out.extend(int(c) for c in str(_TEENS[w]))
        elif w in _TENS:
            out.extend(int(c) for c in str(_TENS[w])[:1])
    return out
