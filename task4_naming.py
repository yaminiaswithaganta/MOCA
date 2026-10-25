"""
MoCA Task 4 — Naming (3 points: lion, rhinoceros, camel)
=========================================================

How it works
-------------
1. The three animal pictures from the MoCA sheet are shown one at a time
   (images/lion.png, images/rhino.png, images/camel.png -- replace them with
   your own pictures any time, same file names).
2. For each picture the patient says what animal it is. The microphone
   records continuously; the answer ends after a natural pause, or ~1.5 s
   after an animal name was heard (so "a tiger... no, a lion" can still be
   corrected). If nothing is said for 12 s the picture is skipped (0).
3. The answer is transcribed OFFLINE by Whisper (same engine as Task 1) and
   checked against the accepted names:
       lion                          -> Lion
       rhinoceros / rhino            -> Rhinoceros
       camel / dromedary             -> Camel
   Accent / pronunciation variants are handled by Whisper itself plus an
   alias list and "one letter off" matching ("rino", "cammel", "lie on").
   Words that merely sound similar but mean something else ("line",
   "cameo", "camera") are NOT accepted.
4. Scoring, per picture (0 or 1, total 0-3):
       1 = the LAST animal the patient named is the correct one, and it was
           heard reliably (heard in both the live and the final transcription,
           or with good confidence);
       0 = wrong animal, no answer, or not reliably recognised.

Run
---
    python task4_naming.py
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from moca_common import get_session_dir, make_task_result, save_task_result
from moca_speech import (find_mentions, get_engine, listen_for_answer, save_wav, words_of,
                         word_prob)

TASK_ID = "task4_naming"
IMAGE_DIR = Path(__file__).resolve().parent / "images"

from moca_voice import speak_instruction, HAS_MAC_VOICE as HAS_VOICE


def say(text, wait=True, rate=150):
    """Speak an instruction through the shared moca_voice module."""
    return speak_instruction(text, wait=wait, rate=rate)


# Order and accepted answers (official MoCA: lion; rhinoceros or rhino; camel or dromedary)
ANIMALS = [
    {"key": "lion", "label": "Lion", "image": "lion.png"},
    {"key": "rhino", "label": "Rhinoceros", "image": "rhino.png"},
    {"key": "camel", "label": "Camel", "image": "camel.png"},
]

ANIMAL_VOCAB = {
    "lion": {"accept": {"lion", "lions", "lyon", "lionn", "liyon", "lieon"},
             "fuzzy": ["lion"],
             "reject": {"line", "lien", "lino", "loan", "lian", "lieu", "linen", "onion"}},
    "rhino": {"accept": {"rhino", "rhinos", "rhinoceros", "rhinoceroses", "rhinocerous",
                         "rhinocerus", "rhinoceras", "rhinosaurus", "rhinoserus", "rino",
                         "ryno", "rhyno", "reno", "rhinoc", "rhinocerose"},
              "fuzzy": ["rhino", "rhinoceros", "rhinocerous"], "max_edit": 2,
              "reject": {"rhine", "rhinal", "rhymo", "casino"}},
    "camel": {"accept": {"camel", "camels", "cammel", "kamel", "kammel", "camal", "camell",
                         "cahmel", "camille", "camil", "camile", "kamal", "kamil", "camu", "camul",
                         "cammal", "kemal", "dromedary", "dromedaries", "dromedery", "dromadary"},
              "fuzzy": ["camel", "dromedary"], "max_edit": 2,
              "reject": {"cameo", "camera", "camp", "canal", "cancel", "carmel", "caramel",
                         "campbell", "came", "calm", "comet", "hamel"}},
}

# Other animals people commonly (wrongly) name -- recognised so that e.g.
# "tiger" is recorded as a wrong answer, and "tiger, no, lion" as a correction.
OTHER_ANIMALS = {
    "tiger", "cat", "leopard", "cheetah", "panther", "puma", "cougar", "jaguar", "lynx",
    "dog", "wolf", "fox", "hyena", "horse", "pony", "donkey", "mule", "zebra", "cow",
    "bull", "ox", "buffalo", "bison", "yak", "hippo", "hippopotamus", "elephant", "pig",
    "boar", "hog", "tapir", "llama", "alpaca", "giraffe", "deer", "goat", "sheep",
    "antelope", "kangaroo", "bear", "dinosaur", "triceratops", "unicorn", "moose",
}
OTHER_VOCAB = {"other:" + a: {"accept": {a, a + "s"}, "fuzzy": []} for a in OTHER_ANIMALS}
ALL_VOCAB = {**ANIMAL_VOCAB, **OTHER_VOCAB}

PROMPT = "The person looks at a picture and says the name of the animal."
MIN_WORD_PROB = 0.25
MIN_AGREED_WORD_PROB = 0.02
ANSWER_TIMEOUT_S = 12.0        # no speech at all -> no answer
MAX_ANSWER_S = 25.0


# --------------------------------------------------------------------------
# Scoring one answer (pure function -- unit tested)
# --------------------------------------------------------------------------
def mentions_in(result):
    """Animal names in a transcription result, in order: [(key, word_index, heard)]."""
    if not result or not result.get("text"):
        return []
    return find_mentions(words_of(result["text"]), ALL_VOCAB)


def judge_answer(target, phrases, final):
    """
    target: "lion" | "rhino" | "camel"
    phrases: live phrase results [{"text","words"}]; final: whole-answer result.
    Returns (score 0/1, reason, details).
    """
    final_mentions = mentions_in(final)
    live_mentions = [m for p in phrases for m in mentions_in(p)]
    details = {"final_transcript": (final or {}).get("text", ""),
               "live_transcripts": [p["text"] for p in phrases],
               "final_mentions": [m[0] for m in final_mentions],
               "live_mentions": [m[0] for m in live_mentions]}
    source = final_mentions or live_mentions
    if not source:
        heard = details["final_transcript"] or " ".join(details["live_transcripts"])
        return 0, (f"no animal name recognised (heard \"{heard}\")" if heard
                   else "no answer"), details
    answer_key, idx, heard = source[-1]          # last named animal = final answer
    details["answer"] = answer_key
    details["heard_as"] = heard
    if answer_key != target:
        name = answer_key.replace("other:", "")
        return 0, f"named '{name}' instead of the correct animal", details
    # confidence: heard in both passes, or a confident word in the pass used
    agreed = bool(live_mentions) and bool(final_mentions) and \
        live_mentions[-1][0] == final_mentions[-1][0] == target
    res = final if final_mentions else phrases[-1]
    prob = word_prob(res, idx) if final_mentions else 1.0
    if not final_mentions:
        for p in phrases:
            ms = mentions_in(p)
            if ms and ms[-1][0] == target:
                prob = word_prob(p, ms[-1][1])
    details["confidence"] = round(prob, 3)
    details["live_and_final_agree"] = agreed
    if prob < (MIN_AGREED_WORD_PROB if agreed else MIN_WORD_PROB):
        return 0, f"'{heard}' was not recognised reliably (confidence {prob:.2f})", details
    return 1, f"correct ('{heard}')", details


# --------------------------------------------------------------------------
# Display
# --------------------------------------------------------------------------
class NamingWindow:
    def __init__(self):
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(8, 7))
        self.ax.axis("off")
        self.status = self.fig.text(0.5, 0.04, "", ha="center", fontsize=13,
                                    bbox=dict(boxstyle="round", fc="lightyellow", ec="gray"))
        self._img = None

    def show_picture(self, path, title):
        self.ax.clear()
        self.ax.axis("off")
        img = plt.imread(str(path))
        self.ax.imshow(img, cmap="gray" if img.ndim == 2 else None)
        self.ax.set_title(title, fontsize=15)
        self.fig.patch.set_facecolor("white")
        self.refresh()

    def set_status(self, text, color="lightyellow"):
        self.status.set_text(text)
        self.status.set_bbox(dict(boxstyle="round", fc=color, ec="gray"))
        self.refresh()

    def show_summary(self, lines, score):
        self.ax.clear()
        self.ax.axis("off")
        self.ax.set_title(f"NAMING SCORE: {score} / 3", fontsize=20, weight="bold",
                          color="darkgreen" if score == 3 else "darkred")
        for i, line in enumerate(lines):
            self.ax.text(0.5, 0.75 - 0.15 * i, line, ha="center", fontsize=15,
                         transform=self.ax.transAxes)
        self.status.set_text("")
        self.refresh()

    def refresh(self):
        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()

    def pump(self):
        plt.pause(0.03)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def run_task4(show_result=True):
    print("=" * 60)
    print("MoCA Task 4: Naming")
    print("=" * 60)

    # Voice instruction
    say("I will show you three pictures of animals, one at a time. For each picture, "
        "look carefully and say the name of the animal out loud as clearly as you can.")

    missing = [a["image"] for a in ANIMALS if not (IMAGE_DIR / a["image"]).exists()]
    if missing:
        raise FileNotFoundError(f"Missing pictures in {IMAGE_DIR}: {missing}")

    win = NamingWindow()
    win.set_status("Loading speech recogniser...")
    win.pump()
    engine = get_engine()
    session_dir = get_session_dir()

    criteria, per_animal, evidence = {}, {}, []
    for i, animal in enumerate(ANIMALS, 1):
        win.show_picture(IMAGE_DIR / animal["image"],
                         f"Picture {i} of 3 — What is this animal? Say its name out loud.")
        win.set_status("Listening...")
        target = animal["key"]

        def is_done(texts):
            return any(find_mentions(words_of(t), ALL_VOCAB) for t in texts)

        ans = listen_for_answer(
            engine, PROMPT, pump=win.pump, status=lambda t: win.set_status(t),
            max_seconds=MAX_ANSWER_S, no_speech_timeout=ANSWER_TIMEOUT_S, is_done=is_done,
            reminder=lambda: win.set_status("Please say the name of the animal out loud.",
                                            color="orange"))
        score, reason, details = judge_answer(target, ans["phrases"], ans["final"])
        details["end_reason"] = ans["end_reason"]
        wav = session_dir / f"task4_naming_{target}.wav"
        save_wav(wav, ans["audio"])
        evidence.append(wav)
        criteria[target] = score
        per_animal[target] = {"score": score, "reason": reason, **details}
        print(f"[{animal['label']}] {'1' if score else '0'}/1 — {reason}")
        heard = details.get("heard_as") or details.get("final_transcript") or "(nothing)"
        win.set_status(f"Answer recorded: \"{heard}\"", color="lightgray")
        t_end = time.time() + 1.5
        while time.time() < t_end:
            win.pump()

    total = sum(criteria.values())
    lines = [f"{a['label']}: {criteria[a['key']]} / 1   ({per_animal[a['key']]['reason']})"
             for a in ANIMALS]
    win.show_summary(lines, total)
    print("\n--- RESULT ---")
    for line in lines:
        print(line)
    print(f"SCORE: {total} / 3")

    std = make_task_result(TASK_ID, total, criteria=criteria,
                           reason="; ".join(f"{k}: {v['reason']}" for k, v in per_animal.items()),
                           details=per_animal, evidence_files=evidence)
    print(f"Result saved to: {save_task_result(std)}")
    if show_result:
        plt.ioff()
        plt.show()
    else:
        plt.pause(4)
        plt.close(win.fig)
    return std


if __name__ == "__main__":
    run_task4()
