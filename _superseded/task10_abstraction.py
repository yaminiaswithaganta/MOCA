"""
MoCA Task 10 -- Abstraction (2 points)
======================================

    Train - bicycle   1 point   answer names a means of transport
    Watch - ruler     1 point   answer names a measuring instrument

How it works
-------------
1. Each question is read aloud and the patient answers by voice. The answer
   is transcribed offline (Whisper).
2. The answer is checked for a word from the accepted category list
   (CATEGORY_VOCAB): e.g. "transport", "transportation", "vehicle" for the
   train-bicycle item; "measure", "measuring", "instrument", "tool" for the
   watch-ruler item. Answers that only name a physical feature ("they both
   have wheels", "they are both long") score 0, as in the MoCA rules.
3. The practice item from the MoCA sheet (banana - orange) is not scored.

Run
---
    python task10_abstraction.py
"""

import matplotlib.pyplot as plt

from moca_common import get_session_dir, make_task_result, save_task_result
from moca_speech import find_mentions, get_engine, listen_for_answer, save_wav, speak, words_of

TASK_ID = "task10_abstraction"
ITEMS = [
    {"key": "train_bicycle", "label": "Train - bicycle", "category": "transport",
     "question": "What is the similarity between a train and a bicycle?"},
    {"key": "watch_ruler", "label": "Watch - ruler", "category": "measure",
     "question": "What is the similarity between a watch and a ruler?"},
]

CATEGORY_VOCAB = {
    "transport": {"accept": {"transport", "transports", "transportation", "transportations",
                             "vehicle", "vehicles", "travel", "transit", "conveyance"},
                  "fuzzy": ["transport", "transportation", "vehicle"], "reject": set()},
    "measure": {"accept": {"measure", "measures", "measuring", "measurement", "measurements",
                           "instrument", "instruments", "gauge", "gauges", "tool", "tools"},
                "fuzzy": ["measure", "measuring", "instrument"], "reject": set()},
}
PROMPT = "The person explains how two objects are similar."
ANSWER_SECONDS = 30.0
ANSWER_END_SILENCE = 2.5
NO_SPEECH_TIMEOUT = 15.0


def category_said(text, category):
    """True if an accepted word for `category` appears in the transcript."""
    return any(key == category for key, _, _ in find_mentions(words_of(text), CATEGORY_VOCAB))


def judge_item(item, final_text, live_text):
    """1 if the category was named in the final or the live transcript, else 0."""
    for text in (final_text, live_text):
        if text and category_said(text, item["category"]):
            return 1
    return 0


class AbstractionWindow:
    def __init__(self):
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(8, 6))
        self.ax.axis("off")

    def show(self, title, big="", small="", color="white"):
        self.ax.clear()
        self.ax.axis("off")
        self.ax.set_title(title, fontsize=15)
        self.ax.text(0.5, 0.55, big, ha="center", va="center", fontsize=26, weight="bold",
                     transform=self.ax.transAxes, wrap=True)
        self.ax.text(0.5, 0.15, small, ha="center", va="center", fontsize=14,
                     transform=self.ax.transAxes, wrap=True)
        self.fig.patch.set_facecolor(color)
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()

    def pump(self):
        plt.pause(0.03)

    def wait(self, seconds):
        import time
        t = time.time() + seconds
        while time.time() < t:
            self.pump()


def run_task10(show_result=True):
    print("=" * 60)
    print("MoCA Task 10: Abstraction (2 items)")
    print("=" * 60)
    win = AbstractionWindow()
    win.show("Abstraction", "", "Loading speech recogniser...")
    win.pump()
    engine = get_engine()
    session_dir = get_session_dir()

    criteria, details, evidence = {}, {}, []
    for i, item in enumerate(ITEMS, 1):
        title = f"Abstraction - item {i} of {len(ITEMS)}: {item['label']}"
        win.show(title, "", item["question"])
        speak(item["question"])
        win.show(title, "", "Listening...", color="#eef6ee")
        ans = listen_for_answer(
            engine, PROMPT, pump=win.pump,
            status=lambda t, ti=title: win.show(ti, "", t),
            max_seconds=ANSWER_SECONDS, end_silence=ANSWER_END_SILENCE,
            no_speech_timeout=NO_SPEECH_TIMEOUT,
            reminder=lambda ti=title: win.show(ti, "", "Please answer out loud.", color="#ffe9c6"))
        final_text = (ans["final"] or {}).get("text", "")
        live_text = " ".join(p["text"] for p in ans["phrases"])
        score = judge_item(item, final_text, live_text)
        wav = session_dir / f"task10_abstraction_{item['key']}.wav"
        save_wav(wav, ans["audio"])
        evidence.append(wav)
        criteria[item["key"]] = score
        details[item["key"]] = {"question": item["question"], "heard": final_text or live_text,
                                "accepted_category": item["category"], "score": score,
                                "end_reason": ans["end_reason"]}
        print(f"[{item['label']}] {score}/1  heard \"{final_text or live_text}\"")
        win.show(title, "", f"Recorded: \"{final_text or live_text or '(nothing)'}\"",
                 color="lightgray")
        win.wait(2.0)

    score = sum(criteria.values())
    reason = "; ".join(f"{it['label']}: {criteria[it['key']]}/1" for it in ITEMS)
    win.show("Abstraction - finished", "", f"ABSTRACTION SCORE: {score} / 2", color="#eef6ee")
    std = make_task_result(TASK_ID, score, criteria=criteria, reason=reason, details=details,
                           evidence_files=evidence)
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
    run_task10()
