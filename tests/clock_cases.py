"""Clock test cases: (name, expected criteria dict, image)."""

import numpy as np
import cv2

from synth import INK, blank_paper, camera_photo, hand_line

# Fonts NOT used to train the back-up digit reader (tools/train_digit_model.py)
FONTS = [cv2.FONT_HERSHEY_TRIPLEX, cv2.FONT_HERSHEY_COMPLEX_SMALL]

# Real handwritten digits (MNIST samples bundled with mlxtend, the part NOT used
# for training the back-up reader). Test-only dependency; falls back to fonts.
try:
    from mlxtend.data import mnist_data
    _X, _Y = mnist_data()
    _perm = np.random.default_rng(0).permutation(len(_Y))
    _X, _Y = _X[_perm][4400:], _Y[_perm][4400:]
    HAND = {d: [x.reshape(28, 28) for x, y in zip(_X, _Y) if y == d] for d in range(10)}
except Exception:  # pragma: no cover
    HAND = None
C = np.array([450.0, 450.0])
R = 300.0


def draw_outline(img, rng, kind="circle", thickness=4):
    if kind == "none":
        return
    t = np.linspace(0, 2 * np.pi, 400, endpoint=False)
    if kind in ("circle", "shaky", "oval", "open", "egg"):
        r = np.full_like(t, R)
        if kind == "shaky":   # tremor: small fast wobble + a slight lumpy shape
            r += R * (0.02 * np.sin(t * rng.uniform(18, 30) + rng.uniform(0, 6))
                      + 0.025 * np.sin(2 * t + rng.uniform(0, 6))
                      + 0.01 * rng.normal(size=t.size))
        if kind == "egg":
            r += R * 0.05 * np.sin(t + rng.uniform(0, 6))
        ax, ay = (1.0, 0.86) if kind == "oval" else (1.0, 1.0)
        pts = np.c_[C[0] + r * np.cos(t) * ax, C[1] + r * np.sin(t) * ay]
        if kind == "open":
            start = rng.uniform(0, 2 * np.pi)
            keep = ((t - start) % (2 * np.pi)) < np.radians(260)
            pts = pts[keep]
            order = np.argsort((t[keep] - start) % (2 * np.pi))
            pts = pts[order]
            cv2.polylines(img, [pts.astype(np.int32).reshape(-1, 1, 2)], False, INK, thickness, cv2.LINE_AA)
            return
        cv2.polylines(img, [pts.astype(np.int32).reshape(-1, 1, 2)], True, INK, thickness, cv2.LINE_AA)
    elif kind == "square":
        s = R * 0.92
        corners = [C + (-s, -s), C + (s, -s), C + (s, s), C + (-s, s)]
        for i in range(4):
            hand_line(img, corners[i], corners[(i + 1) % 4], rng, thickness=thickness)
    elif kind == "triangle":
        corners = [C + R * np.array([np.sin(a), -np.cos(a)]) for a in np.radians([0, 120, 240])]
        for i in range(3):
            hand_line(img, corners[i], corners[(i + 1) % 3], rng, thickness=thickness)


def put_number(img, rng, text, pos, height=40, thickness=3):
    if HAND is not None and rng.random() < 0.5:
        return put_handwritten(img, rng, text, pos, height)
    font = FONTS[rng.integers(len(FONTS))]
    scale = cv2.getFontScaleFromHeight(font, int(height), thickness)
    (w, h), _ = cv2.getTextSize(text, font, scale, thickness)
    tile = np.zeros((h * 3, w + h * 2), np.uint8)
    cv2.putText(tile, text, (h, 2 * h), font, scale, 255, thickness, cv2.LINE_AA)
    M = cv2.getRotationMatrix2D((tile.shape[1] / 2, tile.shape[0] / 2), rng.uniform(-10, 10), 1.0)
    tile = cv2.warpAffine(tile, M, (tile.shape[1], tile.shape[0]))
    x0 = int(pos[0] - tile.shape[1] / 2)
    y0 = int(pos[1] - tile.shape[0] / 2)
    roi = img[y0:y0 + tile.shape[0], x0:x0 + tile.shape[1]]
    a = (tile[:roi.shape[0], :roi.shape[1]] / 255.0)[..., None]
    roi[:] = (roi * (1 - a) + np.array(INK) * a).astype(np.uint8)


