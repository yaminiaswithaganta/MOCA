"""
MoCA Task 10 -- Language: letter F fluency (1 point)
====================================================

    Letter F   1 point   at least 11 different words beginning with F in one minute

How it works
-------------
1. The instruction is spoken aloud: "Now say as many words as you can that
   begin with the letter F. You have one minute. Go."
2. Recording runs for up to 60 seconds (or stops after 10 seconds of silence).
   Each DIFFERENT word that begins with F counts once; repeats are ignored.
   "for" and "from" are not counted.
3. Proper names cannot be detected automatically. The saved word list lets the
   examiner check it.

Run
---
    python task10_fluency.py
"""

import time

import matplotlib.pyplot as plt

from moca_common import get_session_dir, make_task_result, save_task_result
from moca_speech import get_engine, listen_for_answer, save_wav, words_of
from moca_voice import speak_instruction

TASK_ID = "task10_fluency"
INSTRUCTION = ("Now say as many words as you can that begin with the letter F. "
               "You have one minute. Go.")
FLUENCY_SECONDS = 60.0
FLUENCY_END_SILENCE = 10.0
FLUENCY_MIN_WORDS = 11
FLUENCY_IGNORE = {"for", "from"}
FLUENCY_PROMPT = "The person says English words that begin with the letter F."


def fluency_points(words):
    """1 point only when at least FLUENCY_MIN_WORDS different F-words were said."""
    return 1 if len(words) >= FLUENCY_MIN_WORDS else 0


def f_words(text):
    """Different words beginning with F, in the order they were said."""
    out = []
    for w in words_of(text):
        if w.startswith("f") and len(w) >= 2 and w not in FLUENCY_IGNORE and w not in out:
            out.append(w)
    return out


class FluencyWindow:
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


def run_task10(show_result=True):
    print("=" * 60)
    print("MoCA Task 10: Language - letter F fluency (one minute)")
    print("=" * 60)
    win = FluencyWindow()
    title = "Language - letter F"
    win.show(title, "", "Loading speech recogniser...")
    win.pump()
    engine = get_engine()
    session_dir = get_session_dir()

    win.show(title, "", INSTRUCTION)
    speak_instruction(INSTRUCTION)
    win.show(title, "", "Say as many F words as you can...", color="#eef6ee")
    ans = listen_for_answer(
        engine, FLUENCY_PROMPT, pump=win.pump,
        status=lambda t: win.show(title, "", t),
        max_seconds=FLUENCY_SECONDS, end_silence=FLUENCY_END_SILENCE, no_speech_timeout=15.0,
        reminder=lambda: win.show(title, "", "Please say words that begin with F.",
                                  color="#ffe9c6"))
    said = (ans["final"] or {}).get("text") or " ".join(p["text"] for p in ans["phrases"])
    words = f_words(said)
    ok = fluency_points(words)
    wav = session_dir / "task10_fluency.wav"
    save_wav(wav, ans["audio"])
    reason = (f"{len(words)} different F-words (need {FLUENCY_MIN_WORDS}) -> {ok}/1: "
              + ", ".join(words))
    print(f"[fluency] {reason}")
    win.show(title, "", f"{len(words)} F-words recorded", color="#eef6ee")
    win.wait(2.0)

    std = make_task_result(TASK_ID, ok, criteria={"fluency": ok}, reason=reason,
                           details={"heard": said, "words": words, "words_counted": len(words),
                                    "end_reason": ans["end_reason"]},
                           evidence_files=[wav])
    print(f"\n--- RESULT ---\n{reason}\nSCORE: {ok} / 1")
    print(f"Result saved to: {save_task_result(std)}")
    if show_result:
        plt.ioff()
        plt.show()
    else:
        plt.pause(3)
        plt.close(win.fig)
    return std


if __name__ == "__main__":
    run_task10()
