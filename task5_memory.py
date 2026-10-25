"""
MoCA Task 5 — Memory (learning trials, NO points)
==================================================

How it works
-------------
The five words FACE, VELVET, CHURCH, DAISY, RED are presented and the
patient repeats them -- twice (trial 1 and trial 2), as on the MoCA sheet.
No points are given here; the recall results are saved so the Delayed Recall
task can use them later.

For each trial:
  1. "Listen carefully..." -- the words are shown on screen one per second
     (and read aloud on a Mac with the built-in voice; set READ_ALOUD = False
     to only show them).
  2. The words disappear and the patient says all the words they remember,
     in any order. Recording stops after a ~3 s pause (or 30 s).
  3. The answer is transcribed offline (Whisper) and matched to the list,
     tolerating accents / spelling variants ("welvet", "daisies", "chuch").
     Words not on the list are saved as intrusions.

Result (saved to results/<session>/task5_memory.json):
  trials: [{"recalled": ["FACE", "RED"], "intrusions": [...], "transcript": "..."}, ...]
  score: 0 / max 0  (memory registration is not scored in the MoCA)

Run
---
    python task5_memory.py
"""

import time

import matplotlib.pyplot as plt

from moca_common import get_session_dir, make_task_result, save_task_result
from moca_speech import (find_mentions, get_engine, listen_for_answer, save_wav, speak,
                         words_of)

TASK_ID = "task5_memory"
WORDS = ["FACE", "VELVET", "CHURCH", "DAISY", "RED"]
N_TRIALS = 2
READ_ALOUD = True          # also say the words (macOS built-in voice)
SECONDS_PER_WORD = 1.0     # MoCA: one word per second
SHOW_WORDS_WHILE_ANSWERING = False

WORD_VOCAB = {
    "FACE": {"accept": {"face", "faces", "fase", "fays", "phase", "fes"}, "fuzzy": ["face"],
             "reject": {"fact", "fake", "fame", "fare", "race", "pace", "lace", "fade", "facts"}},
    "VELVET": {"accept": {"velvet", "velvets", "welvet", "velvit", "valvet", "vellvet",
                          "velvette", "velvette"},
               "fuzzy": ["velvet"], "reject": {"vervet"}},
    "CHURCH": {"accept": {"church", "churches", "chruch", "chuch", "charch", "cherch", "shurch"},
               "fuzzy": ["church"], "reject": {"crutch", "chunch"}},
    "DAISY": {"accept": {"daisy", "daisies", "daisey", "daizy", "dasy", "dazy", "deisy", "daysy"},
              "fuzzy": ["daisy"], "reject": {"dizzy", "daily", "dairy", "lazy", "crazy", "dais"}},
    "RED": {"accept": {"red", "read", "redd"}, "fuzzy": [],
            "reject": set()},
}
FILLERS = {"and", "um", "uh", "er", "erm", "the", "a", "i", "think", "remember", "that's", "it",
           "was", "is", "there", "then", "also", "so", "okay", "ok", "yeah", "yes", "no",
           "hmm", "mm", "like", "what", "else", "one", "more", "word", "words", "sorry",
           "don't", "dont", "know", "can't", "cant", "oh", "well", "let", "me", "see"}
PROMPT = "The person repeats a short list of words from memory."


def recalled_words(text):
    """Transcript -> (recalled list in list order, intrusion words)."""
    ws = words_of(text)
    hits = find_mentions(ws, WORD_VOCAB)
    recalled = [w for w in WORDS if any(h[0] == w for h in hits)]
    used = set()
    for _, idx, heard in hits:
        used.update(range(idx, idx + len(heard.split())))
    intrusions = [w for i, w in enumerate(ws) if i not in used and w not in FILLERS]
    return recalled, intrusions


