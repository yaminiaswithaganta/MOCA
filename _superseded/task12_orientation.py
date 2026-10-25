"""
MoCA Task 12 -- Orientation (6 points)
======================================

    Date        1 point   day of the month, checked against the computer clock
    Month       1 point   month name, checked against the computer clock
    Year        1 point   year, checked against the computer clock
    Day         1 point   day of the week, checked against the computer clock
    Place       1 point   any place named (accepts any non-empty answer)
    City        1 point   any city named (accepts any non-empty answer)

How it works
-------------
1. Each question is read aloud and the patient answers by voice. The answer
   is transcribed offline (Whisper).
2. Date, month, year and day of the week are compared with the date on the
   computer running the test (today's date, local time). The spoken form is
   accepted in digits or words: "8", "eighth", "the eighth", "October eighth",
   "two thousand and twenty six", "twenty twenty six", "Thursday".
3. Place and city: any answer with a real word in it scores 1. "I don't
   know" and similar answers score 0.

Run
---
    python task12_orientation.py
"""

import datetime
import re
import time

import matplotlib.pyplot as plt

from moca_common import get_session_dir, make_task_result, save_task_result
from moca_speech import get_engine, listen_for_answer, save_wav, speak, words_of

TASK_ID = "task12_orientation"
PROMPT = "The person answers a question about today's date or where they are."
ANSWER_SECONDS = 20.0
NO_SPEECH_TIMEOUT = 12.0

_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen"]
_ORD_ONES = ["", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
             "ninth", "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth",
             "sixteenth", "seventeenth", "eighteenth", "nineteenth"]
_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy",
         8: "eighty", 9: "ninety"}
_TENS_ORD = {2: "twentieth", 3: "thirtieth"}
MONTHS = {
    1: {"january", "jan"}, 2: {"february", "feb"}, 3: {"march", "mar"}, 4: {"april", "apr"},
    5: {"may"}, 6: {"june", "jun"}, 7: {"july", "jul"}, 8: {"august", "aug"},
    9: {"september", "sep", "sept"}, 10: {"october", "oct"}, 11: {"november", "nov"},
    12: {"december", "dec"},
}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
# words that do not name a place or city ("I don't know", "I think it is in the...")
NON_ANSWER_WORDS = {"i", "i'm", "im", "it", "is", "its", "it's", "the", "a", "an", "we", "we're",
                    "are", "in", "at", "on", "of", "am", "be", "dont", "don't", "do", "not", "no",
                    "know", "idea", "sure", "um", "uh", "think", "well", "that", "this", "here",
                    "yes", "okay", "ok", "maybe", "guess", "i'd", "is"}


def cardinal(n):
    """1..99 -> spoken words ('twenty six')."""
    if n < 20:
        return _ONES[n]
    tens, unit = divmod(n, 10)
    return _TENS[tens] + (" " + _ONES[unit] if unit else "")


def ordinal(n):
    """1..31 -> spoken ordinal words ('eighth', 'twenty first')."""
    if n < 20:
        return _ORD_ONES[n]
    tens, unit = divmod(n, 10)
    if unit == 0:
        return _TENS_ORD[tens]
    return _TENS[tens] + " " + _ORD_ONES[unit]


def _spoken(text):
    """Normalised text: lower-case words joined by single spaces, padded for phrase search."""
    return " " + " ".join(words_of(text)) + " "


def _has_phrase(text, phrases):
    s = _spoken(text)
    return any(f" {p} " in s for p in phrases)


def day_said(text, day):
    digits = set(re.findall(r"\d+", text))
    phrases = {cardinal(day), ordinal(day), "the " + ordinal(day)}
    return str(day) in digits or _has_phrase(text, phrases)


def year_said(text, year):
    digits = set(re.findall(r"\d+", text))
    if str(year) in digits:
        return True
    hi, lo = divmod(year, 100)
    phrases = {cardinal(hi) + " " + cardinal(lo)}
    if hi == 20 and lo:
        phrases |= {"two thousand " + cardinal(lo), "two thousand and " + cardinal(lo)}
    return _has_phrase(text, phrases)


