"""
Synthetic "hand-drawn" test images for the MoCA scoring tests.

Nothing here is used by the tasks themselves. It draws wobbly pen lines,
cubes and clocks on a sheet of paper and can add camera effects (paper held
at an angle over a background, uneven light, blur, sensor noise), so the
scoring can be tested for both what must PASS and what must FAIL.
"""

import numpy as np
import cv2

INK = (35, 35, 40)


def blank_paper(w=900, h=900):
    return np.full((h, w, 3), 250, np.uint8)


def hand_line(img, p, q, rng, thickness=3, wobble=1.5, color=INK, gap=0.0, overshoot=0.0):
    """Wobbly pen line from p to q (optional small gap and over/undershoot)."""
    p, q = np.array(p, float), np.array(q, float)
    d = q - p
    L = np.linalg.norm(d) + 1e-9
    u = d / L
    nrm = np.array([-u[1], u[0]])
    p = p - u * overshoot * rng.uniform(-1, 1) * L
    q = q + u * overshoot * rng.uniform(-1, 1) * L
    n = max(8, int(L / 6))
    t = np.linspace(0, 1, n)
    phase = rng.uniform(0, 2 * np.pi)
    freq = rng.uniform(1.0, 3.0)
    off = wobble * (np.sin(2 * np.pi * freq * t + phase) + 0.4 * rng.normal(size=n))
    off = np.convolve(off, np.ones(3) / 3, mode="same")
    pts = p[None] + (q - p)[None] * t[:, None] + nrm[None] * off[:, None]
    pts = pts.astype(np.int32)
    if gap > 0:
        g0 = rng.uniform(0.2, 0.7)
        keep = (t < g0) | (t > g0 + gap)
        for a, b, k1, k2 in zip(pts[:-1], pts[1:], keep[:-1], keep[1:]):
            if k1 and k2:
                cv2.line(img, tuple(int(v) for v in a), tuple(int(v) for v in b), color, thickness, cv2.LINE_AA)
    else:
        cv2.polylines(img, [pts.reshape(-1, 1, 2)], False, color, thickness, cv2.LINE_AA)


def transform_points(pts, scale=1.0, rot_deg=0.0, center=(450, 450), jitter=0.0, rng=None,
                     stretch=(1.0, 1.0)):
    pts = np.array(pts, float)
    c = pts.mean(0)
    pts = (pts - c) * np.array(stretch)
    th = np.radians(rot_deg)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    pts = (R @ pts.T).T * scale + np.array(center)
    if jitter and rng is not None:
        pts = pts + rng.normal(scale=jitter, size=pts.shape)
    return pts


def draw_segments(img, pts, edges, rng, **kw):
    for a, b in edges:
        hand_line(img, pts[a], pts[b], rng, **kw)
    return img


def cube_vertices(face=160, depth=(70, -70), origin=(0, 0)):
    x0, y0 = origin
    x1, y1 = x0 + face, y0 + face
    dx, dy = depth
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1),
            (x0 + dx, y0 + dy), (x1 + dx, y0 + dy), (x1 + dx, y1 + dy), (x0 + dx, y1 + dy)]


CUBE_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
              (0, 4), (1, 5), (2, 6), (3, 7)]


def camera_photo(paper, rng, bg_size=(1280, 720), tilt=0.08, blur=1.2, noise=4.0,
                 light=0.25, paper_frac=0.75):
    """Put the paper into a camera frame: background, perspective, light, blur, noise."""
    W, H = bg_size
    bg = np.zeros((H, W, 3), np.uint8)
    base = rng.integers(40, 110)
    bg[:] = (base, base + 10, base + 20)
    bg = cv2.GaussianBlur((bg + rng.normal(0, 12, bg.shape)).clip(0, 255).astype(np.uint8), (31, 31), 0)
    ph, pw = paper.shape[:2]
    s = paper_frac * H / ph
    tw, th = pw * s, ph * s
    cx, cy = W / 2 + rng.uniform(-60, 60), H / 2 + rng.uniform(-20, 20)
    dst = np.array([[cx - tw / 2, cy - th / 2], [cx + tw / 2, cy - th / 2],
                    [cx + tw / 2, cy + th / 2], [cx - tw / 2, cy + th / 2]], np.float32)
    dst += rng.uniform(-tilt, tilt, dst.shape).astype(np.float32) * np.float32(tw)
    src = np.array([[0, 0], [pw, 0], [pw, ph], [0, ph]], np.float32)
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(paper, M, (W, H), borderValue=(0, 0, 0))
    mask = cv2.warpPerspective(np.full((ph, pw), 255, np.uint8), M, (W, H))
    out = np.where(mask[..., None] > 0, warped, bg)
    gx = np.linspace(1 - light, 1, W)[None, :, None]
    out = (out * gx).clip(0, 255)
    if blur:
        out = cv2.GaussianBlur(out, (0, 0), blur)
    out = out + rng.normal(0, noise, out.shape)
    return out.clip(0, 255).astype(np.uint8)