def put_handwritten(img, rng, text, pos, height=40):
    """Paste real handwritten MNIST digits side by side at pos."""
    tiles = []
    for ch in text:
        x = HAND[int(ch)][rng.integers(len(HAND[int(ch)]))].astype(np.uint8)
        ys, xs = np.nonzero(x > 60)
        x = x[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        s = height / x.shape[0]
        tiles.append(cv2.resize(x, (max(1, int(x.shape[1] * s)), int(height)), interpolation=cv2.INTER_CUBIC))
    gap = int(height * 0.15)
    w = sum(t.shape[1] for t in tiles) + gap * (len(tiles) - 1)
    tile = np.zeros((int(height), w), np.uint8)
    x0 = 0
    for t in tiles:
        tile[:, x0:x0 + t.shape[1]] = np.maximum(tile[:, x0:x0 + t.shape[1]], t)
        x0 += t.shape[1] + gap
    tile = ((tile > 110) * 255).astype(np.uint8)
    y0, xs0 = int(pos[1] - tile.shape[0] / 2), int(pos[0] - tile.shape[1] / 2)
    roi = img[y0:y0 + tile.shape[0], xs0:xs0 + tile.shape[1]]
    a = (tile[:roi.shape[0], :roi.shape[1]] / 255.0)[..., None]
    roi[:] = (roi * (1 - a) + np.array(INK) * a).astype(np.uint8)


def draw_numbers(img, rng, kind="correct", radius_frac=0.8):
    if kind == "none":
        return
    order = list(range(1, 13))
    angles = {n: (n % 12) * 30.0 for n in order}
    if kind == "ccw":
        angles = {n: (-(n % 12) * 30.0) % 360 for n in order}
    elif kind == "shuffled":
        perm = rng.permutation(order)
        angles = {n: (int(p) % 12) * 30.0 for n, p in zip(order, perm)}
    elif kind == "crowded":      # all squeezed into the right half
        angles = {n: 15 + (n - 1) * 14.0 for n in order}
    elif kind == "rot20":        # whole ring turned 20 deg (still acceptable)
        angles = {n: ((n % 12) * 30.0 + 20) % 360 for n in order}
    elif kind == "shift1":       # every number one position too far (wrong)
        angles = {n: ((n + 1) % 12) * 30.0 for n in order}
    elif kind == "swap12":
        angles[1], angles[2] = angles[2], angles[1]
    items = [(n, angles[n]) for n in order]
    if kind == "missing3":
        items = [(n, a) for n, a in items if n not in (3, 7, 10)]
    if kind == "only4":
        items = [(n, a) for n, a in items if n in (12, 3, 6, 9)]
    if kind == "extra":
        items.append((13, 45.0))
    for n, a in items:
        ang = np.radians(a + rng.uniform(-5, 5))
        rr = R * (radius_frac + rng.uniform(-0.04, 0.04))
        pos = C + rr * np.array([np.sin(ang), -np.cos(ang)])
        put_number(img, rng, str(n), pos, height=rng.uniform(34, 46))


def draw_hands(img, rng, hands, arrow=False, thickness=4):
    """hands: list of (clock angle deg, length as fraction of R)."""
    for ang, L in hands:
        a = np.radians(ang + rng.uniform(-3, 3))
        tip = C + L * R * np.array([np.sin(a), -np.cos(a)])
        start = C + rng.uniform(-4, 4, 2)
        hand_line(img, start, tip, rng, thickness=thickness)
        if arrow:
            back = (C - tip) / np.linalg.norm(C - tip) * 22
            for rot in (25, -25):
                th = np.radians(rot)
                v = np.array([back[0] * np.cos(th) - back[1] * np.sin(th),
                              back[0] * np.sin(th) + back[1] * np.cos(th)])
                hand_line(img, tip, tip + v, rng, thickness=thickness, wobble=0.3)


RIGHT_TIME = [(335, 0.45), (60, 0.72)]


def clock(rng, outline="circle", numbers="correct", hands=RIGHT_TIME, arrow=False):
    img = blank_paper()
    draw_outline(img, rng, outline)
    draw_numbers(img, rng, numbers)
    draw_hands(img, rng, hands, arrow=arrow)
    return img


def E(c, n, h):
    return {"contour": c, "numbers": n, "hands": h}


def clock_cases(seed=0):
    rng = np.random.default_rng(seed)
    cs = []
    # the five examples from the brief
    cs.append(("ex1 all correct", E(1, 1, 1), clock(rng)))
    cs.append(("ex2 shaky circle, wrong time", E(1, 1, 0), clock(rng, "shaky", hands=[(300, 0.45), (60, 0.72)])))
    cs.append(("ex3 numbers wrong, time right", E(1, 0, 1), clock(rng, numbers="ccw")))
    cs.append(("ex4 square outline, rest right", E(0, 1, 1), clock(rng, "square")))
    cs.append(("ex5 all wrong", E(0, 0, 0), clock(rng, "open", "crowded", hands=[(90, 0.7)])))
    # contour variations
    cs.append(("shaky circle", E(1, 1, 1), clock(rng, "shaky")))
    cs.append(("slightly oval", E(1, 1, 1), clock(rng, "oval")))
    cs.append(("egg-ish circle", E(1, 1, 1), clock(rng, "egg")))
    cs.append(("open arc (not closed)", E(0, 1, 1), clock(rng, "open")))
    cs.append(("triangle outline", E(0, 1, 1), clock(rng, "triangle")))
    cs.append(("no outline", E(0, 1, 1), clock(rng, "none")))
    # numbers variations
    cs.append(("numbers missing 3", E(1, 0, 1), clock(rng, numbers="missing3")))
    cs.append(("only 12-3-6-9", E(1, 0, 1), clock(rng, numbers="only4")))
    cs.append(("numbers crowded right half", E(1, 0, 1), clock(rng, numbers="crowded")))
    cs.append(("numbers shuffled", E(1, 0, 1), clock(rng, numbers="shuffled")))
    cs.append(("1 and 2 swapped", E(1, 0, 1), clock(rng, numbers="swap12")))
    cs.append(("extra number 13", E(1, 0, 1), clock(rng, numbers="extra")))
    cs.append(("number ring turned 20deg", E(1, 1, 1),
               clock(rng, numbers="rot20", hands=[(355, 0.45), (80, 0.72)])))
    cs.append(("numbers shifted one place", E(1, 0, 1), clock(rng, numbers="shift1")))
    cs.append(("no numbers", E(1, 0, 1), clock(rng, numbers="none")))
    # hands variations
    cs.append(("hands with arrowheads", E(1, 1, 1), clock(rng, arrow=True)))
    cs.append(("10:10 (hour at 10)", E(1, 1, 0), clock(rng, hands=[(305, 0.45), (60, 0.72)])))
    cs.append(("hands swapped (1:55)", E(1, 1, 0), clock(rng, hands=[(335, 0.72), (60, 0.45)])))
    cs.append(("equal length hands", E(1, 1, 0), clock(rng, hands=[(335, 0.6), (60, 0.6)])))
    cs.append(("one hand only", E(1, 1, 0), clock(rng, hands=[(60, 0.72)])))
    cs.append(("no hands", E(1, 1, 0), clock(rng, hands=[])))
    cs.append(("three hands", E(1, 1, 0), clock(rng, hands=RIGHT_TIME + [(180, 0.6)])))
    cs.append(("2:55 (reversed)", E(1, 1, 0), clock(rng, hands=[(60, 0.45), (330, 0.72)])))
    cs.append(("minute at 3 (11:15)", E(1, 1, 0), clock(rng, hands=[(337, 0.45), (90, 0.72)])))
    img = blank_paper()
    for _ in range(10):
        hand_line(img, rng.uniform(150, 750, 2), rng.uniform(150, 750, 2), rng, thickness=4)
    cs.append(("random scribble", E(0, 0, 0), img))
    cs.append(("blank page", E(0, 0, 0), blank_paper()))
    for i in range(2):
        cs.append((f"camera photo correct #{i}", E(1, 1, 1), camera_photo(clock(rng, "shaky"), rng)))
    return cs
