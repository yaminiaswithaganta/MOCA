"""
MoCA Task 12 -- Delayed Recall (5 points)
=========================================

The five words from Task 5 -- FACE, VELVET, CHURCH, DAISY, RED -- are recalled
by voice, with no cues. Each word recalled unprompted scores 1 point.

How it works
-------------
1. The examiner asks the patient to recall the words from the earlier list.
2. The answer is transcribed offline (Whisper) and matched to the list with
   the same accent / spelling tolerance as Task 5 (task5_memory.recalled_words).
   A word counts if either the final or the live transcript heard it.
3. Words the patient does not say are not prompted (the MoCA sheet's optional
   cued recall is not part of the score).

Run
---
    python task12_delayed_recall.py
"""

import time

import matplotlib.pyplot as plt

from moca_common import get_session_dir, make_task_result, save_task_result
from moca_speech import get_engine, listen_for_answer, save_wav, speak
from task5_memory import WORDS, recalled_words

TASK_ID = "task12_delayed_recall"
QUESTION = ("Earlier I read you a list of words. Please tell me as many of those words "
            "as you can remember, in any order.")
PROMPT = "The person recalls a short list of words said earlier."
ANSWER_SECONDS = 45.0
ANSWER_END_SILENCE = 3.0
NO_SPEECH_TIMEOUT = 20.0


class RecallWindow:
    def __init__(self):
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(8, 6))
        self.ax.axis("off")

    def show(self, title, big="", small="", color="white"):
        self.ax.clear()
        self.ax.axis("off")
        self.ax.set_title(title, fontsize=15)
        self.ax.text(0.5, 0.55, big, ha="center", va="center", fontsize=30, weight="bold",
                     transform=self.ax.transAxes)
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


def run_task12(show_result=True):
    print("=" * 60)
    print("MoCA Task 12: Delayed Recall (5 words, no cues)")
    print("=" * 60)
    win = RecallWindow()
    title = "Delayed recall"
    win.show(title, "", "Loading speech recogniser...")
    win.pump()
    engine = get_engine()
    session_dir = get_session_dir()

    win.show(title, "", QUESTION)
    speak(QUESTION)
    win.show(title, "", "Say the words you remember, out loud.", color="#eef6ee")
    ans = listen_for_answer(
        engine, PROMPT, pump=win.pump,
        status=lambda t: win.show(title, "", t),
        max_seconds=ANSWER_SECONDS, end_silence=ANSWER_END_SILENCE,
        no_speech_timeout=NO_SPEECH_TIMEOUT,
        reminder=lambda: win.show(title, "", "Please say the words you remember.",
                                  color="#ffe9c6"))
    final_text = (ans["final"] or {}).get("text", "")
    live_text = " ".join(p["text"] for p in ans["phrases"])
    rec_final, intrusions = recalled_words(final_text)
    rec_live, _ = recalled_words(live_text)
    recalled = [w for w in WORDS if w in rec_final or w in rec_live]

    criteria = {w.lower(): int(w in recalled) for w in WORDS}
    score = sum(criteria.values())
    missed = [w for w in WORDS if w not in recalled]
    reason = f"recalled {score} of {len(WORDS)}: {', '.join(recalled) or 'none'}"
    if missed:
        reason += f" (missed: {', '.join(missed)})"

    wav = session_dir / "task12_delayed_recall.wav"
    save_wav(wav, ans["audio"])
    print(f"[recall] heard \"{final_text or live_text}\"")
    print(f"SCORE: {score} / {len(WORDS)}  ({reason})")
    win.show(title, "", f"RECALL SCORE: {score} / {len(WORDS)}", color="#eef6ee")

    std = make_task_result(
        TASK_ID, score, criteria=criteria, reason=reason,
        details={"recalled": recalled, "missed": missed, "intrusions": intrusions,
                 "transcript": final_text or live_text,
                 "live_transcripts": [p["text"] for p in ans["phrases"]],
                 "end_reason": ans["end_reason"]},
        evidence_files=[wav])
    print(f"Result saved to: {save_task_result(std)}")
    if show_result:
        plt.ioff()
        plt.show()
    else:
        plt.pause(3)
        plt.close(win.fig)
    return std


if __name__ == "__main__":
    run_task12()
