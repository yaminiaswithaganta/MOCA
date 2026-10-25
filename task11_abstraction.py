"""
MoCA Task 11 -- Abstraction (2 points)
======================================

    Train - bicycle   1 point   answer names a means of transport
    Watch - ruler     1 point   answer names a measuring instrument

How it works
-------------
1. Each question is read aloud and the patient answers by voice. The answer
   is transcribed offline (Whisper).
2. The answer is checked for a word from the accepted category list
   (CATEGORY_VOCAB, built from TRANSPORT_WORDS and MEASURE_WORDS): e.g.
   "transport", "vehicle", "wheels", "travel" for the train-bicycle item;
   "measure", "instrument", "scale", "accuracy" for the watch-ruler item.
3. The practice item from the MoCA sheet (banana - orange) is not scored.

Run
---
    python task11_abstraction.py
"""

import re

import matplotlib.pyplot as plt

from moca_common import get_session_dir, make_task_result, save_task_result
from moca_speech import find_mentions, get_engine, listen_for_answer, save_wav, speak, words_of

TASK_ID = "task11_abstraction"
ITEMS = [
    {"key": "train_bicycle", "label": "Train - bicycle", "category": "transport",
     "question": "What is the similarity between a train and a bicycle?"},
    {"key": "watch_ruler", "label": "Watch - ruler", "category": "measure",
     "question": "What is the similarity between a watch and a ruler?"},
]

# Words that count for each item. The lists are the accepted answer words for
# "train - bicycle" (means of transport) and "watch - ruler" (measuring).
TRANSPORT_WORDS = [
    "Transport", "Transportation", "Vehicle", "Movement", "Travel", "Wheels", "Journey",
    "Speed", "Motion", "Machine", "Mechanical", "Riding", "Commuting", "Passenger", "Distance",
    "Route", "Direction", "Destination", "Travel time", "Engine", "Pedal", "Tracks", "Railway",
    "Road", "Cycling", "Locomotion", "Energy", "Power", "Metal", "Frame", "Balance", "Steering",
    "Brakes", "Safety", "Outdoor", "Adventure", "Recreation", "Public transport", "Human-powered",
    "Motorized", "Efficiency", "Mobility", "Transport system", "Infrastructure", "Wheels rotating",
    "Exercise", "Environment", "Fuel", "Speed control", "Commuter", "Transit", "Conveyance",
]
MEASURE_WORDS = [
    "Measure", "Measuring", "Measurement", "Measuring instrument", "Instrument", "Precision",
    "Accuracy", "Numbers", "Scale", "Markings", "Units", "Reading", "Reference", "Length", "Time",
    "Quantification", "Graduation marks", "Measurement tool", "Standard", "Calibration",
    "Comparison", "Value", "Units of measurement", "Intervals", "Divisions", "Small increments",
    "Scale reading", "Numerical values", "Measurement system", "Metric", "Inches", "Centimeters",
    "Seconds", "Minutes", "Hours", "Lines", "Display", "Utility", "Practical tool", "Daily use",
    "Portable", "Handheld", "Design", "Accuracy checking", "Estimation", "Precision tool",
    "Reference point", "Measurement scale", "Recording", "Mathematics", "Geometry", "Timekeeping",
    "Length measurement", "Graduated markings", "Gauge", "Tool",
]


def _vocab_forms(phrases):
    """Every way a listed phrase can be heard: the word itself, its plural, and the joined
    form for two-word phrases ("public transport" -> "publictransport", which the matcher
    uses when the recogniser splits a phrase)."""
    forms = set()
    for phrase in phrases:
        words = re.findall(r"[a-z]+", phrase.lower())
        if not words:
            continue
        forms.add("".join(words))                 # "human-powered" -> "humanpowered"
        if len(words) == 1:
            w = words[0]
            forms.update({w, w + "s", w + "es"})
            if w.endswith("s"):
                forms.add(w[:-1])
        elif len(words) == 2:
            forms.update(words)                   # keep both words as single hits too
    return forms


CATEGORY_VOCAB = {
    "transport": {"accept": _vocab_forms(TRANSPORT_WORDS),
                  "fuzzy": ["transport", "transportation", "vehicle"], "reject": set()},
    "measure": {"accept": _vocab_forms(MEASURE_WORDS),
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


def run_task11(show_result=True):
    print("=" * 60)
    print("MoCA Task 11: Abstraction (2 items)")
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
        wav = session_dir / f"task11_abstraction_{item['key']}.wav"
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
    run_task11()