class MemoryWindow:
    def __init__(self):
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(8, 6))
        self.ax.axis("off")

    def show(self, title, big="", small="", color="white"):
        self.ax.clear()
        self.ax.axis("off")
        self.ax.set_title(title, fontsize=15)
        self.ax.text(0.5, 0.55, big, ha="center", va="center", fontsize=44, weight="bold",
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


def present_words(win, trial):
    intro = ("Listen carefully. I will show you a list of words to remember.\n"
             "When I am done, say back as many words as you can remember, in any order."
             if trial == 1 else
             "I am going to show you the same list again. Say back as many words as you\n"
             "can remember, including words you said the first time.")
    win.show(f"Memory — trial {trial} of {N_TRIALS}", "", intro)
    if READ_ALOUD:
        speak(intro.replace("\n", " ").replace("show you", "read you"))
    win.wait(1.5)
    for w in WORDS:
        win.show(f"Memory — trial {trial} of {N_TRIALS}", w)
        start = time.time()
        if READ_ALOUD:
            speak(w.lower())
        win.wait(max(0.1, SECONDS_PER_WORD - (time.time() - start)))
    win.show(f"Memory — trial {trial} of {N_TRIALS}", "",
             "Now say ALL the words you remember, in any order.")
    if READ_ALOUD:
        speak("Now say all the words you remember.")


def run_task5(show_result=True):
    print("=" * 60)
    print("MoCA Task 5: Memory (2 learning trials, not scored)")
    print("=" * 60)
    win = MemoryWindow()
    win.show("Memory", "", "Loading speech recogniser...")
    win.pump()
    engine = get_engine()
    session_dir = get_session_dir()
    trials, evidence = [], []
    for trial in range(1, N_TRIALS + 1):
        present_words(win, trial)
        win.show(f"Memory — trial {trial}: say the words now",
                 "  ".join(WORDS) if SHOW_WORDS_WHILE_ANSWERING else "", "Listening...")
        ans = listen_for_answer(
            engine, PROMPT, pump=win.pump,
            status=lambda t, tr=trial: win.show(f"Memory — trial {tr}: say the words now", "", t),
            max_seconds=30.0, end_silence=3.0, no_speech_timeout=15.0,
            reminder=lambda: win.show("Memory", "", "Please say the words you remember, out loud.",
                                      color="#ffe9c6"))
        final_text = (ans["final"] or {}).get("text") or " ".join(p["text"] for p in ans["phrases"])
        live_text = " ".join(p["text"] for p in ans["phrases"])
        rec_final, intr = recalled_words(final_text)
        rec_live, _ = recalled_words(live_text)
        # a word counts as recalled if either transcription heard it
        recalled = [w for w in WORDS if w in rec_final or w in rec_live]
        wav = session_dir / f"task5_memory_trial{trial}.wav"
        save_wav(wav, ans["audio"])
        evidence.append(wav)
        trials.append({"trial": trial, "recalled": recalled, "n_recalled": len(recalled),
                       "intrusions": intr, "transcript": final_text,
                       "live_transcripts": [p["text"] for p in ans["phrases"]],
                       "end_reason": ans["end_reason"]})
        print(f"[trial {trial}] heard \"{final_text}\" -> recalled {recalled}"
              + (f", other words {intr}" if intr else ""))
        win.show(f"Memory — trial {trial} done", "",
                 f"Recalled {len(recalled)} of 5: {', '.join(recalled) or '(none)'}", color="#eef6ee")
        win.wait(2.0)

    win.show("Memory — finished", "",
             "Please remember these words.\nYou will be asked to recall them later.")
    if READ_ALOUD:
        speak("Please remember these words. You will be asked to recall them later.")
    std = make_task_result(
        TASK_ID, 0,
        reason="learning trials recorded (not scored); " +
               "; ".join(f"trial {t['trial']}: {t['n_recalled']}/5" for t in trials),
        details={"words": WORDS, "trials": trials, "scored": False},
        evidence_files=evidence)
    print(f"Result saved to: {save_task_result(std)}")
    print("SCORE: not scored (memory registration) — words saved for delayed recall")
    if show_result:
        plt.ioff()
        plt.show()
    else:
        plt.pause(3)
        plt.close(win.fig)
    return std


if __name__ == "__main__":
    run_task5()
