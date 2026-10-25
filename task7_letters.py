"""
MoCA Task 7 — Detect the Letter A (1 point)
==============================================

All instructions are read aloud (Mac built-in voice) and shown on screen.

  Task 7  Letters / A     (1 pt)   A list of 29 letters is read aloud, with a pause
                                   between letters (LETTER_INTERVAL_S, default 2 s).
                                   Patient RAISES A HAND every time they hear "A".
                                   Webcam watches for the raised hand. 1 point if at
                                   most 1 error; 0 if 2+ errors.

The task is scored as soon as it ends and shown on screen; answers, transcripts
and recordings are saved to results/<session>/.

Hand-raise detection: before the task, patient sits still with hands down for 2 s
(camera learns background), then raises a hand once as practice. If camera cannot
see the hand clearly, examiner presses SPACE each time instead.

Usage:
    python task7_letters.py               # run task 7
    python task7_letters.py --camera 1    # use a different webcam
"""

import os
import shutil
import subprocess
import sys
import time

import numpy as np
import cv2

from moca_common import get_session_dir, make_task_result, save_task_result

LETTERS = "F B A C M N A A J K L B A F A K D E A A A J A M O F A A B".split()
LETTER_INTERVAL_S = 2.0              # time between letters (paper MoCA: 1 s)

from moca_voice import speak_instruction, HAS_MAC_VOICE as HAS_VOICE


def say(text, wait=True, rate=150):
    """Speak an instruction through the shared moca_voice module."""
    return speak_instruction(text, wait=wait, rate=rate)


def say_letter(letter):
    # spell it as a letter ("A" is otherwise sometimes read as the word "a")
    return say(f"[[char LTRL]]{letter}[[char NORM]]", wait=False, rate=140)


class Screen:
    """Simple OpenCV window for instructions and scores."""

    def __init__(self, name="MoCA Task 7 - Letters", size=(1000, 620)):
        self.name, self.size = name, size
        self.show("Letters", ["Getting ready..."])

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
# Hand-raise detection
# --------------------------------------------------------------------------
class CameraAborted(Exception):
    """Raised when the examiner presses Esc during camera set-up."""


def _check_abort(key):
    if key == 27:                       # Esc
        raise CameraAborted()


