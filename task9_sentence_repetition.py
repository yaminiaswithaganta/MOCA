"""
MoCA Task 9 -- Language: sentence repetition (2 points)
=======================================================

    Sentence 1   1 point   repeated correctly
    Sentence 2   1 point   repeated correctly

How it works
-------------
1. The instruction is spoken aloud: "I am going to read you two sentences.
   Listen carefully, then repeat each sentence exactly as you heard it."
2. Each sentence is spoken aloud, then the voice says "Now repeat the
   sentence." The patient repeats it.
3. The answer is transcribed offline (Whisper) and compared word by word with
   the sentence. A sentence counts as repeated when at least REPEAT_MIN_RATIO
   of its words were said, in order. A word spelled one letter differently
   still counts. Set REPEAT_MIN_RATIO = 1.0 for strict MoCA scoring.

Run
---
    python task9_sentence_repetition.py
"""

import time

import matplotlib.pyplot as plt

from moca_common import get_session_dir, make_task_result, save_task_result
from moca_speech import damerau, get_engine, listen_for_answer, save_wav, words_of
from moca_voice import speak_instruction

TASK_ID = "task9_sentence_repetition"
SENTENCES = [
    "I only know that John is the one to help today.",
    "The cat always hid under the couch when dogs were in the room.",
]
INTRO = ("I am going to read you two sentences. Listen carefully, then repeat each sentence "
         "exactly as you heard it.")
REPEAT_MIN_RATIO = 0.9
REPEAT_PROMPT = "The person repeats a sentence that was read to them."
ANSWER_SECONDS = 30.0
ANSWER_END_SILENCE = 2.5
NO_SPEECH_TIMEOUT = 15.0


def _same_word(a, b):
    return a == b or (len(a) >= 4 and damerau(a, b) <= 1)


def repetition_ratio(target, said):
    """Share of the target's words that were said, in order (fuzzy longest common subsequence)."""
    t, s = words_of(target), words_of(said)
    if not t:
        return 0.0
    prev = [0] * (len(s) + 1)
    for tw in t:
        cur = [0]
        for j, sw in enumerate(s, 1):
            best = max(prev[j], cur[j - 1])
            if _same_word(tw, sw):
                best = max(best, prev[j - 1] + 1)
            cur.append(best)
        prev = cur
    return prev[-1] / len(t)


class SentenceWindow:
    def __init__(self):
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(8, 6))
        self.ax.axis("off")

    def show(self, title, big="", small="", color="white"):
        self.ax.clear()
        self.ax.axis("off")
        self.ax.set_title(title, fontsize=15)
        self.ax.text(0.5, 0.55, big, ha="center", va="center", fontsize=28, weight="bold",
                     transform=self.ax.transAxes, wrap=True)
        self.ax.text(0.5, 0.15, small, ha="center", va="center", fontsize=14,
                     transform=self.ax.transAxes, wrap=True)
        self.fig.patch.set_facecolor(color)
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()

    def pump(self):
        plt.pause(0.03)

    def wait(self, seconds):
        t = time.time() + seconds
        while time.time() < t:
            self.pump()


def run_task9(show_result=True):
    print("=" * 60)
    print("MoCA Task 9: Language - sentence repetition (2 sentences)")
    print("=" * 60)
    win = SentenceWindow()
    win.show("Language - sentences", "", "Loading speech recogniser...")
    win.pump()
    engine = get_engine()
    session_dir = get_session_dir()

    # spoken instruction for the whole part
    win.show("Language - sentences", "", INTRO)
    speak_instruction(INTRO)
    win.wait(1.0)

    results, evidence = [], []
    for i, sentence in enumerate(SENTENCES, 1):
        title = f"Language - sentence {i} of {len(SENTENCES)}"
        win.show(title, "", "Listen to the sentence.")
        speak_instruction(sentence)                       # the examiner's sentence
        prompt = "Now repeat the sentence."
        win.show(title, "", prompt, color="#eef6ee")
        speak_instruction(prompt)
        ans = listen_for_answer(
            engine, REPEAT_PROMPT, pump=win.pump,
            status=lambda t, ti=title: win.show(ti, "", t),
            max_seconds=ANSWER_SECONDS, end_silence=ANSWER_END_SILENCE,
            no_speech_timeout=NO_SPEECH_TIMEOUT,
            reminder=lambda ti=title: win.show(ti, "", "Please repeat the sentence out loud.",
                                               color="#ffe9c6"))
        said = (ans["final"] or {}).get("text") or " ".join(p["text"] for p in ans["phrases"])
        ratio = repetition_ratio(sentence, said)
        ok = int(ratio >= REPEAT_MIN_RATIO)
        wav = session_dir / f"task9_sentence{i}.wav"
        save_wav(wav, ans["audio"])
        evidence.append(wav)
        results.append({"sentence": sentence, "heard": said, "match": round(ratio, 3),
                        "score": ok, "end_reason": ans["end_reason"]})
        print(f"[sentence {i}] {ok}/1  match {ratio:.2f}  heard \"{said}\"")
        win.show(title, "", f"Recorded: \"{said or '(nothing)'}\"", color="lightgray")
        win.wait(1.5)

    criteria = {f"sentence_{i}": r["score"] for i, r in enumerate(results, 1)}
    score = sum(criteria.values())
    reason = "; ".join(f"sentence {i}: {r['score']}/1" for i, r in enumerate(results, 1))
    win.show("Language - sentences finished", "", f"SENTENCE SCORE: {score} / 2", color="#eef6ee")
    std = make_task_result(TASK_ID, score, criteria=criteria, reason=reason,
                           details={"sentences": results}, evidence_files=evidence)
    print(f"\n--- RESULT ---\n{reason}\nSCORE: {score} / 2")
    print(f"Result saved to: {save_task_result(std)}")
    if show_result:
        plt.ioff()
        plt.show()
    else:
        plt.pause(3)
        plt.close(win.fig)
    return std


if __name__ == "__main__":
    run_task9()