def month_said(text, month):
    return bool(set(words_of(text)) & MONTHS[month])


def weekday_said(text, weekday_index):
    return bool(set(words_of(text)) & {WEEKDAYS[weekday_index]})


def place_said(text):
    return any(w not in NON_ANSWER_WORDS for w in words_of(text))


def build_items(now):
    """The six questions and how each answer is judged, using the clock time `now`."""
    return [
        {"key": "date", "question": "What is today's date?",
         "judge": lambda t: day_said(t, now.day), "expected": f"{now.day}"},
        {"key": "month", "question": "What month is it?",
         "judge": lambda t: month_said(t, now.month), "expected": now.strftime("%B")},
        {"key": "year", "question": "What year is it?",
         "judge": lambda t: year_said(t, now.year), "expected": str(now.year)},
        {"key": "day", "question": "What day of the week is it?",
         "judge": lambda t: weekday_said(t, now.weekday()), "expected": now.strftime("%A")},
        {"key": "place", "question": "Where are we right now?",
         "judge": place_said, "expected": "any place"},
        {"key": "city", "question": "What city are we in?",
         "judge": place_said, "expected": "any city"},
    ]


class OrientationWindow:
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
        t = time.time() + seconds
        while time.time() < t:
            self.pump()


def run_task12(show_result=True):
    print("=" * 60)
    print("MoCA Task 12: Orientation (6 questions)")
    print("=" * 60)
    win = OrientationWindow()
    win.show("Orientation", "", "Loading speech recogniser...")
    win.pump()
    engine = get_engine()
    session_dir = get_session_dir()
    now = datetime.datetime.now()
    items = build_items(now)

    criteria, details, evidence = {}, {}, []
    for i, item in enumerate(items, 1):
        title = f"Orientation - question {i} of {len(items)}"
        win.show(title, "", item["question"])
        speak(item["question"])
        win.show(title, "", "Listening...", color="#eef6ee")
        ans = listen_for_answer(
            engine, PROMPT, pump=win.pump,
            status=lambda t, ti=title: win.show(ti, "", t),
            max_seconds=ANSWER_SECONDS, end_silence=2.0, no_speech_timeout=NO_SPEECH_TIMEOUT,
            reminder=lambda ti=title: win.show(ti, "", "Please answer out loud.",
                                               color="#ffe9c6"))
        final_text = (ans["final"] or {}).get("text", "")
        live_text = " ".join(p["text"] for p in ans["phrases"])
        heard = final_text or live_text
        ok = int(bool(item["judge"](final_text) or item["judge"](live_text)))
        wav = session_dir / f"task12_orientation_{item['key']}.wav"
        save_wav(wav, ans["audio"])
        evidence.append(wav)
        criteria[item["key"]] = ok
        details[item["key"]] = {"question": item["question"], "heard": heard,
                                "expected": item["expected"], "score": ok,
                                "end_reason": ans["end_reason"]}
        print(f"[{item['key']}] {ok}/1  expected {item['expected']!r}  heard \"{heard}\"")
        win.show(title, "", f"Recorded: \"{heard or '(nothing)'}\"", color="lightgray")
        win.wait(1.5)

    score = sum(criteria.values())
    missed = [k for k, v in criteria.items() if not v]
    reason = f"{score} of 6 correct" + (f" (missed: {', '.join(missed)})" if missed else "")
    win.show("Orientation - finished", "", f"ORIENTATION SCORE: {score} / 6", color="#eef6ee")
    std = make_task_result(TASK_ID, score, criteria=criteria, reason=reason,
                           details={"clock": now.isoformat(timespec="seconds"),
                                    "items": details},
                           evidence_files=evidence)
    print(f"\n--- RESULT ---\n{reason}\nSCORE: {score} / 6")
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
