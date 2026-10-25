"""
MoCA Tasks 6, 7, 8 — Attention (6 points total)
===============================================

All instructions are read aloud (Mac built-in voice) and shown on screen.

  Task 6  Digit Span      (2 pts)  6a. Numbers forward (1 pt) + 6b. Numbers backward (1 pt)
                                   "2 1 8 5 4" read at 1 digit per second; the patient
                                   repeats them in the same order, then backwards.
  Task 7  Letters / A     (1 pt)   A list of 29 letters is read aloud, with a pause
                                   between letters (LETTER_INTERVAL_S, default 2 s).
                                   Patient RAISES A HAND every time they hear "A".
                                   Webcam watches for the raised hand. 1 point if at
                                   most 1 error; 0 if 2+ errors.
  Task 8  Serial 7s       (3 pts)  "Count backwards from 100 by sevens": the patient says
                                   4 answers (93, 86, 79, 72). Each answer checked against previous
                                   answer minus 7 (MoCA rule). 4 correct = 3, 2-3 = 2, 1 = 1, 0 = 0.

Each task is scored as soon as it ends and shown on screen; answers, transcripts
and recordings are saved to results/<session>/.

Hand-raise detection: before task 7, patient sits still with hands down for 2 s
(camera learns background), then raises a hand once as practice. If camera cannot
see the hand clearly, examiner presses SPACE each time instead.

Run (legacy - runs all three tasks):
    python task6_attention.py

Run (separate tasks):
    python task6_attention.py --task 6  # Digit Span only
    python task6_attention.py --task 7  # Letters only
    python task6_attention.py --task 8  # Serial 7s only
"""

import os
import shutil
import subprocess
import sys
import time

import numpy as np
import cv2

from moca_common import get_session_dir, make_task_result, save_task_result
from moca_speech import digits_of, get_engine, listen_for_answer, numbers_of, save_wav

TASK_IDS = {
    "task6_digit_span": {"label": "Digit Span", "subtasks": ["forward", "backward"]},
    "task7_letters": {"label": "Letters (detect A)", "subtasks": ["letters"]},
    "task8_serial7s": {"label": "Serial 7s Subtraction", "subtasks": ["serial7"]},
}

FORWARD = [2, 1, 8, 5, 4]
BACKWARD = [7, 4, 2]                 # patient must say 2 4 7
LETTERS = "F B A C M N A A J K L B A F A K D E A A A J A M O F A A B".split()
LETTER_INTERVAL_S = 2.0              # time between letters (paper MoCA: 1 s)
SERIAL_START, SERIAL_STEP, SERIAL_ANSWERS = 100, 7, 4
DIGIT_PROMPT = "The person repeats a list of single digits."
NUMBER_PROMPT = "The person says numbers."

from moca_voice import speak_instruction, HAS_MAC_VOICE as HAS_VOICE


def say(text, wait=True, rate=150):
    """Speak an instruction through the shared moca_voice module."""
    return speak_instruction(text, wait=wait, rate=rate)


def say_letter(letter):
    # spell it as a letter ("A" is otherwise sometimes read as the word "a")
    return say(f"[[char LTRL]]{letter}[[char NORM]]", wait=False, rate=140)


class Screen:
    """Simple OpenCV window for instructions and scores."""

    def __init__(self, name="MoCA Task 6 - Attention", size=(1000, 620)):
        self.name, self.size = name, size
        self.show("Attention", ["Getting ready..."])

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
# 6a / 6b  Digit span
# --------------------------------------------------------------------------
def judge_digits(expected, phrases, final):
    """1 if the patient said exactly the expected digits (either transcription)."""
    final_d = digits_of((final or {}).get("text", ""))
    live_d = digits_of(" ".join(p["text"] for p in phrases))
    ok = final_d == expected or live_d == expected
    said = final_d if final_d else live_d
    reason = (f"correct ({' '.join(map(str, expected))})" if ok else
              f"said {' '.join(map(str, said)) or '(nothing)'}, expected {' '.join(map(str, expected))}")
    return (1 if ok else 0), reason, {"said": said, "final_digits": final_d, "live_digits": live_d,
                                      "transcript": (final or {}).get("text", ""),
                                      "live_transcripts": [p["text"] for p in phrases]}


