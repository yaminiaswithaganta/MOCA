"""
Shared helpers for the three MoCA task scripts
==============================================

Kept deliberately small. Everything here is used by more than one task:

* result format + saving (so every task reports its score the same way and
  `run_moca.py` can add them up to the final /5),
* camera-frame helpers used by Task 2 and Task 3 (find the sheet of paper,
  straighten it, extract the pen strokes, auto-start the countdown when the
  paper is held steady),
* a small window that shows the score as soon as a task is scored.

Each task script still runs on its own: `python task2_cube_copy.py` works as
before, it just imports this file from the same folder.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import numpy as np

try:  # OpenCV is needed by Task 2 / Task 3 helpers only
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


PROJECT_DIR = Path(__file__).resolve().parent
RESULTS_ROOT = Path(os.environ.get("MOCA_RESULTS_DIR") or PROJECT_DIR / "results")
# Fixed maximum per task -- the scoring can never exceed these.
TASK_MAX_SCORES = {
    "task1_trail_making": 1,
    "task2_cube_copy": 1,
    "task3_clock_draw": 3,
    "task4_naming": 3,
    "task5_memory": 0,      # learning trials: recorded, not scored (MoCA "no points")
    "task6_digit_span": 2,  # digits forward 1 + backward 1
    "task7_letters": 1,     # letter A detection 1
    "task8_serial7s": 3,    # serial 7s subtraction 3
    "task9_sentence_repetition": 2,  # two sentences, 1 each
    "task10_fluency": 1,             # 11+ different F-words in one minute
    "task11_abstraction": 2,         # train-bicycle 1 + watch-ruler 1
    "task12_delayed_recall": 5,      # the 5 Task 5 words, 1 each
    "task13_orientation": 6,         # date, month, year, day, place, city
}
# Maximum per criterion (default 1)
CRITERIA_MAX = {
    "task6_digit_span": {"digits_forward": 1, "digits_backward": 1},
    "task7_letters": {"letters_a": 1},
    "task8_serial7s": {"serial7": 3},
    "task9_sentence_repetition": {"sentence_1": 1, "sentence_2": 1},
    "task10_fluency": {"fluency": 1},
    "task11_abstraction": {"train_bicycle": 1, "watch_ruler": 1},
    "task12_delayed_recall": {"face": 1, "velvet": 1, "church": 1, "daisy": 1, "red": 1},
    "task13_orientation": {"date": 1, "month": 1, "year": 1, "day": 1, "place": 1, "city": 1},
}
# MoCA sections (the MoCA sheet's point boxes)
SECTIONS = {
    "visuospatial_executive": {"tasks": ["task1_trail_making", "task2_cube_copy",
                                         "task3_clock_draw"], "max": 5},
    "naming": {"tasks": ["task4_naming"], "max": 3},
    "memory": {"tasks": ["task5_memory"], "max": 0},
    "attention": {"tasks": ["task6_digit_span", "task7_letters", "task8_serial7s"], "max": 6},
    "language": {"tasks": ["task9_sentence_repetition", "task10_fluency"], "max": 3},
    "abstraction": {"tasks": ["task11_abstraction"], "max": 2},
    "delayed_recall": {"tasks": ["task12_delayed_recall"], "max": 5},
    "orientation": {"tasks": ["task13_orientation"], "max": 6},
}
MAX_TOTAL_SCORE = sum(TASK_MAX_SCORES.values())          # 30 with all 12 tasks
VISUOSPATIAL_MAX = SECTIONS["visuospatial_executive"]["max"]
assert sum(TASK_MAX_SCORES[t] for t in SECTIONS["visuospatial_executive"]["tasks"]) == 5
assert sum(sec["max"] for sec in SECTIONS.values()) == MAX_TOTAL_SCORE

DEFAULT_CRITERIA = {
    "task3_clock_draw": {"contour": 0, "numbers": 0, "hands": 0},
    "task4_naming": {"lion": 0, "rhino": 0, "camel": 0},
    "task6_digit_span": {"digits_forward": 0, "digits_backward": 0},
    "task7_letters": {"letters_a": 0},
    "task8_serial7s": {"serial7": 0},
    "task9_sentence_repetition": {"sentence_1": 0, "sentence_2": 0},
    "task10_fluency": {"fluency": 0},
    "task11_abstraction": {"train_bicycle": 0, "watch_ruler": 0},
    "task12_delayed_recall": {"face": 0, "velvet": 0, "church": 0, "daisy": 0, "red": 0},
    "task13_orientation": {"date": 0, "month": 0, "year": 0, "day": 0, "place": 0, "city": 0},
}


# --------------------------------------------------------------------------
# 1. Result format + saving
# --------------------------------------------------------------------------
def get_session_dir():
    """
    Folder where this session's photos, audio and JSON results are saved.
    `run_moca.py` sets MOCA_SESSION_DIR so all three tasks share one folder;
    a task run on its own gets a fresh time-stamped folder.
    """
    existing = os.environ.get("MOCA_SESSION_DIR")
    if existing:
        path = Path(existing)
    else:
        path = RESULTS_ROOT / datetime.now().strftime("session_%Y%m%d_%H%M%S")
        os.environ["MOCA_SESSION_DIR"] = str(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _to_jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return round(float(obj), 4)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return _to_jsonable(obj.tolist())
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, float):
        return round(obj, 4)
    return obj


def make_task_result(task_id, score, criteria=None, reason="", details=None,
                     evidence_files=None, completed=True):
    """
    Build the standard result dict every task returns.

    * `score` is forced to an int in [0, max_score].
    * For Task 3, `criteria` is {"contour": 0/1, "numbers": 0/1, "hands": 0/1}
      and the score MUST equal their sum.
    """
    max_score = TASK_MAX_SCORES[task_id]
    score = int(score)
    if not 0 <= score <= max_score:
        raise ValueError(f"{task_id}: score {score} outside 0..{max_score}")
    if criteria is not None:
        criteria = {k: int(v) for k, v in criteria.items()}
        cmax = CRITERIA_MAX.get(task_id, {})
        if any(not 0 <= v <= cmax.get(k, 1) for k, v in criteria.items()):
            raise ValueError(f"{task_id}: criterion outside its allowed range: {criteria}")
        if sum(criteria.values()) != score:
            raise ValueError(f"{task_id}: criteria {criteria} do not add up to {score}")
    elif max_score == 1 and score not in (0, 1):
        raise ValueError(f"{task_id}: score must be 0 or 1")
    return {
        "task": task_id,
        "score": score,
        "max_score": max_score,
        "criteria": criteria,
        "completed": bool(completed),
        "reason": reason,
        "details": _to_jsonable(details or {}),
        "evidence_files": [str(p) for p in (evidence_files or [])],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


def save_task_result(result, session_dir=None):
    """Write <session>/<task>.json and return its path."""
    session_dir = Path(session_dir) if session_dir else get_session_dir()
    path = session_dir / f"{result['task']}.json"
    path.write_text(json.dumps(_to_jsonable(result), indent=2))
    return path


def build_final_report(results, tasks=None):
    """
    Combine task results into the final report. `tasks` = the task ids that
    were part of this session (default: all). Missing / cancelled tasks
    count as 0 (listed as not completed).
    """
    tasks = list(tasks or TASK_MAX_SCORES)
    report = {"tasks": {}, "sections": {}, "total": 0,
              "max_total": sum(TASK_MAX_SCORES[t] for t in tasks)}
    for task_id in tasks:
        r = results.get(task_id)
        if r is None:
            r = make_task_result(task_id, 0, reason="task not completed", completed=False,
                                 criteria=DEFAULT_CRITERIA.get(task_id))
        report["tasks"][task_id] = r
        report["total"] += r["score"]
    assert 0 <= report["total"] <= report["max_total"]
    for name, sec in SECTIONS.items():
        ids = [t for t in sec["tasks"] if t in report["tasks"]]
        if ids:
            report["sections"][name] = {
                "score": sum(report["tasks"][t]["score"] for t in ids),
                "max": sum(TASK_MAX_SCORES[t] for t in ids)}
    summary = {}
    for t, r in report["tasks"].items():
        if t == "task5_memory":
            summary[t] = {f"trial{tr['trial']}": tr["recalled"]
                          for tr in r.get("details", {}).get("trials", [])}
        else:
            summary[t] = r["criteria"] if r.get("criteria") else r["score"]
    summary["total"] = report["total"]
    summary["max_total"] = report["max_total"]
    report["summary"] = summary
    return report


# --------------------------------------------------------------------------
# 2. Image helpers (Task 2 + Task 3)
# --------------------------------------------------------------------------
def _order_quad(pts):
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def find_paper_quad(frame_bgr, min_area_frac=0.12, strict=True):
    """
    Find the sheet of paper (largest bright 4-sided region) in a camera frame.
    Returns 4 ordered corners (tl, tr, br, bl) or None if no paper is found
    (e.g. the paper fills the whole frame).
    """
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if frame_bgr.ndim == 3 else frame_bgr
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (7, 7), 0)
    _, bright = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area < min_area_frac * h * w or area > 0.97 * h * w:
        return None
    # Paper touching the frame border on most sides == fills the frame.
    x, y, bw, bh = cv2.boundingRect(c)
    if bw > 0.97 * w and bh > 0.97 * h:
        return None
    hull = cv2.convexHull(c)
    peri = cv2.arcLength(hull, True)
    for eps in (0.015, 0.02, 0.03):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            quad = _order_quad(approx)
            return quad if (not strict or _plausible_sheet(quad, c)) else None
    if not strict:   # good enough to know "a sheet is being held up"
        return _order_quad(cv2.boxPoints(cv2.minAreaRect(hull)))
    # Not clearly a flat 4-cornered sheet (bent paper, white wall behind it,
    # hand covering a corner): don't warp -- a wrong warp distorts the drawing.
    return None


def _plausible_sheet(quad, contour):
    """A real, flat sheet: corners roughly square and the bright area fills the quad."""
    q = quad.astype(np.float64)
    for i in range(4):
        a, b, c = q[i - 1], q[i], q[(i + 1) % 4]
        v1, v2 = a - b, c - b
        cosang = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
        if not 60 <= np.degrees(np.arccos(np.clip(cosang, -1, 1))) <= 120:
            return False
    quad_area = cv2.contourArea(q.astype(np.float32))
    return quad_area > 0 and cv2.contourArea(contour) / quad_area >= 0.92


def warp_paper(frame_bgr, quad, max_side=1000):
    tl, tr, br, bl = quad
    wid = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    hei = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    scale = max_side / max(wid, hei)
    W, H = int(round(wid * scale)), int(round(hei * scale))
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(quad.astype(np.float32), dst)
    return cv2.warpPerspective(frame_bgr, M, (W, H), borderValue=(255, 255, 255))


def ink_mask_from_gray(gray):
    """
    Binary mask (uint8 0/255) of the pen strokes on a sheet of paper.
    Uses the local paper brightness as reference, so uneven lighting,
    shadows and pencil vs. marker are handled.
    """
    h, w = gray.shape
    k = max(15, int(min(h, w) * 0.03)) | 1
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    background = cv2.GaussianBlur(background, (k, k), 0).astype(np.float32)
    diff = background - gray.astype(np.float32)
    ink = (diff > np.maximum(28.0, 0.20 * background)).astype(np.uint8) * 255
    # remove isolated specks (sensor noise, paper texture)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    min_area = max(6, int(h * w * 0.00001))
    keep = np.zeros(n, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    return (keep[labels] * 255).astype(np.uint8)


def prepare_drawing(image_bgr, max_side=1000, border_frac=0.03):
    """
    Camera photo -> straightened paper image + ink mask.
    Returns dict(bgr, gray, ink, paper_found).
    """
    quad = find_paper_quad(image_bgr)
    paper_mask = None
    if quad is not None:
        paper = warp_paper(image_bgr, quad, max_side=max_side)
    else:
        h, w = image_bgr.shape[:2]
        s = max_side / max(h, w)
        paper = cv2.resize(image_bgr, (int(w * s), int(h * s)),
                           interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
        # no clean sheet outline: don't warp, but ignore everything that is
        # not on the (bright) paper -- walls, blinds, hands, background
        paper_mask = _paper_region_mask(paper)
    gray = cv2.cvtColor(paper, cv2.COLOR_BGR2GRAY)
    ink = ink_mask_from_gray(gray)
    if paper_mask is not None:
        ink[paper_mask == 0] = 0
    # blank out a thin border so paper edges / fingers at the edge are ignored
    h, w = ink.shape
    b = int(min(h, w) * border_frac)
    if b > 0:
        ink[:b, :] = 0
        ink[-b:, :] = 0
        ink[:, :b] = 0
        ink[:, -b:] = 0
    return {"bgr": paper, "gray": gray, "ink": ink, "paper_found": quad is not None}


def _paper_region_mask(bgr):
    """Filled mask of the largest bright, low-colour region (the sheet), slightly shrunk."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (9, 9), 0)
    _, bright = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright[hsv[..., 1] > 60] = 0          # coloured things (skin, walls) are not paper
    k = max(5, int(min(gray.shape) * 0.02)) | 1
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.1 * gray.size:
        return None
    mask = np.zeros_like(gray)
    cv2.drawContours(mask, [c], -1, 255, -1)       # fill: pen strokes inside are kept
    return cv2.erode(mask, np.ones((k, k), np.uint8))


