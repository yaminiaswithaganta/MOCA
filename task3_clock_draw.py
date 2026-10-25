"""
MoCA Task 3 — Clock Drawing Test (CDT): "Draw a clock, put in all the
numbers, and set the hands to show ten past eleven (11:10)"
=============================================================================

Scored out of 3, same breakdown as the paper MoCA (each criterion is 0 or 1):
    1 point - Contour   : a closed, circular outline (a slightly shaky /
                           slightly oval hand-drawn circle is fine; a square,
                           an open arc or a scribble is not)
    1 point - Numbers   : all 12 numbers present, no extra numbers, in the
                           correct clockwise order and each near its correct
                           clock position
    1 point - Hands     : exactly two hands joined near the centre, the hour
                           hand clearly shorter, pointing at the required time
                           (11:10 -> hour hand at 11, minute hand at 2)

How it works
-------------
1. Opens the webcam, shows instructions and captures a photo 10 seconds
   after the paper is held up steady (auto-start; SPACE also starts it).
2. The paper is found and straightened and the pen strokes are extracted.
3. CONTOUR: the largest closed stroke is taken as the clock face; an ellipse
   is fitted and the outline's deviation from it is measured after smoothing
   out small hand tremor. It must be closed, round (only minor distortion),
   and big enough.
4. HANDS: straight strokes starting at the centre are found; they are
   grouped into hands; exactly two are required, and their direction and
   relative length are compared with the required time.
5. NUMBERS: with the outline and hands removed, the remaining marks are
   grouped into numbers; each is read by a small handwritten-digit model
   (models/mnist-8.onnx, run through OpenCV -- Tesseract is used as an
   optional second opinion if installed). Every one of the 12 clock
   positions must hold the right number, in the right order, and nothing
   may be left over.
Anything the system cannot verify scores 0 for that criterion.

Setup
-----
    pip install opencv-python numpy scikit-image
    # optional second opinion for reading numbers:
    #   pip install pytesseract  (+ the tesseract program, e.g. brew install tesseract)

Run
---
    python task3_clock_draw.py
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import cv2

from moca_common import (SteadyPaperDetector, _photo_to_width, _touches_border,
                         drawing_candidates, find_pen_ink, get_session_dir, ink_mask_from_gray,
                         make_task_result, merge_line_segments, prepare_drawing,
                         save_task_result, show_result_window, skeletonize_mask,
                         stroke_width)

try:  # optional second opinion for number reading
    import pytesseract
    pytesseract.get_tesseract_version()
except Exception:  # not installed / tesseract binary missing
    pytesseract = None

TASK_ID = "task3_clock_draw"

from moca_voice import speak_instruction, HAS_MAC_VOICE as HAS_VOICE


def say(text, wait=True, rate=150):
    """Speak an instruction through the shared moca_voice module."""
    return speak_instruction(text, wait=wait, rate=rate)


# The time the patient is asked to draw. Change it here only.
REQUIRED_TIME = (11, 10)   # (hour, minute) -> "ten past eleven"

CLOCK_TOL = {
    # contour
    "min_face_frac": 0.15,          # face radius >= 15% of the paper's short side
    "max_shape_deviation": 0.085,   # smoothed outline vs. fitted ellipse (x radius)
    "min_axis_ratio": 0.75,         # short/long axis (1.0 = perfect circle)
    "min_closure": 0.85,            # enclosed area / ellipse area (open arc -> ~0)
    "smooth_deg": 24,               # tremor smaller than this is ignored
    # hands
    "hand_center_dist": 0.25,       # hand must start within this x R of the centre
    "hand_line_dist": 0.12,         # line through the hand passes this close to centre
    "min_hand_len": 0.25,           # shorter centre strokes are ignored (x R)
    "hand_angle_tol": 20.0,         # degrees
    "max_hour_minute_ratio": 0.85,  # hour hand must be clearly shorter
    "hand_group_deg": 12.0,
    # numbers
    "number_slot_tol": 25.0,        # degrees from its correct clock position (tolerant of different handwriting/tilts)
    "number_max_rotation": 15,      # whole number ring may be rotated this much
    "number_slot_tol_rotated": 15.0,  # per-number tolerance when ring is rotated
    "number_ring": (0.35, 1.5),     # numbers may sit inside or just outside the circle
    "digit_confirm_prob": 0.25,     # P(expected number) to accept it (lowered for different handwriting)
    "digit_contradict_prob": 0.80,  # P(other number) to call it wrong (lowered for leniency)
    "max_unclear_numbers": 3,       # allow up to 3 unclear numbers (increased from 2)
}

LINE_MERGE_TOL = {"merge_angle_deg": 10.0, "merge_offset_frac": 0.04, "merge_gap_frac": 0.06,
                  "merge_gap_max_frac": 0.30, "gap_ink_coverage": 0.85}


# --------------------------------------------------------------------------
# 1. Camera capture (same pattern as Task 2)
# --------------------------------------------------------------------------
def capture_with_countdown(hold_seconds=10, cam_index=0, save_path=None, auto_start=True):
    if save_path is None:
        save_path = str(get_session_dir() / "clock_capture.png")
    cap = cv2.VideoCapture(cam_index)
    if not cap.isOpened():
        raise RuntimeError("Could not open webcam. Check cam_index / permissions.")

    instructions = [
        "1) Draw a large circle",
        "2) Write in all 12 numbers where they belong",
        "3) Draw the hands to show TEN PAST ELEVEN (11:10)",
        "HOLD THE CLOCK TO THE CAMERA:",
        "- face the camera, straight (NOT tilted)",
        "- NOT upside down, whole clock in view",
    ]

    # Voice instructions
    say("Draw a clock. First, draw a large circle. Then write all 12 numbers in their correct positions around the circle. "
        "Finally, draw two hands to show the time ten past eleven, or eleven ten. "
        "Then hold the clock up to the camera. Hold it straight, not tilted, and not upside down, "
        "with the whole clock in view.")

    print("\n".join(instructions))
    print("Hold the clock straight to the camera: not tilted, not upside down.")
    print("The countdown starts automatically once the drawing is held up steady "
          f"(or press SPACE). {hold_seconds}s countdown. Press q to quit.")

    countdown_started = None
    steady = SteadyPaperDetector() if auto_start else None
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        display = frame.copy()

        if countdown_started is None:
            y = 30
            for line in instructions:
                cv2.putText(display, line, (20, y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (0, 255, 0), 2)
                y += 30
            cv2.putText(display, "Hold still (auto) or press SPACE when ready", (20, y + 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            if steady is not None and steady.update(frame):
                print("[capture] Paper detected and steady -- starting countdown.")
                countdown_started = time.time()
        else:
            remaining = hold_seconds - (time.time() - countdown_started)
            if remaining <= 0:
                cv2.imwrite(save_path, frame)
                print(f"[capture] Photo saved to {save_path}")
                break
            cv2.putText(display, f"Hold steady... capturing in {int(remaining) + 1}s",
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)

        cv2.imshow("MoCA Task 3 - Clock Drawing", display)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            cap.release()
            cv2.destroyAllWindows()
            return None
        if key == ord(" ") and countdown_started is None:
            countdown_started = time.time()

    cap.release()
    cv2.destroyAllWindows()
    return save_path


# --------------------------------------------------------------------------
# 2. Geometry helpers
# --------------------------------------------------------------------------
def clock_angle_for_hour_position(hour):
    """
    Angle (degrees, clockwise from 12 o'clock / straight up) that the
    given clock-face number sits at. 12 numbers spaced 30 degrees apart.
    """
    return (hour % 12) * 30.0


def required_hand_angles(hour=REQUIRED_TIME[0], minute=REQUIRED_TIME[1]):
    """(hour-hand angle, minute-hand angle), clockwise from 12, for the required time."""
    return ((hour % 12) * 30.0 + minute * 0.5) % 360, (minute * 6.0) % 360


def point_to_segment_distance(px, py, x1, y1, x2, y2):
    line_len_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
    if line_len_sq == 0:
        return np.hypot(px - x1, py - y1)
    t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_len_sq))
    proj_x, proj_y = x1 + t * (x2 - x1), y1 + t * (y2 - y1)
    return np.hypot(px - proj_x, py - proj_y)


def _clock_angle(dx, dy):
    """Image vector -> clock angle (0 = up / 12 o'clock, clockwise)."""
    return float(np.degrees(np.arctan2(dx, -dy)) % 360)


def _angle_diff360(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


class Face:
    """Fitted clock face: centre, ellipse axes; converts points to (angle, rho)."""

    def __init__(self, center, axes, angle_deg):
        self.center = np.asarray(center, float)
        self.a, self.b = max(axes) / 2.0, min(axes) / 2.0   # semi-axes
        # cv2.fitEllipse angle refers to the first axis; keep the long one
        self.theta = np.radians(angle_deg if axes[0] >= axes[1] else angle_deg + 90)
        self.R = float(np.sqrt(self.a * self.b))

    def rho(self, pts):
        """Normalised radius: 1.0 on the fitted outline, 0 at the centre."""
        d = np.atleast_2d(pts) - self.center
        c, s = np.cos(-self.theta), np.sin(-self.theta)
        x = d[:, 0] * c - d[:, 1] * s
        y = d[:, 0] * s + d[:, 1] * c
        return np.sqrt((x / self.a) ** 2 + (y / self.b) ** 2)

    def clock_angle(self, pts):
        d = np.atleast_2d(pts) - self.center
        return np.degrees(np.arctan2(d[:, 0], -d[:, 1])) % 360


# --------------------------------------------------------------------------
# 3. CONTOUR scoring
# --------------------------------------------------------------------------
def find_clock_face(ink):
    """
    Largest stroke on the page = the clock outline. Returns dict with the
    fitted Face and the outline's contours, or None if nothing big enough.
    """
    h, w = ink.shape
    k = max(3, int(min(h, w) * 0.015)) | 1
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    if n <= 1:
        return None
    bbox_area = stats[1:, cv2.CC_STAT_WIDTH] * stats[1:, cv2.CC_STAT_HEIGHT]
    best = 1 + int(np.argmax(bbox_area))
    bw, bh = stats[best, cv2.CC_STAT_WIDTH], stats[best, cv2.CC_STAT_HEIGHT]
    if max(bw, bh) < 0.2 * min(h, w):
        return None
    comp = (labels == best).astype(np.uint8) * 255
    contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outer = max(contours, key=len)
    if len(outer) < 20:
        return None
    all_contours, _ = cv2.findContours(comp, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    # fit ellipse to the outer boundary, then refine ignoring outliers
    pts = outer.reshape(-1, 2).astype(np.float32)
    ell = cv2.fitEllipse(pts)
    face = Face(ell[0], ell[1], ell[2])
    for _ in range(2):
        r = face.rho(pts)
        keep = np.abs(r - np.median(r)) < 0.15
        if keep.sum() < 20:
            break
        ell = cv2.fitEllipse(pts[keep])
        face = Face(ell[0], ell[1], ell[2])
    return {"face": face, "outer": outer, "contours": all_contours, "component": comp,
            "ellipse": ell}


def score_contour_face(face_info, paper_shape):
    """0/1 for the clock outline, plus measurements explaining the decision."""
    tol = CLOCK_TOL
    if face_info is None:
        return 0, {"reason": "no clock outline found"}
    face = face_info["face"]
    pts = face_info["outer"].reshape(-1, 2).astype(float)
    rho = face.rho(pts)
    ang = face.clock_angle(pts)
    # outer radius per 3-degree bin, then smooth out hand tremor
    nb = 120
    bins = (ang / (360 / nb)).astype(int) % nb
    prof = np.full(nb, np.nan)
    for b in range(nb):
        sel = rho[bins == b]
        if sel.size:
            prof[b] = sel.max()
    covered = np.isfinite(prof)
    coverage = float(covered.mean())
    if covered.sum() < nb * 0.5:
        return 0, {"reason": "outline is not a closed round shape", "coverage": coverage}
    idx = np.arange(nb)
    prof = np.interp(idx, idx[covered], prof[covered], period=nb)
    win = max(1, int(tol["smooth_deg"] / (360 / nb)))
    kern = np.ones(win) / win
    smooth = np.convolve(np.concatenate([prof[-win:], prof, prof[:win]]), kern, mode="same")[win:-win]
    deviation = float(np.max(np.abs(smooth - np.median(smooth))))
    axis_ratio = face.b / face.a
    closure = float(cv2.contourArea(face_info["outer"]) / (np.pi * face.a * face.b))
    size_frac = face.R / min(paper_shape)
    info = {"shape_deviation": deviation, "axis_ratio": axis_ratio, "closure": closure,
            "coverage": coverage, "radius_frac": size_frac,
            "center": face.center.round(1).tolist(), "radius": round(face.R, 1)}
    fails = []
    if closure < tol["min_closure"]:
        fails.append(f"outline not closed (closure {closure:.2f})")
    if deviation > tol["max_shape_deviation"]:
        fails.append(f"outline not circular (deviation {deviation:.3f})")
    if axis_ratio < tol["min_axis_ratio"]:
        fails.append(f"outline too oval (axis ratio {axis_ratio:.2f})")
    if size_frac < tol["min_face_frac"]:
        fails.append("outline too small")
    info["reason"] = "; ".join(fails) if fails else "closed circular outline"
    return (0 if fails else 1), info


def score_contour(gray, circularity_threshold=None):
    """Backwards-compatible entry point: grayscale image -> (score, info)."""
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    face_info = find_clock_face(ink)
    return score_contour_face(face_info, gray.shape)


# --------------------------------------------------------------------------
# 4. HANDS scoring
# --------------------------------------------------------------------------
def detect_hands(ink, face):
    """
    Straight strokes that start at the clock centre. Returns a list of hands
    [{"angle": deg clockwise from 12, "length": px, "length_R": x radius, "tip": (x,y)}].
    """
    tol = CLOCK_TOL
    R, C = face.R, face.center
    h, w = ink.shape
    yy, xx = np.mgrid[0:h, 0:w]
    inside = face.rho(np.stack([xx.ravel(), yy.ravel()], 1)).reshape(h, w) < 0.92
    region = ((ink > 0) & inside).astype(np.uint8) * 255
    if not region.any():
        return [], []
    skel = cv2.dilate(skeletonize_mask(region), np.ones((3, 3), np.uint8))
    lines = cv2.HoughLinesP(skel, 1, np.pi / 180, threshold=max(8, int(0.06 * R)),
                            minLineLength=max(6, int(0.08 * R)), maxLineGap=max(3, int(0.05 * R)))
    if lines is None:
        return [], []
    segs = merge_line_segments(list(lines.reshape(-1, 4)), R, LINE_MERGE_TOL,
                               cv2.dilate(region, np.ones((5, 5), np.uint8)))
    rays = []
    for s in segs:
        p, q = s[:2], s[2:]
        dp, dq = np.linalg.norm(p - C), np.linalg.norm(q - C)
        if point_to_segment_distance(C[0], C[1], *p, *q) > tol["hand_line_dist"] * R:
            continue
        near, far = (p, q) if dp <= dq else (q, p)
        if min(dp, dq) <= tol["hand_center_dist"] * R:
            rays.append({"tip": far, "length": max(dp, dq)})
        else:  # one straight stroke drawn right through the centre = two rays
            rays.append({"tip": p, "length": dp})
            rays.append({"tip": q, "length": dq})
    for r in rays:
        r["angle"] = _clock_angle(*(r["tip"] - C))
    # group rays pointing the same way (fragments / double strokes of one hand)
    rays.sort(key=lambda r: r["angle"])
    groups = []
    for r in rays:
        if groups and _angle_diff360(r["angle"], groups[-1][-1]["angle"]) <= tol["hand_group_deg"]:
            groups[-1].append(r)
        else:
            groups.append([r])
    if len(groups) > 1 and _angle_diff360(groups[0][0]["angle"], groups[-1][-1]["angle"]) <= tol["hand_group_deg"]:
        groups[0] = groups.pop() + groups[0]
    hands = []
    for g in groups:
        top = max(g, key=lambda r: r["length"])
        if top["length"] >= tol["min_hand_len"] * R:
            hands.append({"angle": top["angle"], "length": top["length"],
                          "length_R": top["length"] / R, "tip": top["tip"]})
    return hands, segs


def score_hands_face(hands, face_found=True, numbers_rotation=0.0):
    """Hands are judged against where the patient put the numbers (numbers_rotation)."""
    tol = CLOCK_TOL
    exp_hour, exp_min = required_hand_angles()
    exp_hour, exp_min = (exp_hour + numbers_rotation) % 360, (exp_min + numbers_rotation) % 360
    info = {"hands_found": len(hands), "expected_hour_angle": exp_hour,
            "expected_minute_angle": exp_min,
            "hands": [{"angle": round(hd["angle"], 1), "length_R": round(hd["length_R"], 2)} for hd in hands]}
    if not face_found:
        info["reason"] = "no clock face / centre found"
        return 0, info
    if len(hands) == 0:
        info["reason"] = "no hands found"
        return 0, info
    if len(hands) == 1:
        info["reason"] = "only one hand found"
        return 0, info
    if len(hands) > 2:
        info["reason"] = f"{len(hands)} lines leave the centre (expected exactly 2 hands)"
        return 0, info
    minute, hour = sorted(hands, key=lambda hd: -hd["length"])
    ratio = hour["length"] / minute["length"]
    hour_err = _angle_diff360(hour["angle"], exp_hour)
    minute_err = _angle_diff360(minute["angle"], exp_min)
    info.update({"hour_hand_angle": round(hour["angle"], 1), "minute_hand_angle": round(minute["angle"], 1),
                 "hour_error_deg": round(hour_err, 1), "minute_error_deg": round(minute_err, 1),
                 "hour_to_minute_length": round(ratio, 2)})
    fails = []
    if ratio > tol["max_hour_minute_ratio"]:
        fails.append(f"hour hand not clearly shorter than minute hand (ratio {ratio:.2f})")
    if hour_err > tol["hand_angle_tol"]:
        fails.append(f"hour hand points to {hour['angle']:.0f} deg, needs {exp_hour:.0f}")
    if minute_err > tol["hand_angle_tol"]:
        fails.append(f"minute hand points to {minute['angle']:.0f} deg, needs {exp_min:.0f}")
    info["reason"] = "; ".join(fails) if fails else "hands show the required time"
    return (0 if fails else 1), info


# --------------------------------------------------------------------------
# 5. NUMBERS scoring
# --------------------------------------------------------------------------
MNIST_MODEL_PATH = Path(__file__).resolve().parent / "models" / "mnist-8.onnx"
_mnist_net = None


def _mnist():
    global _mnist_net
    if _mnist_net is None:
        if not MNIST_MODEL_PATH.exists():
            raise FileNotFoundError(f"digit model missing: {MNIST_MODEL_PATH}")
        _mnist_net = cv2.dnn.readNetFromONNX(str(MNIST_MODEL_PATH))
    return _mnist_net


def _to_mnist(mask, thickness=2.2, rotate_deg=0.0):
    """Binary digit mask -> 28x28 MNIST-style image in [0, 1] (white digit, black bg)."""
    ys, xs = np.nonzero(mask)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    pad = max(crop.shape) // 4 + 2
    crop = cv2.copyMakeBorder(crop, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    if rotate_deg:
        M = cv2.getRotationMatrix2D((crop.shape[1] / 2, crop.shape[0] / 2), rotate_deg, 1.0)
        crop = cv2.warpAffine(crop, M, (crop.shape[1], crop.shape[0]))
    skel = skeletonize_mask((crop > 127).astype(np.uint8) * 255)
    ys, xs = np.nonzero(skel)
    if ys.size == 0:
        return np.zeros((28, 28), np.float32)
    skel = skel[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = skel.shape
    s = 20.0 / max(h, w)
    # redraw the pen centre-line with an MNIST-like stroke width at 28x28 scale
    t = max(1, int(round(thickness / s)))
    big = cv2.copyMakeBorder(skel, t, t, t, t, cv2.BORDER_CONSTANT, value=0)
    big = cv2.dilate(big, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (t, t)))
    h, w = big.shape
    s = 20.0 / max(h, w)
    small = cv2.resize(big, (max(1, int(round(w * s))), max(1, int(round(h * s)))),
                       interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    out = np.zeros((28, 28), np.float32)
    sh, sw_ = small.shape
    y0, x0 = (28 - sh) // 2, (28 - sw_) // 2
    out[y0:y0 + sh, x0:x0 + sw_] = small
    m = cv2.moments(out)
    if m["m00"] > 0:
        M = np.float32([[1, 0, 14 - m["m10"] / m["m00"]], [0, 1, 14 - m["m01"] / m["m00"]]])
        out = cv2.warpAffine(out, M, (28, 28))
    return out


HOG_MODEL_PATH = Path(__file__).resolve().parent / "models" / "digits_hog_softmax.npz"
_hog_model = None


def _hog(img, cell=7, bins=9):
    """Plain-numpy HOG (OpenCV 5 dropped cv2.HOGDescriptor): 2x2-cell blocks, L2-Hys."""
    img = img.astype(np.float32)
    gx = np.zeros_like(img)
    gy = np.zeros_like(img)
    gx[:, 1:-1] = img[:, 2:] - img[:, :-2]
    gy[1:-1, :] = img[2:, :] - img[:-2, :]
    mag = np.hypot(gx, gy)
    ang = np.degrees(np.arctan2(gy, gx)) % 180.0
    pos = ang / (180.0 / bins)
    b0 = np.floor(pos).astype(int) % bins
    b1 = (b0 + 1) % bins
    w1 = pos - np.floor(pos)
    n = img.shape[0] // cell
    hist = np.zeros((n, n, bins), np.float32)
    for cy in range(n):
        for cx in range(n):
            sl = (slice(cy * cell, (cy + 1) * cell), slice(cx * cell, (cx + 1) * cell))
            m, a0, a1, w = mag[sl].ravel(), b0[sl].ravel(), b1[sl].ravel(), w1[sl].ravel()
            hist[cy, cx] = (np.bincount(a0, m * (1 - w), bins) + np.bincount(a1, m * w, bins))
    feats = []
    for by in range(n - 1):
        for bx in range(n - 1):
            v = hist[by:by + 2, bx:bx + 2].ravel()
            v = v / np.sqrt((v ** 2).sum() + 1e-6)
            v = np.minimum(v, 0.2)
            v = v / np.sqrt((v ** 2).sum() + 1e-6)
            feats.append(v)
    return np.concatenate(feats)


def digit_features(x28):
    """HOG + coarse pixel features of a 28x28 [0,1] digit (for the back-up reader)."""
    h = _hog(x28 * 255.0)
    px = cv2.resize(x28, (14, 14), interpolation=cv2.INTER_AREA).ravel()
    return np.concatenate([h, px]).astype(np.float32)


def _hog_probs(x28):
    global _hog_model
    if _hog_model is None:
        if not HOG_MODEL_PATH.exists():
            return None
        _hog_model = dict(np.load(HOG_MODEL_PATH))
    m = _hog_model
    z = ((digit_features(x28) - m["mu"]) / m["sd"]) @ m["W"].T + m["b"]
    z = np.exp(z - z.max())
    return z / z.sum()


def classify_digit(mask):
    """
    Handwritten digit -> (digit, probability, all 10 probabilities).
    Two readers are averaged: the MNIST CNN (over a few stroke widths / small
    rotations, so one odd rendering can't decide) and the HOG back-up model.
    """
    net = _mnist()
    views = [_to_mnist(mask, t, r) for t in (1.6, 2.2, 3.0) for r in (-8.0, 0.0, 8.0)]
    # one view at a time: the model has a fixed batch size of 1 (OpenCV 5 enforces it)
    logits = []
    for v in views:
        net.setInput(v[None, None].astype(np.float32))
        logits.append(net.forward().reshape(-1)[:10])
    logits = np.array(logits, dtype=np.float64)
    p = np.exp(logits - logits.max(axis=1, keepdims=True))
    p /= p.sum(axis=1, keepdims=True)
    p = p.mean(axis=0)
    ph = _hog_probs(views[4])
    if ph is not None:
        p = 0.5 * p + 0.5 * ph
    d = int(np.argmax(p))
    return d, float(p[d]), p


def _tesseract_read(mask):
    if pytesseract is None:
        return None
    ys, xs = np.nonzero(mask)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = crop.shape
    s = 60.0 / max(h, 1)
    crop = cv2.resize(crop, (max(1, int(w * s)), 60), interpolation=cv2.INTER_NEAREST)
    img = cv2.copyMakeBorder(255 - crop, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    try:
        txt = pytesseract.image_to_string(img, config="--psm 8 -c tessedit_char_whitelist=0123456789")
    except Exception:
        return None
    txt = "".join(ch for ch in txt if ch.isdigit())
    return int(txt) if txt else None


def read_number(glyph_mask):
    """
    Read one clock number from its mask. Side-by-side parts are read as
    separate digits ("1" + "2" -> 12). Returns
    dict(value, prob, digits=[(digit, prob)], probs=[10-vector per digit], heights).
    """
    n, labels, stats, _ = cv2.connectedComponentsWithStats(glyph_mask, connectivity=8)
    parts = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > 0]
    # join parts that overlap horizontally (a digit drawn in 2 strokes)
    boxes = [[stats[i, 0], stats[i, 0] + stats[i, 2], [i]] for i in parts]
    boxes.sort(key=lambda b: b[0])
    digits = []
    for b in boxes:
        if digits:
            last = digits[-1]
            overlap = min(last[1], b[1]) - max(last[0], b[0])
            if overlap > 0.4 * min(last[1] - last[0], b[1] - b[0]):
                last[1] = max(last[1], b[1])
                last[2] += b[2]
                continue
        digits.append(list(b))
    if not 1 <= len(digits) <= 3:
        return {"value": None, "prob": 0.0, "digits": [], "probs": [], "heights": []}
    read, probs, heights = [], [], []
    for _, _, ids in digits:
        m = np.isin(labels, ids).astype(np.uint8) * 255
        d, p, pv = classify_digit(m)
        read.append((d, p))
        probs.append(pv)
        ys = np.nonzero(m)[0]
        heights.append(int(ys.max() - ys.min() + 1))
    value = int("".join(str(d) for d, _ in read))
    return {"value": value, "prob": float(np.prod([p for _, p in read])), "digits": read,
            "probs": probs, "heights": heights}


def _split_touching_digits(mask):
    """
    A two-digit number written with touching digits ("12" as one blob):
    cut it at the thinnest column near the middle. Returns the two halves or None.
    """
    ys, xs = np.nonzero(mask)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = crop.shape
    if w < 0.8 * h:
        return None
    cols = (crop > 0).sum(axis=0).astype(float)
    lo, hi = int(0.3 * w), int(0.7 * w)
    if hi <= lo:
        return None
    cut = lo + int(np.argmin(cols[lo:hi]))
    left, right = crop.copy(), crop.copy()
    left[:, cut:] = 0
    right[:, :cut] = 0
    if left.sum() == 0 or right.sum() == 0:
        return None
    return left, right


def _p_expected(mask, expected):
    """Best probability, over plausible ways of splitting the mark into digits,
    that it reads as `expected` (a string like "12"). Also returns the best
    alternative reading."""
    r = read_number(mask)
    cands = []
    if r["digits"] and len(r["digits"]) == len(expected):
        cands.append(float(np.prod([pv[int(ch)] for pv, ch in zip(r["probs"], expected)])))
    if len(expected) == 2 and len(r["digits"]) == 1:
        halves = _split_touching_digits(mask)
        if halves is not None:
            pl = classify_digit(halves[0])[2]
            pr = classify_digit(halves[1])[2]
            cands.append(float(pl[int(expected[0])] * pr[int(expected[1])]))
    return (max(cands) if cands else None), r


def _judge_reading(r, slot, mask):
    """
    Does this mark read as the number that belongs in `slot`?
    confirmed     - the digit model finds the expected number plausible
    contradiction - it is confidently a DIFFERENT number (wrong order/number)
    unclear       - can't tell either way

    More lenient with different handwriting styles: lower thresholds for confirmation.
    """
    tol = CLOCK_TOL
    expected = str(slot)
    if not r["digits"]:
        return "unclear"
    p_exp, _ = _p_expected(mask, expected)
    if p_exp is None:
        # e.g. two clear digits ("11" or "13") where a single "1"/"2" belongs
        if len(r["digits"]) > len(expected) and (
                min(r["heights"]) >= 0.5 * max(r["heights"]) or r["prob"] >= tol["digit_contradict_prob"]):
            return "contradiction" if _tesseract_read(mask) != slot else "unclear"
        return "unclear"
    p_best = r["prob"]
    r["p_expected"] = p_exp
    # Lower threshold for confirmation (0.25 instead of 0.30) to accept more different handwriting
    if p_exp >= tol["digit_confirm_prob"]:
        return "confirmed"
    tess = _tesseract_read(mask)
    # More lenient: lower contradiction threshold
    if p_exp < 0.01 and p_best >= tol["digit_contradict_prob"]:
        return "unclear" if tess == slot else "contradiction"
    return "confirmed" if tess == slot else "unclear"


def find_number_marks(ink, face_info, face, hands, sw):
    """Remove outline + hands; group what is left into candidate numbers."""
    work = ink.copy()
    erase = np.zeros_like(ink)
    if face_info is not None:
        # erase along the OUTER boundary only: numbers written against the
        # inside of the circle keep their shape (only a sliver is removed)
        cv2.drawContours(erase, [face_info["outer"]], -1, 255, thickness=max(3, int(3.2 * sw)))
    for hd in hands:
        # inner part of the hand: erase carefully; outer part (where it may
        # touch the number it points at): erase only a thin line (don't destroy numbers)
        c0 = face.center
        tip = np.asarray(hd["tip"], float)
        mid = c0 + (tip - c0) * min(1.0, 0.5 * face.R / max(hd["length"], 1e-6))
        cv2.line(erase, tuple(int(v) for v in c0), tuple(int(v) for v in mid),
                 255, thickness=max(2, int(2.5 * sw)))
        cv2.line(erase, tuple(int(v) for v in mid), tuple(int(v) for v in tip),
                 255, thickness=max(2, int(1.2 * sw) + 1))
    cv2.circle(erase, tuple(int(v) for v in face.center), max(3, int(0.06 * face.R)), 255, -1)
    work[erase > 0] = 0
    n, labels, stats, cents = cv2.connectedComponentsWithStats(work, connectivity=8)
    R = face.R
    comps = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        size = max(w, h)
        # More lenient size filtering for different handwriting styles
        if size < 0.03 * R or area < max(5, 0.0002 * R * R):
            continue       # specks / remnants of erased lines
        if size > 0.75 * R:
            comps.append({"id": i, "box": (x, y, w, h), "too_big": True})
            continue
        comps.append({"id": i, "box": (x, y, w, h), "too_big": False})
    # group parts that sit next to each other (e.g. "1" + "2" -> 12)
    parent = list(range(len(comps)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(len(comps)):
        for j in range(i + 1, len(comps)):
            if comps[i]["too_big"] or comps[j]["too_big"]:
                continue
            xi, yi, wi, hi = comps[i]["box"]
            xj, yj, wj, hj = comps[j]["box"]
            gx = max(0, max(xi, xj) - min(xi + wi, xj + wj))
            y_overlap = min(yi + hi, yj + hj) - max(yi, yj)
            x_overlap = min(xi + wi, xj + wj) - max(xi, xj)
            side_by_side = gx <= 0.8 * max(hi, hj) and y_overlap >= 0.4 * min(hi, hj)
            stacked = x_overlap >= 0.4 * min(wi, wj) and \
                max(0, max(yi, yj) - min(yi + hi, yj + hj)) <= 0.45 * max(hi, hj)  # e.g. a "5" drawn in 2 strokes
            ai = face.clock_angle(np.array([xi + wi / 2, yi + hi / 2]))[0]
            aj = face.clock_angle(np.array([xj + wj / 2, yj + hj / 2]))[0]
            same_position = _angle_diff360(ai, aj) <= 15.0   # neighbours are ~30 deg apart, allow some variation
            H = max(hi, hj)
            gy = max(0, max(yi, yj) - min(yi + hi, yj + hj))
            ux = max(xi + wi, xj + wj) - min(xi, xj)
            uy = max(yi + hi, yj + hj) - min(yi, yj)
            # nearly touching strokes that together are still digit-sized
            # (e.g. the detached top bar of a handwritten "5")
            touching = gx <= 0.2 * H and gy <= 0.2 * H and max(ux, uy) <= 1.5 * H
            if (side_by_side or stacked or touching) and same_position:
                parent[find(i)] = find(j)
    groups = {}
    for i, c in enumerate(comps):
        groups.setdefault(find(i), []).append(c)
    marks = []
    for g in groups.values():
        mask = np.isin(labels, [c["id"] for c in g]).astype(np.uint8) * 255
        ys, xs = np.nonzero(mask)
        cx, cy = xs.mean(), ys.mean()
        marks.append({"mask": mask, "center": np.array([cx, cy]),
                      "box": (xs.min(), ys.min(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1),
                      "too_big": any(c["too_big"] for c in g)})
    return marks


def _slot_covered_by_hand(n, face, hands, ink, sw, delta=0.0):
    """
    True if a hand ends on number position n and there is pen ink there that
    is not part of the hand itself (the number is drawn but touches the hand).
    """
    ang = (clock_angle_for_hour_position(n) + delta) % 360
    for hd in hands:
        if _angle_diff360(hd["angle"], ang) > 15 or hd["length_R"] < 0.6:
            continue
        tip = np.asarray(hd["tip"], float)
        region = np.zeros_like(ink)
        cv2.circle(region, tuple(int(v) for v in tip), int(0.15 * face.R), 255, -1)
        cv2.line(region, tuple(int(v) for v in face.center), tuple(int(v) for v in tip), 0,
                 thickness=max(3, int(2 * sw) + 2))
        extra_ink = int(((ink > 0) & (region > 0)).sum())
        if extra_ink >= 0.002 * face.R * face.R + 3 * sw * sw:
            return True
    return False


def score_numbers_face(marks, face, hands, ink, sw):
    """
    0/1: all 12 numbers present, right order, right positions, nothing extra.
    Tolerates different handwriting styles and paper tilts up to 15 degrees.
    Tries to find the best number alignment allowing for natural variations
    in how patients draw and hold the paper.
    """
    tol = CLOCK_TOL
    for m in marks:
        m["rho"] = float(face.rho(m["center"])[0])
        m["angle"] = float(face.clock_angle(m["center"])[0])
    cache = {}
    best = None
    # Try rotation angles with reasonable tolerance
    lim = int(tol["number_max_rotation"])
    for delta in sorted(range(-lim, lim + 1, 5), key=abs):  # Check every 5 degrees
        score, info = _numbers_at_rotation(marks, face, hands, ink, sw, delta, cache)
        key = (score, info["confirmed"], -info["contradiction"], -info["missing"],
               -info["extra_marks"], -abs(delta))
        if best is None or key > best[0]:
            best = (key, score, info)

    return best[1], best[2]


def _numbers_at_rotation(marks, face, hands, ink, sw, delta, cache):
    tol = CLOCK_TOL
    lo, hi = tol["number_ring"]
    info = {"marks_found": len(marks), "rotation_deg": delta}
    slots = {n: [] for n in range(1, 13)}
    stray = []
    for m in marks:
        rho, ang = m["rho"], (m["angle"] - delta) % 360
        if rho < 0.3:
            continue    # leftovers where the hands join at the centre
        if m["too_big"] or not lo <= rho <= hi:
            stray.append(m)
            continue
        slot = int(round(ang / 30.0)) % 12 or 12
        slot_tol = tol["number_slot_tol"] if delta == 0 else tol["number_slot_tol_rotated"]
        if _angle_diff360(ang, clock_angle_for_hour_position(slot)) > slot_tol:
            stray.append(m)
            continue
        slots[slot].append(m)

    # a hand tip (arrow head) can run into the number it points at: that is not a wrong number
    def near_hand_tip(m, reach=0.15):
        return any(np.linalg.norm(m["center"] - hd["tip"]) < reach * face.R for hd in hands)

    # a "number" much bigger than the others = several things run together
    heights = [m["box"][3] for n in slots for m in slots[n]]
    med_h = float(np.median(heights)) if heights else 0.0
    per_slot = {}
    unexplained = []
    for n in range(1, 13):
        cands = slots[n]
        if not cands:
            # A hand pointing at this number may cover it: count it as
            # "unclear" (not "missing") only if ink is really there.
            per_slot[n] = {"status": "unclear" if _slot_covered_by_hand(n, face, hands, ink, sw, delta)
                           else "missing"}
            continue
        results = []
        for m in cands:
            key = id(m)
            if key not in cache:
                cache[key] = read_number(m["mask"])
            r = cache[key]
            if (key, n) not in cache:
                cache[(key, n)] = _judge_reading(r, n, m["mask"])
            status = cache[(key, n)]
            if med_h and m["box"][3] > 1.6 * med_h and status != "confirmed":
                status = "contradiction"
            # an arrow head merged into a number reads as an extra digit ("2" -> "57"): not a wrong number
            if status == "contradiction" and near_hand_tip(m) and len(r["digits"]) > len(str(n)):
                status = "unclear"
            results.append((m, r, status))
        order = {"confirmed": 0, "unclear": 1, "contradiction": 2}
        results.sort(key=lambda t: (order[t[2]], -t[1]["prob"]))
        m, r, status = results[0]
        per_slot[n] = {"status": status, "read": r["value"], "prob": round(r["prob"], 3),
                       "angle": round(m["angle"], 1)}
        unexplained += [t[0] for t in results[1:]]

    # tiny ticks/dots (e.g. where the circle's ends overlap) are not numbers
    def is_tiny(m):
        return med_h and max(m["box"][2], m["box"][3]) < 0.5 * med_h

    # a short fragment just beyond an arrow tip is part of the arrow, not a number;
    # a full-height numeral next to a hand is still an extra number
    def arrow_fragment(m):
        return bool(med_h) and m["box"][3] < 0.6 * med_h and near_hand_tip(m, reach=0.25)

    extra = [m for m in unexplained + stray
             if not near_hand_tip(m) and not is_tiny(m) and not arrow_fragment(m)]
    counts = {s: sum(1 for v in per_slot.values() if v["status"] == s)
              for s in ("confirmed", "unclear", "contradiction", "missing")}
    # one small speck or tick (much smaller than a numeral) next to a clear ring: a person ignores it.
    # A full-size extra number still counts.
    if len(extra) == 1 and counts["contradiction"] == 0 and counts["missing"] == 0 \
            and counts["unclear"] <= 1 and med_h \
            and max(extra[0]["box"][2], extra[0]["box"][3]) < 0.7 * med_h:
        extra = []
    info.update({"slots": per_slot, "extra_marks": len(extra), **counts})
    fails = []
    if counts["missing"]:
        miss = [n for n, v in per_slot.items() if v["status"] == "missing"]
        fails.append(f"no number at position(s) {miss}")
    if counts["contradiction"]:
        wrong = [f"{n}->{v['read']}" for n, v in per_slot.items() if v["status"] == "contradiction"]
        fails.append(f"wrong number/order at {wrong}")
    if counts["unclear"] > tol["max_unclear_numbers"]:
        fails.append(f"{counts['unclear']} numbers could not be read reliably")
    if extra:
        fails.append(f"{len(extra)} extra/misplaced mark(s) outside the 12 clock positions")
    info["reason"] = "; ".join(fails) if fails else "12 numbers in correct order and positions"
    return (0 if fails else 1), info


def _small_mark_centres(ink):
    n, labels, stats, cents = cv2.connectedComponentsWithStats(ink, connectivity=8)
    if n <= 1:
        return np.zeros((0, 2))
    ys, xs = np.nonzero(ink)
    span = max(xs.max() - xs.min(), ys.max() - ys.min(), 1)
    return np.array([cents[i] for i in range(1, n)
                     if 0.02 * span < max(stats[i, 2], stats[i, 3]) < 0.2 * span]).reshape(-1, 2)


def _marks_fit_face(ink, face):
    """Do most small marks (numbers) sit around this face, as on a clock?"""
    pts = _small_mark_centres(ink)
    if len(pts) < 6:
        return True
    rho = face.rho(pts)
    ang = face.clock_angle(pts)
    ring = (rho >= 0.35) & (rho <= 1.5)
    spread = len(np.unique((ang[ring] // 45).astype(int)))   # octants covered
    return ring.mean() >= 0.6 and spread >= 5


def _face_from_marks(ink):
    """No usable outline: estimate the clock centre from the small marks (numbers)."""
    pts = _small_mark_centres(ink)
    if len(pts) < 6:
        return None
    A = np.c_[2 * pts, np.ones(len(pts))]
    bvec = (pts ** 2).sum(1)
    cx, cy, c = np.linalg.lstsq(A, bvec, rcond=None)[0]
    r = np.sqrt(max(c + cx * cx + cy * cy, 1e-6))
    R = r / 0.8                     # numbers usually sit at ~80% of the radius
    return Face((cx, cy), (2 * R, 2 * R), 0.0)


# --------------------------------------------------------------------------
# 6. Main scoring pipeline
# --------------------------------------------------------------------------
def score_clock_drawing(ink):
    face_info = find_clock_face(ink)
    contour_score, contour_info = score_contour_face(face_info, ink.shape)
    face = face_info["face"] if face_info is not None else None
    if face is not None and face.R < 0.1 * min(ink.shape):
        face = None
    if face is not None and contour_score == 0 and not _marks_fit_face(ink, face):
        # the biggest stroke is not a clock face (e.g. no circle was drawn and
        # the hands are the biggest stroke): locate the clock from the numbers
        face, face_info = None, None
    if face is None:
        face = _face_from_marks(ink)
    sw = stroke_width(ink) if ink.any() else 1.0
    if face is None:
        hands, marks = [], []
        hands_score, hands_info = score_hands_face([], face_found=False)
        numbers_score, numbers_info = 0, {"reason": "no clock face / centre found"}
    else:
        hands, _ = detect_hands(ink, face)
        marks = find_number_marks(ink, face_info, face, hands, sw)
        numbers_score, numbers_info = score_numbers_face(marks, face, hands, ink, sw)
        # if the numbers are clearly readable, judge the hands against them
        rot = numbers_info.get("rotation_deg", 0) if numbers_info.get("confirmed", 0) >= 8 else 0
        hands_score, hands_info = score_hands_face(hands, numbers_rotation=rot)
    criteria = {"contour": contour_score, "numbers": numbers_score, "hands": hands_score}
    return {
        "score": sum(criteria.values()), "max_score": 3, "criteria": criteria,
        "contour": {"score": contour_score, **contour_info},
        "numbers": {"score": numbers_score, **numbers_info},
        "hands": {"score": hands_score, **hands_info},
        "_face": face, "_hands": hands, "_marks": marks,
    }


def score_clock(image_path):
    img = cv2.imread(image_path)
    if img is None:
        z = {"score": 0, "reason": f"could not read image {image_path}"}
        return {"score": 0, "max_score": 3, "criteria": {"contour": 0, "numbers": 0, "hands": 0},
                "contour": dict(z), "numbers": dict(z), "hands": dict(z)}
    return score_clock_image(img)


def score_clock_image(img_bgr):
    """
    Photo (BGR array) -> full clock result. Same path as a captured photo.

    A patient may hold the paper sideways or upside down. The first try is the
    photo as taken. If the numbers do not read as a clock, the paper is turned
    90, 180 and 270 degrees and the turn that makes the most numbers read
    correctly is kept -- the way a person turns a page until the 12 is at the top.
    """
    best = _score_orientation(img_bgr, 0)
    if best["criteria"]["numbers"] == 0:
        for quarter_turns, rotate_code in ((1, cv2.ROTATE_90_CLOCKWISE),
                                           (2, cv2.ROTATE_180),
                                           (3, cv2.ROTATE_90_COUNTERCLOCKWISE)):
            cand = _score_orientation(cv2.rotate(img_bgr, rotate_code), quarter_turns * 90)
            if _judge_key(cand) > _judge_key(best):
                best = cand
    if best.get("_rotation_applied_deg", 0):
        print(f"[clock] Paper was turned {best['_rotation_applied_deg']} degrees -- auto-corrected before scoring")
    return best


def _clock_closure(mask):
    """How round and closed the biggest outline in the mask is (1.0 = a full circle)."""
    face_info = find_clock_face(mask)
    if face_info is None:
        return 0.0
    face = face_info["face"]
    return cv2.contourArea(face_info["outer"]) / (np.pi * face.a * face.b + 1e-9)


def _paper_prep(img_bgr):
    prep = prepare_drawing(img_bgr, max_side=1600)
    return {"bgr": prep["bgr"], "gray": prep["gray"], "ink": prep["ink"],
            "paper_found": prep["paper_found"], "cut_off": False}


def _pen_prep(img_bgr):
    """
    Photo -> the pen-ink cluster that is the clock. The paper outline is not
    needed: a blue clipboard, a hand or a shirt is ignored by colour, and the
    clock is the cluster whose outline is the most closed circle.
    """
    img = _photo_to_width(img_bgr, width=1600)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink_all = find_pen_ink(img)
    cands = drawing_candidates(ink_all, top=60, min_px=25)
    big = [m for m in cands if np.count_nonzero(m) >= 200]
    scored = [(_clock_closure(m), int(np.count_nonzero(m)), m) for m in big]
    if not scored or max(s[0] for s in scored) < 0.6:
        # no closed circle drawn: use the paper-based pipeline as before
        return _paper_prep(img_bgr)
    _, _, outline = max(scored, key=lambda s: (min(s[0], 0.6), s[1]))
    ink = outline.copy()
    # The hands are separate pen clusters (they do not touch the rim), so add
    # every other cluster that lies inside the clock face: hands, numbers, dots.
    face_info = find_clock_face(outline)
    if face_info is not None:
        face = face_info["face"]
        cx, cy = face.center
        yy, xx = np.mgrid[0:gray.shape[0], 0:gray.shape[1]]
        disc = ((xx - cx) ** 2 + (yy - cy) ** 2) <= (1.15 * max(face.a, face.b)) ** 2
        for m in cands:
            if m is outline:
                continue
            n = np.count_nonzero(m)
            if n and np.count_nonzero(m & disc.astype(np.uint8) * 255) / n >= 0.8:
                ink = cv2.bitwise_or(ink, m)
    # a little growth so thin strokes of a number are not cut by the crop mask
    ink = cv2.dilate(ink, np.ones((5, 5), np.uint8))
    return {"bgr": img, "gray": gray, "ink": ink, "paper_found": True,
            "cut_off": _touches_border(outline)}


def _score_orientation(img_bgr, rotation_deg):
    prep = _zoom_to_clock(_pen_prep(img_bgr))
    result = score_clock_drawing(prep["ink"])
    if result["contour"]["score"] == 0 and prep.get("cut_off"):
        result["contour"]["reason"] = ("the clock runs off the edge of the photo -- "
                                       "hold the paper so the whole clock is in view")
    result["_prep"] = prep
    result["_rotation_applied_deg"] = rotation_deg
    return result


def _judge_key(result):
    """Higher = the drawing reads more like a clock in this orientation."""
    return (sum(result["criteria"].values()), result["numbers"].get("confirmed", 0))


def _zoom_to_clock(prep, target_radius=300):
    """
    Crop around the clock and scale it to a standard size, so a small clock
    far from the camera is read at the same detail as a big one.
    """
    face_info = find_clock_face(prep["ink"])
    if face_info is None:
        return prep
    face = face_info["face"]
    closure = cv2.contourArea(face_info["outer"]) / (np.pi * face.a * face.b + 1e-9)
    if closure < 0.6 or not _marks_fit_face(prep["ink"], face):
        return prep          # biggest stroke isn't a clock outline: don't zoom on it
    R = max(face.a, 1.0)
    cx, cy = face.center
    h, w = prep["gray"].shape
    half = 1.7 * R
    x0, x1 = int(max(0, cx - half)), int(min(w, cx + half))
    y0, y1 = int(max(0, cy - half)), int(min(h, cy + half))
    if x1 - x0 < 20 or y1 - y0 < 20:
        return prep
    scale = min(4.0, target_radius / R)
    size = (int((x1 - x0) * scale), int((y1 - y0) * scale))
    bgr = cv2.resize(prep["bgr"][y0:y1, x0:x1], size, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    ink = ink_mask_from_gray(gray)
    # keep only ink that was on the paper in the original mask
    keep = cv2.resize(cv2.dilate(prep["ink"][y0:y1, x0:x1], np.ones((5, 5), np.uint8)), size,
                      interpolation=cv2.INTER_NEAREST)
    ink[keep == 0] = 0
    return {"bgr": bgr, "gray": gray, "ink": ink, "paper_found": prep["paper_found"]}


def annotate_clock(result, out_path):
    prep = result.get("_prep")
    img = prep["bgr"].copy()
    face = result.get("_face")
    if face is not None:
        c = tuple(int(v) for v in face.center)
        cv2.ellipse(img, (c, (int(2 * face.a), int(2 * face.b)), float(np.degrees(face.theta))),
                    (0, 170, 0) if result["criteria"]["contour"] else (0, 0, 220), 2)
        for hd in result.get("_hands", []):
            cv2.line(img, c, tuple(int(v) for v in hd["tip"]), (255, 120, 0), 3)
        slots = result["numbers"].get("slots", {})
        for m in result.get("_marks", []):
            x, y, w, h = [int(v) for v in m["box"]]
            cv2.rectangle(img, (x, y), (x + w, y + h), (200, 0, 200), 2)
        for n, v in slots.items():
            if v.get("status") in (None, "missing"):
                continue
            ang = np.radians(clock_angle_for_hour_position(n))
            p = face.center + 1.12 * face.R * np.array([np.sin(ang), -np.cos(ang)])
            col = {"confirmed": (0, 150, 0), "unclear": (0, 140, 255), "contradiction": (0, 0, 220)}[v["status"]]
            cv2.putText(img, str(v["read"]), tuple(int(t) for t in p), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
    cv2.imwrite(out_path, img)
    return out_path


def run_task3(cam_index=0, show_result=True):
    print("=" * 60)
    print("MoCA Task 3: Clock Drawing Test")
    print("=" * 60)
    photo_path = capture_with_countdown(hold_seconds=10, cam_index=cam_index)
    if photo_path is None:
        print("Cancelled.")
        return None
    return score_and_report(photo_path, show_result=show_result)


def score_and_report(photo_path, show_result=True):
    result = score_clock(photo_path)
    annotated = None
    if result.get("_prep") is not None:
        annotated = annotate_clock(result, str(get_session_dir() / "clock_annotated.png"))
    c = result["criteria"]

    print("\n--- RESULT ---")
    print(f"Contour: {c['contour']}/1  ({result['contour'].get('reason', '')})")
    print(f"Numbers: {c['numbers']}/1  ({result['numbers'].get('reason', '')})")
    print(f"Hands:   {c['hands']}/1  ({result['hands'].get('reason', '')})")
    print(f"SCORE: {result['score']} / {result['max_score']}")

    details = {k: {kk: vv for kk, vv in result[k].items()} for k in ("contour", "numbers", "hands")}
    std = make_task_result(
        TASK_ID, result["score"], criteria=c,
        reason="; ".join(f"{k}: {result[k].get('reason', '')}" for k in ("contour", "numbers", "hands")),
        details=details, evidence_files=[p for p in (photo_path, annotated) if p])
    saved = save_task_result(std)
    print(f"Result saved to: {saved}")
    if show_result and annotated:
        show_result_window("MoCA Task 3 - Result", cv2.imread(annotated),
                           [f"Task 3 (clock) SCORE: {result['score']} / 3",
                            f"Contour {c['contour']}/1   Numbers {c['numbers']}/1   Hands {c['hands']}/1"],
                           passed=result["score"] == 3)
    return std


if __name__ == "__main__":
    run_task3()
