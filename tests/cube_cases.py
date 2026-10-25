"""Cube test cases: (name, expected_score, image) generators."""

import numpy as np
import cv2

from synth import (CUBE_EDGES, blank_paper, camera_photo, cube_vertices, draw_segments,
                   hand_line, transform_points)


def _cube_img(rng, face=160, depth=(70, -70), scale=2.2, rot=0.0, jitter=0.0, stretch=(1, 1),
              edges=CUBE_EDGES, extra=None, thickness=4, wobble=1.5, gap=0.0, overshoot=0.0,
              color=(35, 35, 40), move_corner=None):
    img = blank_paper()
    pts = transform_points(cube_vertices(face, depth), scale=scale, rot_deg=rot,
                           jitter=jitter, rng=rng, stretch=stretch)
    if move_corner is not None:
        idx, delta = move_corner
        pts[idx] += np.array(delta)
    draw_segments(img, pts, edges, rng, thickness=thickness, wobble=wobble, gap=gap,
                  overshoot=overshoot, color=color)
    if extra:
        for a, b in extra:
            hand_line(img, pts[a], pts[b], rng, thickness=thickness, wobble=wobble, color=color)
    return img


def cube_cases(seed=0):
    rng = np.random.default_rng(seed)
    cases = []
    # ---------------- must PASS (1) ----------------
    cases.append(("exact reference copy", 1, _cube_img(rng, wobble=0.0)))
    for i in range(4):
        cases.append((f"hand-drawn wobble+jitter #{i}", 1,
                      _cube_img(rng, jitter=9, wobble=2.0, overshoot=0.03)))
    cases.append(("slightly rotated +8deg", 1, _cube_img(rng, rot=8, jitter=6)))
    cases.append(("slightly rotated -8deg", 1, _cube_img(rng, rot=-8, jitter=6)))
    cases.append(("small drawing", 1, _cube_img(rng, scale=1.2, jitter=4, thickness=3)))
    cases.append(("large drawing", 1, _cube_img(rng, scale=3.0, jitter=10)))
    cases.append(("slightly wider prism", 1, _cube_img(rng, stretch=(1.15, 1.0), jitter=6)))
    cases.append(("a bit deeper", 1, _cube_img(rng, depth=(85, -85), jitter=6)))
    cases.append(("broken strokes (small gaps)", 1, _cube_img(rng, gap=0.04, jitter=6)))
    cases.append(("faint pencil", 1, _cube_img(rng, color=(130, 130, 130), thickness=3, jitter=6)))
    cases.append(("thin pen", 1, _cube_img(rng, thickness=2, jitter=6)))
    for i in range(3):
        cases.append((f"camera photo #{i}", 1,
                      camera_photo(_cube_img(rng, jitter=7, wobble=1.8, overshoot=0.02), rng)))
    # ---------------- must FAIL (0) ----------------
    cases.append(("blank page", 0, blank_paper()))
    cases.append(("missing one edge", 0, _cube_img(rng, edges=CUBE_EDGES[:-1], jitter=5)))
    cases.append(("missing hidden edges (solid cube)", 0,
                  _cube_img(rng, edges=[e for i, e in enumerate(CUBE_EDGES) if i not in (6, 7, 11)], jitter=5)))
    cases.append(("extra face diagonal", 0, _cube_img(rng, extra=[(0, 2)], jitter=5)))
    cases.append(("extra back diagonal", 0, _cube_img(rng, extra=[(4, 6)], jitter=5)))
    cases.append(("flat square only", 0, _cube_img(rng, edges=CUBE_EDGES[:4], jitter=5)))
    cases.append(("two squares, no connectors", 0, _cube_img(rng, edges=CUBE_EDGES[:8], jitter=5)))
    cases.append(("mirrored (back face up-left)", 0, _cube_img(rng, depth=(-70, -70), jitter=5)))
    cases.append(("back face down-right", 0, _cube_img(rng, depth=(70, 70), jitter=5)))
    cases.append(("stretched 2x wide", 0, _cube_img(rng, stretch=(2.0, 1.0), scale=1.6, jitter=5)))
    cases.append(("very deep (depth 2.3x)", 0, _cube_img(rng, depth=(160, -160), scale=1.5, jitter=5)))
    cases.append(("very shallow (depth 0.3x)", 0, _cube_img(rng, depth=(20, -20), jitter=3)))
    cases.append(("heavily distorted corner", 0, _cube_img(rng, move_corner=(5, (90, -100)), jitter=3)))
    cases.append(("rotated 45deg", 0, _cube_img(rng, rot=45, jitter=5)))
    cases.append(("turned 180 (wireframe looks identical)", 1, _cube_img(rng, rot=180, jitter=5)))
    img = blank_paper()
    for _ in range(12):
        p, q = rng.uniform(150, 750, 2), rng.uniform(150, 750, 2)
        hand_line(img, p, q, rng, thickness=4)
    cases.append(("random lines", 0, img))
    img = blank_paper()
    for k in range(4):   # "#"-grid + diagonals: 3 parallel families (old code passed this)
        hand_line(img, (250 + 130 * k, 200), (250 + 130 * k, 700), rng, thickness=4)
        hand_line(img, (200, 250 + 130 * k), (700, 250 + 130 * k), rng, thickness=4)
    for k in range(3):
        hand_line(img, (200 + 100 * k, 750), (400 + 100 * k, 550), rng, thickness=4)
    cases.append(("grid of parallel lines", 0, img))
    img = blank_paper()
    tri = np.array([(300, 600), (600, 600), (450, 340)], float)
    tri2 = tri + (120, -90)
    for P in (tri, tri2):
        for i in range(3):
            hand_line(img, P[i], P[(i + 1) % 3], rng, thickness=4)
    for i in range(3):
        hand_line(img, tri[i], tri2[i], rng, thickness=4)
    cases.append(("triangular prism", 0, img))
    img = blank_paper()
    cv2.circle(img, (450, 450), 250, (35, 35, 40), 4)
    cases.append(("circle", 0, img))
    return cases