def skeletonize_mask(mask):
    """1-pixel-wide centre lines of the pen strokes (uint8 0/255)."""
    from skimage.morphology import skeletonize
    return (skeletonize(mask > 0) * 255).astype(np.uint8)


def stroke_width(mask):
    """Median pen-stroke width in pixels."""
    if not np.any(mask):
        return 1.0
    dist = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 3)
    skel = skeletonize_mask(mask) > 0
    vals = dist[skel]
    return float(max(1.0, 2.0 * np.median(vals))) if vals.size else 1.0


# ---- straight-line helpers (Hough fragments -> one segment per pen line) ----
def seg_angle(seg):
    x1, y1, x2, y2 = seg
    return np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180.0


def angle_diff180(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def merge_line_segments(segs, size, tol, ink=None):
    """
    Join Hough fragments that belong to the same drawn pen line.
    `tol` needs keys merge_angle_deg, merge_offset_frac, merge_gap_frac,
    merge_gap_max_frac, gap_ink_coverage (fractions of `size`).
    Returns a list of segments [x1, y1, x2, y2] (float).
    """
    segs = [np.asarray(s, dtype=np.float64) for s in segs]
    for _ in range(3):
        n = len(segs)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(n):
            for j in range(i + 1, n):
                if _segments_same_edge(segs[i], segs[j], size, tol, ink):
                    parent[find(i)] = find(j)
        groups = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(segs[i])
        merged = [_fit_group(g) for g in groups.values()]
        if len(merged) == len(segs):
            break
        segs = merged
    return segs


def _ink_coverage(ink, p, q):
    """Fraction of points on the straight path p->q that lie on pen ink."""
    n = max(2, int(np.linalg.norm(q - p) / 2))
    t = np.linspace(0, 1, n)[:, None]
    pts = np.round(p[None] * (1 - t) + q[None] * t).astype(int)
    h, w = ink.shape
    pts[:, 0] = pts[:, 0].clip(0, w - 1)
    pts[:, 1] = pts[:, 1].clip(0, h - 1)
    return float((ink[pts[:, 1], pts[:, 0]] > 0).mean())


def _segments_same_edge(a, b, size, tol, ink=None):
    if angle_diff180(seg_angle(a), seg_angle(b)) > tol["merge_angle_deg"]:
        return False
    la, lb = np.hypot(*(a[2:] - a[:2])), np.hypot(*(b[2:] - b[:2]))
    ref = a if la >= lb else b
    oth = b if la >= lb else a
    p0, p1 = ref[:2], ref[2:]
    d = (p1 - p0) / max(np.linalg.norm(p1 - p0), 1e-9)
    nrm = np.array([-d[1], d[0]])
    off = max(abs(np.dot(oth[:2] - p0, nrm)), abs(np.dot(oth[2:] - p0, nrm)))
    if off > tol["merge_offset_frac"] * size:
        return False
    t = sorted([np.dot(oth[:2] - p0, d), np.dot(oth[2:] - p0, d)])
    L = np.linalg.norm(p1 - p0)
    gap = max(0.0, t[0] - L, -t[1])
    if gap <= tol["merge_gap_frac"] * size:
        return True
    # a longer gap is only bridged if the pen line really continues there
    # (Hough sometimes misses a wobbly stretch of an otherwise continuous line)
    if ink is None or gap > tol["merge_gap_max_frac"] * size:
        return False
    if t[0] > L:
        g0, g1 = p1, p0 + d * t[0]
    else:
        g0, g1 = p0 + d * t[1], p0
    return _ink_coverage(ink, g0, g1) >= tol["gap_ink_coverage"]


def _fit_group(group):
    pts, wts = [], []
    for s in group:
        L = np.hypot(*(s[2:] - s[:2])) + 1e-6
        pts += [s[:2], s[2:]]
        wts += [L, L]
    pts, wts = np.array(pts), np.array(wts)
    c = (pts * wts[:, None]).sum(0) / wts.sum()
    cov = ((pts - c) * wts[:, None]).T @ (pts - c)
    evals, evecs = np.linalg.eigh(cov)
    d = evecs[:, np.argmax(evals)]
    t = (pts - c) @ d
    return np.concatenate([c + d * t.min(), c + d * t.max()])



# --------------------------------------------------------------------------
# 3. Auto-start: detect that the paper is being held up and steady
# --------------------------------------------------------------------------
class SteadyPaperDetector:
    """
    Feed it every camera frame; `update()` returns True once a sheet of paper
    with a drawing on it has been visible and still for `steady_seconds`.
    Used to start the capture countdown automatically (SPACE still works).
    """

    def __init__(self, steady_seconds=1.5, max_motion_frac=0.02, check_every=3):
        self.steady_seconds = steady_seconds
        self.max_motion_frac = max_motion_frac
        self.check_every = check_every
        self._frame_i = 0
        self._last_quad = None
        self._steady_since = None

    def update(self, frame_bgr):
        self._frame_i += 1
        if self._frame_i % self.check_every:
            return self._is_steady()
        small = cv2.resize(frame_bgr, (320, int(320 * frame_bgr.shape[0] / frame_bgr.shape[1])))
        quad = find_paper_quad(small, min_area_frac=0.15, strict=False)
        now = time.time()
        if quad is None or not self._has_drawing(small, quad):
            self._last_quad, self._steady_since = None, None
            return False
        if self._last_quad is not None:
            motion = np.abs(quad - self._last_quad).max() / small.shape[1]
            if motion <= self.max_motion_frac:
                if self._steady_since is None:
                    self._steady_since = now
            else:
                self._steady_since = None
        self._last_quad = quad
        return self._is_steady()

    def _is_steady(self):
        return (self._steady_since is not None
                and time.time() - self._steady_since >= self.steady_seconds)

    @staticmethod
    def _has_drawing(small_bgr, quad):
        paper = warp_paper(small_bgr, quad, max_side=240)
        ink = ink_mask_from_gray(cv2.cvtColor(paper, cv2.COLOR_BGR2GRAY))
        b = 12
        ink = ink[b:-b, b:-b]
        return ink.mean() / 255.0 > 0.004


# --------------------------------------------------------------------------
# 4. Score display
# --------------------------------------------------------------------------
def show_result_window(window_name, image_bgr, lines, passed, wait_ms=8000):
    """
    Show the annotated drawing with the score written on top. Closes after
    `wait_ms` or on any key, so the next task can continue automatically.
    Returns silently if no display is available.
    """
    try:
        img = image_bgr.copy()
        h, w = img.shape[:2]
        scale = 900 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
        pad = 34 * len(lines) + 20
        canvas = np.full((img.shape[0] + pad, img.shape[1], 3), 255, np.uint8)
        canvas[pad:] = img
        color = (0, 140, 0) if passed else (0, 0, 190)
        for i, line in enumerate(lines):
            cv2.putText(canvas, line, (12, 32 + 34 * i), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8 if i == 0 else 0.6, color if i == 0 else (40, 40, 40), 2)
        cv2.imshow(window_name, canvas)
        cv2.waitKey(wait_ms)
        cv2.destroyWindow(window_name)
        cv2.waitKey(1)
    except Exception as e:  # headless / no GUI
        print(f"[display] could not show result window ({e})")


# --------------------------------------------------------------------------
# Pen-ink detection for photos. Pen strokes are dark and grey/black, so
# coloured things (a blue clipboard, skin, a shirt) are ignored; a faint
# pencil line is still caught because the threshold is relative to the local
# brightness of the paper. Photos are downscaled to this width first.
INK_PHOTO_WIDTH = 1600
INK_DIFF_ABS, INK_DIFF_REL, INK_MAX_SAT = 14.0, 0.06, 85
MIN_CLUSTER_INK_PX = 200          # clusters smaller than this are not a drawing
MAX_CANDIDATE_CLUSTERS = 6        # try the largest few clusters of pen ink


def _photo_to_width(img_bgr, width=INK_PHOTO_WIDTH):
    h, w = img_bgr.shape[:2]
    if w <= width:
        return img_bgr
    s = width / w
    return cv2.resize(img_bgr, (width, int(round(h * s))), interpolation=cv2.INTER_AREA)


def find_pen_ink(img_bgr):
    """Whole-photo pen-ink mask (uint8 0/255), coloured non-ink pixels removed."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    k = max(15, int(min(h, w) * 0.03)) | 1
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    background = cv2.GaussianBlur(background, (k, k), 0).astype(np.float32)
    diff = background - gray.astype(np.float32)
    ink = (diff > np.maximum(INK_DIFF_ABS, INK_DIFF_REL * background)).astype(np.uint8) * 255
    ink[hsv[..., 1] > INK_MAX_SAT] = 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    keep = np.zeros(n, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= 6
    return (keep[labels] * 255).astype(np.uint8)


def drawing_candidates(ink, top=MAX_CANDIDATE_CLUSTERS, min_px=MIN_CLUSTER_INK_PX):
    """The largest separate clusters of pen ink -- the cube is one of them.

    A clipboard edge, a shadow or a finger can be the single biggest cluster,
    so each of the largest clusters is offered to the cube check in turn.
    """
    h, w = ink.shape
    k = max(3, int(min(h, w) * 0.02)) | 1
    grown = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, labels = cv2.connectedComponents(grown, connectivity=8)
    if n <= 1:
        return []
    counts = np.bincount(labels[ink > 0], minlength=n)
    counts[0] = 0
    out = []
    for lab in np.argsort(-counts)[:top]:
        if counts[lab] < min_px:
            break
        out.append(((labels == lab) & (ink > 0)).astype(np.uint8) * 255)
    return out


def _touches_border(mask, margin=2):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return False
    h, w = mask.shape
    return bool(xs.min() <= margin or ys.min() <= margin or
                xs.max() >= w - 1 - margin or ys.max() >= h - 1 - margin)