def run_digit_span(screen, engine, digits, answer, title, instruction, wav_path):
    instruct(screen, title, instruction)
    screen.wait(0.5)
    for d in digits:                       # one digit per second
        t = time.time()
        if HAS_VOICE:
            say(str(d), wait=True)
            screen.show(title, ["Listen..."])
        else:
            screen.show(title, ["Listen..."], big=str(d))
        while time.time() - t < 1.0:
            cv2.waitKey(20)
    screen.show(title, ["Now say the numbers.", "Listening..."], color=(235, 245, 255))
    ans = listen_for_answer(
        engine, DIGIT_PROMPT, pump=screen.pump,
        status=lambda t: screen.show(title, ["Listening...", f'Heard: "{t}"'], color=(235, 245, 255)),
        max_seconds=25, end_silence=3.0, no_speech_timeout=10.0,
        is_done=lambda texts: len(digits_of(" ".join(texts))) >= len(answer),
        grace_after_done=1.5)
    save_wav(wav_path, ans["audio"])
    score, reason, details = judge_digits(answer, ans["phrases"], ans["final"])
    return score, reason, details


# --------------------------------------------------------------------------
# 6c  Letters with hand raising -- the one copy lives in task7_letters.py
# --------------------------------------------------------------------------
from task7_letters import (LETTERS, LETTER_INTERVAL_S, HandRaiseDetector,  # noqa: E402
                           run_letters, run_task7, score_letter_responses)


# --------------------------------------------------------------------------
# 6d  Serial 7s
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
# Main: Three separate task entry points
# --------------------------------------------------------------------------
def run_task6(cam_index=0, show_result=True):
    """Task 6: Digit Span (2 points - forward + backward)"""
    print("=" * 60)
    print("MoCA Task 6: Digit Span")
    print("=" * 60)
    screen = Screen()
    screen.show("Digit Span", ["Loading speech recogniser..."])
    engine = get_engine()
    session_dir = get_session_dir()
    criteria, parts = {}, {}

    def report(label, score, max_score, reason):
        print(f"[{label}] {score}/{max_score} — {reason}")
        screen.show(label, [f"Score: {score} / {max_score}", reason[:70]], color=(235, 250, 235))
        screen.wait(2.5)

    # Forward
    s, r, d = run_digit_span(
        screen, engine, FORWARD, FORWARD, "Digit Span - forward",
        "I am going to say some numbers, and when I am through, repeat them to me exactly as I said them.",
        session_dir / "task6_digits_forward.wav")
    criteria["digits_forward"] = s
    parts["digits_forward"] = {"score": s, "reason": r, **d}
    report("Forward", s, 1, r)

    # Backward
    s, r, d = run_digit_span(
        screen, engine, BACKWARD, list(reversed(BACKWARD)), "Digit Span - backward",
        "Now I am going to say some more numbers, but when I am through, you must repeat them "
        "to me in the backwards order.",
        session_dir / "task6_digits_backward.wav")
    criteria["digits_backward"] = s
    parts["digits_backward"] = {"score": s, "reason": r, **d}
    report("Backward", s, 1, r)

    total = sum(criteria.values())
    lines = [f"Numbers forward : {criteria['digits_forward']} / 1",
             f"Numbers backward: {criteria['digits_backward']} / 1",
             f"DIGIT SPAN TOTAL: {total} / 2"]
    print("\n--- RESULT ---")
    for line in lines:
        print(line)
    std = make_task_result("task6_digit_span", total, criteria=criteria,
                           reason="; ".join(f"{k}: {v['reason']}" for k, v in parts.items()),
                           details=parts,
                           evidence_files=[session_dir / "task6_digits_forward.wav",
                                           session_dir / "task6_digits_backward.wav"])
    print(f"Result saved to: {save_task_result(std)}")
    cleanup_console()
    screen.show(f"DIGIT SPAN SCORE: {total} / 2", lines, color=(235, 250, 235))
    screen.wait(6 if not show_result else 1)
    if show_result:
        cleanup_console()
        screen.show(f"DIGIT SPAN SCORE: {total} / 2", lines + ["", "Press any key to close."], color=(235, 250, 235))
        cv2.waitKey(0)
    cv2.destroyAllWindows()
    cv2.waitKey(1)
    return std


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
    cleanup_console()
    screen.show(f"SERIAL 7s SCORE: {s} / 3", lines, color=(235, 250, 235))
    screen.wait(6 if not show_result else 1)
    if show_result:
        cleanup_console()
        screen.show(f"SERIAL 7s SCORE: {s} / 3", lines + ["", "Press any key to close."], color=(235, 250, 235))
        cv2.waitKey(0)
    cv2.destroyAllWindows()
    cv2.waitKey(1)
    return std


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", type=int, choices=[6, 7, 8], default=6,
                    help="which task to run (6=digit span, 7=letters, 8=serial7s)")
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()

    if args.task == 6:
        run_task6(cam_index=args.camera)
    elif args.task == 7:
        run_task7(cam_index=args.camera)
    else:
        run_task8(cam_index=args.camera)
