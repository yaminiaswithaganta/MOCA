"""
MoCA Task 8 — Count Backwards by 7s (3 points)
================================================

All instructions are read aloud (Mac built-in voice) and shown on screen.

  Task 8  Serial 7s       (3 pts)  "Count backwards from 100 by sevens": the patient says
                                   4 answers (93, 86, 79, 72). Each answer checked against
                                   previous answer minus 7 (MoCA rule). 4 correct = 3,
                                   2-3 = 2, 1 = 1, 0 = 0.

The task is scored as soon as it ends and shown on screen; answers, transcripts
and recordings are saved to results/<session>/.

Usage:
    python task8_serial7s.py
"""

import os
import shutil
import subprocess
import sys
import time

import numpy as np
import cv2

from moca_common import get_session_dir, make_task_result, save_task_result
from moca_speech import get_engine, listen_for_answer, numbers_of, save_wav

SERIAL_START, SERIAL_STEP, SERIAL_ANSWERS = 100, 7, 4
NUMBER_PROMPT = "The person says numbers."

from moca_voice import speak_instruction, HAS_MAC_VOICE as HAS_VOICE


def say(text, wait=True, rate=150):
    """Speak an instruction through the shared moca_voice module."""
    return speak_instruction(text, wait=wait, rate=rate)


class Screen:
    """Simple OpenCV window for instructions and scores."""

    def __init__(self, name="MoCA Task 8 - Serial 7s", size=(1000, 620)):
        self.name, self.size = name, size
        self.show("Serial 7s", ["Getting ready..."])

    def show(self, title, lines=(), big="", color=(255, 255, 255), wait_ms=1):
        w, h = self.size
        img = np.full((h, w, 3), color, np.uint8)
        cv2.putText(img, title, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (40, 40, 40), 3)
        y = 120
        for line in lines:
            cv2.putText(img, line, (30, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), 2)
            y += 42
        if big:
            (tw, th), _ = cv2.getTextSize(big, cv2.FONT_HERSHEY_SIMPLEX, 4, 8)
            cv2.putText(img, big, ((w - tw) // 2, min(h - 40, y + 140)),
                        cv2.FONT_HERSHEY_SIMPLEX, 4, (20, 20, 120), 8)
        cv2.imshow(self.name, img)
        cv2.waitKey(wait_ms)

    def pump(self):
        cv2.waitKey(1)

    def wait(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            cv2.waitKey(20)


def instruct(screen, title, text, wrap=70):
    """Show the instruction on screen and read it aloud."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > wrap:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    screen.show(title, lines)
    if HAS_VOICE:
        say(text)
    else:
        screen.wait(min(8, 1 + len(words) * 0.3))
    print(f"[instruction] {text}")


def cleanup_console():
    """Clear stdout/stderr buffers to prevent display artifacts."""
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        os.system("clear" if sys.platform != "win32" else "cls")
    except Exception:
        pass


# --------------------------------------------------------------------------
# Serial 7s
# --------------------------------------------------------------------------
def serial7_answers(text):
    """Numbers the patient gave, without the starting 100 or the word 'seven'."""
    nums = numbers_of(text)
    out = []
    for k, n in enumerate(nums):
        if n == SERIAL_START and not out:
            continue                      # "100 minus 7 is 93"
        if n == SERIAL_STEP:
            continue                      # "... minus 7 ..."
        out.append(n)
    return out[:SERIAL_ANSWERS]


def score_serial7(answers, start=SERIAL_START, step=SERIAL_STEP):
    """MoCA: each subtraction checked against the previous ANSWER. 4 correct -> 3, 2-3 -> 2, 1 -> 1."""
    prev, correct, per = start, 0, []
    for a in answers[:SERIAL_ANSWERS]:
        ok = a == prev - step
        correct += ok
        per.append({"answer": a, "expected": prev - step, "correct": ok})
        prev = a
    points = 3 if correct == 4 else 2 if correct >= 2 else 1 if correct == 1 else 0
    return points, correct, per


def run_serial7(screen, engine, wav_path):
    title = "Attention - subtract 7"
    instruct(screen, title,
             "Now I will ask you to count by subtracting seven from one hundred, and then keep "
             "subtracting seven from your answer. Please begin now.")
    screen.show(title, ["Start at 100 and keep subtracting 7.", "Listening..."],
                        color=(235, 245, 255))

    def show_heard(t):
        nums = serial7_answers(t)
        screen.show(title, ["Start at 100 and keep subtracting 7.", "Listening...",
                            "Answers so far: " + ", ".join(map(str, nums))], color=(235, 245, 255))

    texts_seen = []

    def status(t):
        texts_seen.append(t)
        show_heard(" ".join(texts_seen))

    ans = listen_for_answer(
        engine, NUMBER_PROMPT, pump=screen.pump, status=lambda t: status(t.replace('Heard: ', '').strip('"')),
        max_seconds=90, end_silence=8.0, no_speech_timeout=15.0,
        is_done=lambda texts: len(serial7_answers(" ".join(texts))) >= SERIAL_ANSWERS,
        grace_after_done=1.5)
    say("Thank you. You can stop.", wait=False)
    save_wav(wav_path, ans["audio"])
    final_ans = serial7_answers((ans["final"] or {}).get("text", ""))
    live_ans = serial7_answers(" ".join(p["text"] for p in ans["phrases"]))
    answers = final_ans if len(final_ans) >= len(live_ans) else live_ans
    points, correct, per = score_serial7(answers)
    reason = (f"{correct} of 4 correct subtractions ({', '.join(map(str, answers)) or 'no answers'}) "
              f"-> {points} point(s)")
    return points, reason, {"answers": answers, "correct_subtractions": correct, "per_step": per,
                            "transcript": (ans["final"] or {}).get("text", ""),
                            "live_transcripts": [p["text"] for p in ans["phrases"]]}


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def run_task8(cam_index=0, show_result=True):
    """Task 8: Serial 7s Subtraction (3 points)"""
    print("=" * 60)
    print("MoCA Task 8: Serial 7s")
    print("=" * 60)
    screen = Screen()
    screen.show("Serial 7s", ["Loading speech recogniser..."])
    engine = get_engine()
    session_dir = get_session_dir()

    # Serial 7s
    s, r, d = run_serial7(screen, engine, session_dir / "task8_serial7.wav")
    criteria = {"serial7": s}
    parts = {"serial7": {"score": s, "reason": r, **d}}

    lines = [f"Subtracting 7   : {s} / 3"]
    print("\n--- RESULT ---")
    print(f"[Serial 7s] {s}/3 — {r}")
    for line in lines:
        print(line)
    std = make_task_result("task8_serial7s", s, criteria=criteria,
                           reason=r, details=parts,
                           evidence_files=[session_dir / "task8_serial7.wav"])
    print(f"Result saved to: {save_task_result(std)}")
    screen.show(f"SERIAL 7s SCORE: {s} / 3", lines, color=(235, 250, 235))
    screen.wait(6 if not show_result else 1)
    if show_result:
        screen.show(f"SERIAL 7s SCORE: {s} / 3", lines + ["", "Press any key to close."], color=(235, 250, 235))
        cv2.waitKey(0)
    cv2.destroyAllWindows()
    cv2.waitKey(1)
    return std


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args = ap.parse_args()
    run_task8()