class HandRaiseDetector:
    """
    Detects a raised hand with the webcam by comparing each frame with a
    'hands down' picture of the patient, in the areas beside / above the head
    (where a raised hand appears). Thresholds come from a practice raise.

    Camera safety: a missing frame never freezes the window, the camera is
    re-opened when it stops delivering frames, and Esc switches the task to
    examiner mode (press SPACE for each raise).
    """

    MAX_FAILED_FRAMES = 90          # about 3 s without a frame -> stop using the camera

    def __init__(self, cam_index=0, width=320):
        self.cam_index = cam_index
        self.cap = cv2.VideoCapture(cam_index)
        self.width = width
        self.base = None
        self.zone = None
        self.thr_up = self.thr_down = None
        self.up = False
        self._streak = 0
        self.face = None
        self.fails = 0
        self.reopens = 0
        self.last_bgr = None
        self.base_skin = None
        self.mode = "changed"           # "changed" (brightness) or "skin" (hand-coloured pixels)

    def ok(self):
        return self.cap is not None and self.cap.isOpened() and self.fails < self.MAX_FAILED_FRAMES

    def _reopen(self):
        self.release()
        self.cap = cv2.VideoCapture(self.cam_index)
        self.reopens += 1

    def read(self):
        if self.cap is None or not self.cap.isOpened():
            return None, None
        ok, frame = self.cap.read()
        if not ok or frame is None:
            self.fails += 1
            if self.fails in (15, 45) and self.reopens < 2:
                self._reopen()          # the camera may be busy: try again
            return None, None
        self.fails = 0
        frame = cv2.flip(frame, 1)                  # mirror view, feels natural
        h = int(frame.shape[0] * self.width / frame.shape[1])
        small = cv2.GaussianBlur(cv2.resize(frame, (self.width, h)), (5, 5), 0)
        self.last_bgr = small
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return frame, gray.astype(np.float32)

    def _make_zone(self, gray):
        h, w = gray.shape
        zone = np.zeros((h, w), bool)
        face = None
        try:
            casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            faces = casc.detectMultiScale(gray.astype(np.uint8), 1.1, 5, minSize=(w // 10, w // 10))
            if len(faces):
                face = max(faces, key=lambda f: f[2] * f[3])
        except Exception:
            face = None
        if face is not None:
            fx, fy, fw, fh = face
            bottom = min(h, int(fy + 1.4 * fh))           # about shoulder height
            zone[:bottom, :] = True
            x0, x1 = max(0, int(fx - 0.35 * fw)), min(w, int(fx + 1.35 * fw))
            zone[:, x0:x1] = False                       # ignore the head itself
        else:
            zone[: int(0.55 * h), :] = True
            zone[:, int(0.33 * w): int(0.67 * w)] = False
        self.face = face
        return zone

    @staticmethod
    def skin_mask(bgr):
        """Skin-coloured pixels (YCrCb). Works across skin tones and lighting better than brightness."""
        ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
        return ((ycc[..., 1] >= 133) & (ycc[..., 1] <= 178) &
                (ycc[..., 2] >= 77) & (ycc[..., 2] <= 130))

    def features(self, gray, bgr):
        """(brightness-change fraction, new-skin fraction) of the raise zone."""
        if not self.zone.any():
            return 0.0, 0.0
        changed = np.abs(gray - self.base) > 25
        skin = self.skin_mask(bgr) & ~self.base_skin      # skin where there was none at rest
        return float(changed[self.zone].mean()), float(skin[self.zone].mean())

    def fraction(self, gray, bgr=None):
        if self.base is None:
            return 0.0
        bgr = self.last_bgr if bgr is None else bgr
        if bgr is None:
            return 0.0
        c, k = self.features(gray, bgr)
        return k if self.mode == "skin" else c

    def calibrate(self, preview):
        """Returns (True, info) if a raised hand can be told apart from hands down.
        `preview(frame, value)` shows the camera picture and returns the key pressed.
        Two signals are measured during the practice raise -- brightness change and
        new skin-coloured pixels -- and the one that separates "hand up" from
        "hand down" more clearly is used for the rest of the task."""
        # 1) hands down, sit still
        grays, bgrs = [], []
        end = time.time() + 2.5
        while time.time() < end:
            frame, g = self.read()
            if g is not None:
                grays.append(g)
                bgrs.append(self.last_bgr)
            _check_abort(preview(frame, None))
        if len(grays) < 5:
            return False, {"reason": "no camera frames"}
        k = len(grays) // 3
        self.base = np.median(np.stack(grays[k:]), axis=0)
        self.base_skin = np.stack([self.skin_mask(b) for b in bgrs[k:]]).mean(axis=0) >= 0.5
        self.zone = self._make_zone(self.base)
        rest = np.array([self.features(g, b) for g, b in zip(grays[k:], bgrs[k:])])
        rest_level = np.percentile(rest, 95, axis=0)                 # per feature
        # 2) practice raise
        say("Now raise your hand, and hold it up.", wait=False)
        vals = []
        t0 = time.time()
        while time.time() - t0 < 3.5:
            frame, g = self.read()
            f = self.features(g, self.last_bgr) if g is not None else None
            _check_abort(preview(frame, f[1] if f is not None else None))
            if f is not None and time.time() - t0 > 1.5:
                vals.append(f)
        say("Thank you. Put your hand down.", wait=False)
        t0 = time.time()
        while time.time() - t0 < 2.0:
            frame, g = self.read()
            _check_abort(preview(frame, None))
        if not vals:
            return False, {"reason": "no camera frames during the practice raise"}
        raised_level = np.percentile(np.array(vals), 70, axis=0)
        # pick the signal with the clearest gap between hand up and hand down
        gap = (raised_level - rest_level) / (rest_level + 0.02)
        idx = int(np.argmax(gap))
        self.mode = ("changed", "skin")[idx]
        b, p = float(rest_level[idx]), float(raised_level[idx])
        info = {"signal": self.mode, "rest_level": round(b, 4), "raised_level": round(p, 4),
                "face_found": self.face is not None}
        if p < max(2.5 * b, b + 0.03):
            return False, info
        self.thr_up = b + 0.4 * (p - b)
        self.thr_down = b + 0.15 * (p - b)
        info.update(thr_up=round(self.thr_up, 4), thr_down=round(self.thr_down, 4))
        return True, info

    def update(self, gray):
        """Hand up / down with hysteresis (needs 2 frames in a row to change)."""
        f = self.fraction(gray)
        want = f > self.thr_up if not self.up else f > self.thr_down
        if want != self.up:
            self._streak += 1
            if self._streak >= 2:
                self.up, self._streak = want, 0
        else:
            self._streak = 0
            if not self.up:      # slowly follow light changes while the hand is down
                self.base = 0.97 * self.base + 0.03 * gray
        return self.up, f

    def release(self):
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass


def _hand_up_runs(up_samples):
    """[(start, end)] of each time the hand was continuously up, from (time, is_up) samples."""
    runs, start, last = [], None, None
    for ts, up in up_samples:
        if up and start is None:
            start = ts
        if not up and start is not None:
            runs.append((start, ts))
            start = None
        last = ts
    if start is not None:
        runs.append((start, last))
    return runs


def score_letter_responses(letters, letter_times, raise_times, up_samples, interval):
    """
    letters[i] said at letter_times[i]; raise_times = moments the hand went up;
    up_samples = [(t, is_up)]. Returns (score, errors, per_letter).

    Window of letter i = from 0.15 s after it was said until the next letter.
      * "A": correct if the hand went up in its window, or was already up
        (raised for the previous A and kept there through "A A A").
      * other letter: an error only if the hand went UP in its window. A hand
        still held up from an earlier A is not penalised (the patient was
        not told to put it down at once), unless it has been up for more than
        two letter intervals -- then the patient is ignoring the task.
    0 or 1 error -> 1 point.
    """
    runs = _hand_up_runs(up_samples)
    per, errors = [], 0
    for i, (L, t) in enumerate(zip(letters, letter_times)):
        w0 = t + 0.15
        w1 = (letter_times[i + 1] if i + 1 < len(letters) else t + interval) + 0.15
        onset = any(w0 <= r < w1 for r in raise_times)
        ups = [u for (ts, u) in up_samples if w0 <= ts < w1]
        mostly_up = bool(ups) and np.mean(ups) >= 0.6
        if L == "A":
            ok = onset or mostly_up
        else:
            long_hold = mostly_up and any(
                rs <= w0 < re and (w0 - rs) > 2 * interval for rs, re in runs)
            ok = not (onset or long_hold)
        if not ok:
            errors += 1
        per.append({"letter": L, "raised": bool(onset or mostly_up), "ok": ok})
    return (1 if errors <= 1 else 0), errors, per


def run_letters(screen, cam_index, session_dir):
    title = "Attention - letters"
    cam_win = "Camera - hand raise"
    det = HandRaiseDetector(cam_index)
    mode = "camera"
    calib_info = {}
    letter_times, raise_times, up_samples = [], [], []
    trace = []          # (time, hand signal, hand up) for every camera frame -- for checking results

    def preview(frame, frac, up=None):
        """Show the camera picture (if any). Always processes window events.
        Returns the key pressed (255 if none)."""
        if frame is not None:
            disp = frame.copy()
            if det.zone is not None:
                z = cv2.resize(det.zone.astype(np.uint8) * 255, (disp.shape[1], disp.shape[0]),
                               interpolation=cv2.INTER_NEAREST)
                disp[z > 0] = (0.75 * disp[z > 0] + 0.25 * np.array([255, 200, 0])).astype(np.uint8)
            if up is not None:
                cv2.putText(disp, "HAND UP" if up else "hand down", (20, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 255) if up else (0, 160, 0), 3)
            cv2.imshow(cam_win, cv2.resize(disp, (640, int(640 * disp.shape[0] / disp.shape[1]))))
        return cv2.waitKey(1) & 0xFF

    try:
        if det.ok():
            for attempt in range(2):
                instruct(screen, title, "Please sit facing the camera, put your hands down on your lap, "
                                        "and keep still for a moment.")
                try:
                    ok, calib_info = det.calibrate(preview)
                except CameraAborted:
                    ok, calib_info, mode = False, {"reason": "cancelled with Esc"}, "keyboard"
                    break
                if ok:
                    break
                instruct(screen, title, "I could not see your hand clearly. Please raise your hand "
                                        "higher, to the side of your head, so the camera can see it.")
            else:
                mode = "keyboard"
        else:
            calib_info = {"reason": "camera could not be opened"}
            mode = "keyboard"
        if mode == "keyboard":
            print("[letters] camera not used -> examiner presses SPACE for each raise")
            screen.show(title, ["Camera cannot see the hand clearly.",
                                "EXAMINER: press SPACE in this window every time",
                                "the patient raises their hand."], color=(220, 235, 255))
            screen.wait(4)

        instruct(screen, title,
                 "I am going to read a list of letters. Every time I say the letter A, raise your hand, "
                 "and then put it down again. If I say a different letter, do not raise your hand.")
        screen.wait(1.0)
        screen.show(title, ["Listen... raise your hand at every A."], color=(245, 245, 230))

        start = time.time() + 0.5
        i = 0
        prev_up = False
        end = start + len(LETTERS) * LETTER_INTERVAL_S + 0.5
        while time.time() < end:
            now = time.time()
            if i < len(LETTERS) and now >= start + i * LETTER_INTERVAL_S:
                if HAS_VOICE:
                    say_letter(LETTERS[i])
                    letter_times.append(time.time() + 0.25)   # speech starts shortly after
                else:
                    letter_times.append(time.time())
                screen.show(title, ["Listen... raise your hand at every A.",
                                    f"letter {i + 1} of {len(LETTERS)}"],
                            big="" if HAS_VOICE else LETTERS[i], color=(245, 245, 230))
                i += 1
            key = 255
            if mode == "camera":
                frame, g = det.read()
                if g is not None:
                    up, frac = det.update(g)
                    t = time.time()
                    up_samples.append((t, up))
                    trace.append((round(t - start, 2), round(float(frac), 4), int(up)))
                    if up and not prev_up:
                        raise_times.append(t)
                    prev_up = up
                    key = preview(frame, frac, up)
                else:
                    key = preview(frame, None)           # keeps the window responsive
                    if not det.ok():                     # no picture for about 3 s
                        mode = "keyboard"
                        print("[letters] camera stopped sending pictures -> examiner presses SPACE")
                        screen.show(title, ["Camera stopped.", "EXAMINER: press SPACE in this window",
                                            "every time the patient raises their hand."],
                                    color=(220, 235, 255))
                if key == 27:                            # Esc: stop using the camera
                    mode = "keyboard"
                    print("[letters] camera stopped with Esc -> examiner presses SPACE")
            else:
                key = cv2.waitKey(15) & 0xFF
            if key == ord(" "):                          # examiner SPACE (keyboard mode or override)
                raise_times.append(time.time())
    finally:
        det.release()
        try:
            cv2.destroyWindow(cam_win)
        except Exception:
            pass
    score, errors, per = score_letter_responses(LETTERS, letter_times, raise_times, up_samples,
                                                LETTER_INTERVAL_S)
    missed = [k for k, p in enumerate(per) if p["letter"] == "A" and not p["ok"]]
    wrong = [f"{p['letter']}#{k + 1}" for k, p in enumerate(per) if p["letter"] != "A" and not p["ok"]]
    reason = (f"{errors} error(s): {len(missed)} missed A, {len(wrong)} raise(s) on other letters"
              + ("" if score else " (2 or more errors = 0)"))
    return score, reason, {"mode": mode, "errors": errors, "missed_A_positions": [m + 1 for m in missed],
                           "wrong_raises": wrong, "per_letter": per, "calibration": calib_info,
                           "letter_interval_s": LETTER_INTERVAL_S,
                           "letter_times_s": [round(t - start, 2) for t in letter_times],
                           "raise_times_s": [round(t - start, 2) for t in raise_times],
                           "trace": trace}


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def run_task7(cam_index=0, show_result=True):
    """Task 7: Letter A Detection (1 point)"""
    print("=" * 60)
    print("MoCA Task 7: Letters (Detect A)")
    print("=" * 60)
    screen = Screen()
    screen.show("Letters", ["Loading camera..."])
    session_dir = get_session_dir()

    # Letters A detection
    s, r, d = run_letters(screen, cam_index, session_dir)
    criteria = {"letters_a": s}
    parts = {"letters_a": {"score": s, "reason": r, **d}}

    lines = [f"Letters (A)     : {s} / 1"]
    print("\n--- RESULT ---")
    print(f"[Letters] {s}/1 — {r}")
    for line in lines:
        print(line)
    std = make_task_result("task7_letters", s, criteria=criteria,
                           reason=r, details=parts,
                           evidence_files=[session_dir / "task7_letters.wav" if
                                          (session_dir / "task7_letters.wav").exists() else None])
    print(f"Result saved to: {save_task_result(std)}")
    cleanup_console()
    screen.show(f"LETTERS SCORE: {s} / 1", lines, color=(235, 250, 235))
    screen.wait(6 if not show_result else 1)
    if show_result:
        cleanup_console()
        screen.show(f"LETTERS SCORE: {s} / 1", lines + ["", "Press any key to close."], color=(235, 250, 235))
        for _ in range(600):              # wait up to 60 s, then close by itself
            if cv2.waitKey(100) != -1:
                break
    cv2.destroyAllWindows()
    cv2.waitKey(1)
    return std


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", type=int, default=0, help="which webcam to use (default 0)")
    args = ap.parse_args()
    run_task7(cam_index=args.camera)
