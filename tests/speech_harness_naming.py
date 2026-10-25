"""
End-to-end check of Task 4 (Naming) and Task 5 (Memory) voice handling with
synthesised voices (see speech_harness.py for the test-only requirements).
Runs the real listen_for_answer() -> judge_answer()/recalled_words() path,
feeding the synthetic audio as if it came from the microphone.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import speech_harness as sh  # noqa: E402
from moca_speech import listen_for_answer  # noqa: E402
import task4_naming as t4  # noqa: E402
import task5_memory as t5  # noqa: E402

SR = sh.SR


class FakeRecorder:
    """Pretends to be the microphone: releases the prepared audio 0.1 s per pull."""
    def __init__(self, audio):
        self.full = audio
        self.pos = 0
        self.audio = audio[:0]

    def pull(self):
        self.pos = min(len(self.full), self.pos + int(0.1 * SR))
        if self.pos >= len(self.full):     # afterwards: silence
            self.full = np.concatenate([self.full, np.zeros(int(0.1 * SR), np.float32)])
        self.audio = self.full[:self.pos]
        return self.pos / SR

    def start(self):
        pass

    def stop(self):
        pass


NAMING = [("lion", "lion", 1), ("lion", "It's a lion.", 1), ("rhino", "rhinoceros", 1),
          ("rhino", "a rhino", 1), ("camel", "camel", 1), ("camel", "It is a camel.", 1),
          ("camel", "dromedary", 1),
          ("lion", "tiger", 0), ("rhino", "hippopotamus", 0), ("camel", "horse", 0),
          ("lion", "I don't know.", 0), ("camel", None, 0)]


def run(voice_names=None, verbose=True):
    import time
    orig_sleep = time.sleep
    time.sleep = lambda s: None          # run faster than real time
    try:
        eng = sh.SherpaWhisperEngine()
        rng = np.random.default_rng(0)
        out = []
        for v in sh.voices():
            if voice_names and v.name not in voice_names:
                continue
            for target, text, exp in NAMING:
                audio = sh.build_answer(v, [text], rng, tail=4.0) if text else \
                    np.zeros(14 * SR, np.float32)
                ans = listen_for_answer(eng, t4.PROMPT, recorder=FakeRecorder(audio),
                                        max_seconds=1e9, no_speech_timeout=12.0,
                                        is_done=lambda ts: any(t4.find_mentions(t4.words_of(x), t4.ALL_VOCAB) for x in ts),
                                        grace_after_done=0.0)
                score, reason, _ = t4.judge_answer(target, ans["phrases"], ans["final"])
                ok = score == exp
                out.append(("naming", v.name, target, text, exp, score, ok))
                if verbose:
                    print(f"{'OK ' if ok else 'XX '} naming {v.name:34s} {target:6s} said={text!r:18} "
                          f"exp={exp} got={score} | {reason}", flush=True)
            for parts, exp_n in [(["face", "velvet", "church", "daisy", "red"], 5),
                                 (["face, velvet", "church", "daisy, red"], 5),
                                 (["red", "face", "daisy"], 3)]:
                audio = sh.build_answer(v, parts, rng, pause=(0.5, 1.2), tail=5.0)
                ans = listen_for_answer(eng, t5.PROMPT, recorder=FakeRecorder(audio),
                                        max_seconds=1e9, end_silence=3.0, no_speech_timeout=15.0)
                text = (ans["final"] or {}).get("text", "")
                rec, intr = t5.recalled_words(text)
                live, _ = t5.recalled_words(" ".join(p["text"] for p in ans["phrases"]))
                got = [w for w in t5.WORDS if w in rec or w in live]
                ok = len(got) == exp_n
                out.append(("memory", v.name, parts, exp_n, len(got), ok))
                if verbose:
                    print(f"{'OK ' if ok else 'XX '} memory {v.name:34s} said={parts} got={got} "
                          f"heard=\"{text}\"", flush=True)
        return out
    finally:
        time.sleep = orig_sleep


if __name__ == "__main__":
    res = run(sys.argv[1:] or None)
    bad = [r for r in res if not r[-1]]
    false_pos = [r for r in bad if r[0] == "naming" and r[5] == 1]
    print(f"\n{len(res) - len(bad)}/{len(res)} as expected; wrong names scored correct: {len(false_pos)}")
