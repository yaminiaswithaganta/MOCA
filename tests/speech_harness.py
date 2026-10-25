"""
Offline end-to-end test harness for Task 1's voice pipeline.

Synthesises spoken answers with several different TTS voices (US / UK
accents, male / female, slow / fast, pauses, quiet, background noise), then
runs them through the SAME LiveSession code Task 1 uses (VAD -> phrase
segmentation -> transcription -> parsing -> final whole-recording pass ->
all-or-nothing score).

Test-only dependencies (NOT needed to run the tasks):
    pip install sherpa-onnx
    TTS voices : vits-piper-* from github.com/k2-fsa/sherpa-onnx/releases (tts-models)
    ASR stand-in: sherpa-onnx-whisper-small.en (same Whisper small.en weights, ONNX
                  export) -- used when the faster-whisper model can't be downloaded.
Set MOCA_TTS_DIR / MOCA_SHERPA_WHISPER_DIR to their folders.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import task1_trail_making as t1  # noqa: E402

TTS_DIR = os.environ.get("MOCA_TTS_DIR", "/tmp/tts")
SHERPA_WHISPER_DIR = os.environ.get("MOCA_SHERPA_WHISPER_DIR", "/tmp/sherpa-onnx-whisper-small.en")
SR = t1.SAMPLE_RATE


def _resample(x, sr_in, sr_out=SR):
    if sr_in == sr_out:
        return x.astype(np.float32)
    n = int(len(x) * sr_out / sr_in)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


class Voice:
    def __init__(self, folder):
        import sherpa_onnx
        name = os.path.basename(folder).replace("vits-piper-", "")
        cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=os.path.join(folder, name + ".onnx"),
                tokens=os.path.join(folder, "tokens.txt"),
                data_dir=os.path.join(folder, "espeak-ng-data")),
            num_threads=2))
        self.name = name
        self.tts = sherpa_onnx.OfflineTts(cfg)

    def say(self, text, speed=1.0):
        a = self.tts.generate(text, sid=0, speed=speed)
        return _resample(np.array(a.samples, np.float32), a.sample_rate)


def voices():
    out = []
    for d in sorted(os.listdir(TTS_DIR)):
        if d.startswith("vits-piper-"):
            out.append(Voice(os.path.join(TTS_DIR, d)))
    return out


def build_answer(voice, parts, rng, pause=(0.4, 1.2), speed=1.0, volume=0.8, noise_db=None,
                 lead=1.0, tail=13.0):
    """parts: list of strings spoken with pauses between them."""
    chunks = [np.zeros(int(lead * SR), np.float32)]
    for i, p in enumerate(parts):
        a = voice.say(p, speed=speed)
        chunks.append(a)
        if i < len(parts) - 1:
            chunks.append(np.zeros(int(rng.uniform(*pause) * SR), np.float32))
    chunks.append(np.zeros(int(tail * SR), np.float32))
    x = np.concatenate(chunks)
    x = x / (np.max(np.abs(x)) + 1e-9) * volume
    if noise_db is not None:   # background noise at the given SNR
        sig_rms = np.sqrt(np.mean(x[np.abs(x) > 0.02 * volume] ** 2) + 1e-12)
        noise = rng.normal(size=x.size).astype(np.float32)
        noise = np.convolve(noise, np.ones(4) / 4, mode="same")      # a bit less hissy
        noise *= sig_rms / (np.sqrt(np.mean(noise ** 2)) * 10 ** (noise_db / 20))
        x = x + noise
    return x.astype(np.float32)


class SherpaWhisperEngine:
    """Same interface as t1.SpeechEngine, backed by sherpa-onnx Whisper (test stand-in)."""

    def __init__(self, folder=SHERPA_WHISPER_DIR):
        import sherpa_onnx
        size = os.path.basename(folder).replace("sherpa-onnx-whisper-", "")
        self.rec = sherpa_onnx.OfflineRecognizer.from_whisper(
            encoder=os.path.join(folder, f"{size}-encoder.int8.onnx"),
            decoder=os.path.join(folder, f"{size}-decoder.int8.onnx"),
            tokens=os.path.join(folder, f"{size}-tokens.txt"),
            language="en", task="transcribe", num_threads=2)
        self.model_size = "sherpa-" + size

    def _one(self, audio):
        s = self.rec.create_stream()
        s.accept_waveform(SR, t1._normalise_level(audio))
        self.rec.decode_stream(s)
        return s.result.text.strip()

    def transcribe(self, audio, whole_session=False, **_ignored):
        if whole_session:
            segs = t1.find_speech(audio, min_silence_s=0.5)
            texts = []
            # whisper handles up to 30 s at a time: group speech into <=25 s chunks
            cur, cur_len = [], 0
            for s, e in segs:
                piece = audio[max(0, s - 2400):e + 2400]
                if cur_len + len(piece) > 25 * SR and cur:
                    texts.append(self._one(np.concatenate(cur)))
                    cur, cur_len = [], 0
                cur += [piece, np.zeros(int(0.3 * SR), np.float32)]
                cur_len += len(piece) + int(0.3 * SR)
            if cur:
                texts.append(self._one(np.concatenate(cur)))
            text = " ".join(t for t in texts if t)
        else:
            text = self._one(audio)
        return {"text": text, "words": [{"word": w, "prob": 1.0} for w in text.split()]}


def run_session(engine, audio, step=0.25):
    """Feed audio as if it arrived live from the microphone."""
    events = []
    sess = t1.LiveSession(engine, lambda k, p: events.append((k, p)))
    n = len(audio)
    pos = 0
    while pos < n:
        pos = min(n, pos + int(step * SR))
        if sess.feed(audio[:pos]):
            break
    sess.audio = audio[:pos]
    score, reason, details = sess.final_result()
    return score, reason, details, events, pos / SR


CORRECT_WORDS = ["one", "A", "two", "B", "three", "C", "four", "D", "five", "E"]


def scenarios():
    """(name, expected_score, parts, build kwargs)"""
    return [
        ("one step at a time", 1, CORRECT_WORDS, dict(pause=(0.8, 2.0))),
        ("long pauses (3-4 s)", 1, CORRECT_WORDS, dict(pause=(3.0, 4.0))),
        ("all in one breath", 1, ["1, A, 2, B, 3, C, 4, D, 5, E"], {}),
        ("pairs", 1, ["one, A", "two, B", "three, C", "four, D", "five, E"], dict(pause=(0.6, 1.5))),
        ("slow speaker", 1, CORRECT_WORDS, dict(speed=0.7, pause=(1.0, 2.5))),
        ("fast speaker", 1, ["1, A, 2, B, 3, C, 4, D, 5, E"], dict(speed=1.5)),
        ("quiet voice", 1, CORRECT_WORDS, dict(volume=0.05, pause=(0.6, 1.5))),
        ("noisy room (15 dB SNR)", 1, CORRECT_WORDS, dict(noise_db=15, pause=(0.6, 1.5))),
        ("with filler words", 1, ["one", "then A", "then two", "B", "three", "and C", "four",
                                  "D", "five", "and E"], dict(pause=(0.6, 1.5))),
        ("WRONG: D and C swapped", 0, ["one", "A", "two", "B", "three", "D", "four", "C", "five", "E"],
         dict(pause=(0.6, 1.5))),
        ("WRONG: D skipped", 0, ["one", "A", "two", "B", "three", "C", "four", "five", "E"],
         dict(pause=(0.6, 1.5))),
        ("WRONG: numbers then letters", 0, ["1, 2, 3, 4, 5, A, B, C, D, E"], {}),
        ("WRONG: stops at 3", 0, ["one", "A", "two", "B", "three"], dict(pause=(0.6, 1.5))),
        ("WRONG: ends with F", 0, ["one", "A", "two", "B", "three", "C", "four", "D", "five", "F"],
         dict(pause=(0.6, 1.5))),
        ("silence only", 0, [], {}),
    ]


def run_all(engine=None, voice_names=None, verbose=True, seed=0):
    rng = np.random.default_rng(seed)
    engine = engine or SherpaWhisperEngine()
    results = []
    for v in voices():
        if voice_names and v.name not in voice_names:
            continue
        for name, expected, parts, kw in scenarios():
            if parts:
                audio = build_answer(v, parts, rng, **kw)
            else:
                audio = (rng.normal(size=12 * SR) * 0.002).astype(np.float32)
            score, reason, details, events, dur = run_session(engine, audio)
            ok = score == expected
            results.append((v.name, name, expected, score, ok, details))
            if verbose:
                print(f"{'OK ' if ok else 'XX '} {v.name:32s} {name:30s} exp={expected} got={score} "
                      f"live={''.join(details['live_sequence'])} final={''.join(details['spoken_sequence'])} "
                      f"end={details.get('end_reason')} t={dur:.0f}s | \"{details['final_transcript'][:70]}\"",
                      flush=True)
    return results


if __name__ == "__main__":
    names = sys.argv[1:] or None
    res = run_all(voice_names=names)
    bad = [r for r in res if not r[4]]
    false_pos = [r for r in bad if r[3] == 1]
    print(f"\n{len(res) - len(bad)}/{len(res)} correct; false 1s (wrong path scored correct): {len(false_pos)}")
