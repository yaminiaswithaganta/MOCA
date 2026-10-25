"""
MoCA Task 2 — Cube Copy (Visuospatial/Executive)
=================================================

How it works
-------------
0. A reference cube is drawn and shown in its own window (the thing the
   patient is supposed to copy) — it stays on screen the whole time,
   next to the live camera preview, exactly like the paper MoCA item
   where the cube-to-copy stays visible while they draw.
1. Opens your webcam in a live preview window with on-screen instructions.
2. Patient draws a 3D cube on paper (copying the reference) and holds it
   up to the camera.
3. Once the paper is held steady in front of the camera, a 10-second
   countdown starts automatically (SPACE also starts it); at 0 a photo is
   captured automatically.
4. The photo is scored automatically against the ACTUAL reference cube
   (the same 8 corners / 12 edges used to draw the reference window):
      a. find the sheet of paper, straighten it, extract the pen strokes
      b. thin the strokes, find straight edges, join broken pieces
      c. group edge ends into corners -> a graph of corners + edges
      d. STRUCTURE: exactly 8 corners, 12 edges, 3 edges per corner,
         connected like a cube (missing / extra edges -> 0)
      e. GEOMETRY: match the 8 drawn corners to the 8 reference corners
         (only shift / rotate / uniform scale allowed -- no mirroring, no
         stretching) and require a small fit error, the same 3 families of
         parallel edges (horizontal, vertical, diagonal up-right), the same
         perspective and similar proportions.
   -> 1 point only if every check passes, otherwise 0. Anything the system
      cannot verify also scores 0.

Setup
-----
    pip install opencv-python numpy scikit-image

Run
---
    python task2_cube_copy.py

Controls while the camera window is open:
    (automatic) hold the paper steady -> countdown starts by itself
    SPACE  -  start the 10s hold countdown manually
    q      -  quit without scoring
"""

import shutil
import subprocess
import sys
import time

import numpy as np
import cv2

from moca_common import (SteadyPaperDetector, angle_diff180, drawing_candidates, find_pen_ink,
                         get_session_dir, _photo_to_width, _touches_border,
                         make_task_result, merge_line_segments, prepare_drawing,
                         save_task_result, show_result_window, skeletonize_mask)

TASK_ID = "task2_cube_copy"

from moca_voice import speak_instruction, HAS_MAC_VOICE as HAS_VOICE


def say(text, wait=True, rate=150):
    """Speak an instruction through the shared moca_voice module."""
    return speak_instruction(text, wait=wait, rate=rate)


# --------------------------------------------------------------------------
# 0. Reference cube — the thing the patient is asked to copy
# --------------------------------------------------------------------------
REF_SIZE, REF_MARGIN, REF_DEPTH_OFFSET = 350, 60, 70


def reference_cube_geometry(size=REF_SIZE, margin=REF_MARGIN, depth_offset=REF_DEPTH_OFFSET):
    """
    The exact corner coordinates and edges of the reference cube. This is the
    single source of truth: `make_reference_cube_image()` draws it and
    `score_cube()` compares the patient's drawing against it.
    """
    # front face (axis-aligned square)
    x0, y0 = margin, margin + depth_offset
    x1, y1 = size - margin - depth_offset, size - margin
    # back face (shifted up-right)
    bx0, by0 = x0 + depth_offset, y0 - depth_offset
    bx1, by1 = x1 + depth_offset, y1 - depth_offset

    names = ["F_tl", "F_tr", "F_br", "F_bl", "B_tl", "B_tr", "B_br", "B_bl"]
    pts = np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1),
                    (bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)], dtype=np.float64)
    edges = [(0, 1), (1, 2), (2, 3), (3, 0),        # front face
             (4, 5), (5, 6), (6, 7), (7, 4),        # back face
             (0, 4), (1, 5), (2, 6), (3, 7)]        # connecting diagonals
    return {"names": names, "vertices": pts, "edges": edges}


def make_reference_cube_image(size=350, margin=60, depth_offset=70):
    """
    Draws a simple wireframe cube (two offset squares + connecting
    diagonals) as the reference image the patient copies — generated
    fresh here, not a scan of any copyrighted test sheet.
    """
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    geo = reference_cube_geometry(size, margin, depth_offset)
    pts = geo["vertices"].astype(int)
    for a, b in geo["edges"]:
        cv2.line(img, tuple(int(v) for v in pts[a]), tuple(int(v) for v in pts[b]), (0, 0, 0), 3)

    cv2.putText(img, "COPY THIS CUBE", (30, 30), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (0, 0, 0), 2)
    return img


def show_reference_cube(window_name="Reference Cube - Copy This", position=(50, 50)):
    """Opens a persistent window showing the reference cube and returns its name."""
    ref_img = make_reference_cube_image()
    cv2.imshow(window_name, ref_img)
    cv2.moveWindow(window_name, *position)
    cv2.waitKey(1)  # let the window actually paint
    return window_name


# --------------------------------------------------------------------------
# 1. Camera capture with an on-screen instruction + 10-second hold countdown
# --------------------------------------------------------------------------
def capture_with_countdown(hold_seconds=10, cam_index=0, save_path=None,
                            show_reference=True, auto_start=True):
    if save_path is None:
        save_path = str(get_session_dir() / "cube_capture.png")
    cap = cv2.VideoCapture(cam_index)
    if not cap.isOpened():
        raise RuntimeError("Could not open webcam. Check cam_index / permissions.")

    ref_window = None
    if show_reference:
        ref_window = show_reference_cube()

    # Voice instructions
    say("Look at the reference cube shown on the screen. Draw a matching three-dimensional cube on paper. "
        "Include all edges and make it look like the reference. Then hold your drawing up to the camera. "
        "The system will automatically start counting down when it detects the paper is steady, or you can press space to start manually.")

    print("Look at the reference cube window, draw a matching 3D cube on paper,")
    print("then hold it up facing the camera.")
    print("The countdown starts automatically once the paper is held steady "
          f"(or press SPACE). Press q to quit.")

    frame = None
    countdown_started = None
    steady = SteadyPaperDetector() if auto_start else None

    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        display = frame.copy()

        if countdown_started is None:
            cv2.putText(display, "Copy the reference cube, then hold it up", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(display, "Hold still (auto) or press SPACE when ready", (20, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            if steady is not None and steady.update(frame):
                print("[capture] Paper detected and steady -- starting countdown.")
                countdown_started = time.time()
        else:
            elapsed = time.time() - countdown_started
            remaining = hold_seconds - elapsed
            if remaining <= 0:
                cv2.imwrite(save_path, frame)
                print(f"[capture] Photo saved to {save_path}")
                break
            cv2.putText(display, f"Hold steady... capturing in {int(remaining) + 1}s",
                        (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)

        cv2.imshow("MoCA Task 2 - Cube Copy", display)
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
# 2. Line detection + parallel-group analysis (original helpers, kept for
#    debugging / comparison -- the score now comes from section 3)
# --------------------------------------------------------------------------
def detect_lines(image_path):
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    lines = cv2.HoughLinesP(
        edges, rho=1, theta=np.pi / 180, threshold=40,
        minLineLength=30, maxLineGap=10,
    )
    if lines is None:
        return []
    return [tuple(l) for l in lines.reshape(-1, 4)]  # each: (x1, y1, x2, y2)


def line_angle_deg(x1, y1, x2, y2):
    """Angle of the line in degrees, normalized to [0, 180)."""
    angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
    return angle % 180


def group_parallel_lines(lines, angle_tolerance=8):
    """
    Cluster lines into groups of near-identical orientation.
    Returns a list of groups; each group is a list of lines that are
    mutually parallel within `angle_tolerance` degrees.
    """
    angles = [line_angle_deg(*l) for l in lines]
    order = np.argsort(angles)
    sorted_lines = [lines[i] for i in order]
    sorted_angles = [angles[i] for i in order]

    groups = []
    current_group = [sorted_lines[0]] if sorted_lines else []
    current_angles = [sorted_angles[0]] if sorted_angles else []

    for line, angle in zip(sorted_lines[1:], sorted_angles[1:]):
        if abs(angle - current_angles[-1]) <= angle_tolerance:
            current_group.append(line)
            current_angles.append(angle)
        else:
            groups.append(current_group)
            current_group = [line]
            current_angles = [angle]
    if current_group:
        groups.append(current_group)

    # Wrap-around check (angles near 0 and near 180 are actually close)
    if len(groups) > 1:
        first_angle = line_angle_deg(*groups[0][0])
        last_angle = line_angle_deg(*groups[-1][0])
        if (180 - last_angle) + first_angle <= angle_tolerance:
            groups[0] = groups[-1] + groups[0]
            groups.pop()

    return groups


def line_perp_offset(x1, y1, x2, y2):
    """
    Perpendicular distance of the line from the image origin, used to tell
    apart two lines that share an orientation but sit in different places
    (real parallel edges) from two Hough fragments of the SAME physical
    edge (which sit at ~the same offset and should be merged, not double
    counted).
    """
    angle = np.radians(line_angle_deg(x1, y1, x2, y2))
    nx, ny = -np.sin(angle), np.cos(angle)  # unit normal to the line
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    return mx * nx + my * ny


def merge_collinear_duplicates(group, offset_tolerance=15):
    """
    Within one angle-group, merge Hough fragments that belong to the same
    physical edge (near-identical perpendicular offset) so a single edge
    split into several short segments isn't miscounted as multiple
    parallel edges. Returns the list of DISTINCT edges (one line per
    physical edge).
    """
    offsets = [line_perp_offset(*l) for l in group]
    order = np.argsort(offsets)
    sorted_lines = [group[i] for i in order]
    sorted_offsets = [offsets[i] for i in order]

    distinct = []
    current = [sorted_lines[0]]
    current_offset = sorted_offsets[0]
    for line, off in zip(sorted_lines[1:], sorted_offsets[1:]):
        if abs(off - current_offset) <= offset_tolerance:
            current.append(line)
        else:
            distinct.append(current)
            current = [line]
            current_offset = off
    distinct.append(current)
    return distinct  # list of clusters; len(distinct) == number of distinct physical edges


# --------------------------------------------------------------------------
# 3. Cube validation against the reference geometry
# --------------------------------------------------------------------------
# Tolerances (fractions are relative to the drawn cube's size or to the
# reference edge length). Loosen/tighten after calibrating on real drawings.
CUBE_TOL = {
    "min_drawing_frac": 0.10,     # drawing must span >=10% of the paper
    "work_size": 600,             # drawing is analysed at this size (pixels)
    "merge_angle_deg": 10.0,      # Hough fragments of one edge: angle diff
    "merge_offset_frac": 0.03,    #   ... perpendicular offset (x drawing size)
    "merge_gap_frac": 0.08,       #   ... gap along the line (x drawing size)
    "merge_gap_max_frac": 0.30,   #   ... longer gaps only if ink continues there
    "gap_ink_coverage": 0.85,
    "min_edge_frac": 0.14,        # shorter strokes are ignored as noise
    "corner_join_frac": 0.13,     # edge ends closer than this form one corner
    "max_rms_error": 0.12,        # corner fit error (x reference edge length)
    "max_corner_error": 0.20,     # worst single corner (x reference edge length)
    "max_rotation_deg": 20.0,     # drawing may be tilted at most this much
    "max_family_spread_deg": 15.0,  # the 4 edges of a parallel family
    "max_family_offset_deg": 15.0,  # family direction vs. reference
    "face_aspect_range": (0.70, 1.43),
    "depth_ratio_range": (0.55, 1.70),  # depth edges vs. reference depth
    "max_family_length_ratio": 1.7,
}


def _main_drawing_mask(ink):
    """Keep the largest cluster of pen strokes (the cube) and drop the rest."""
    h, w = ink.shape
    k = max(3, int(min(h, w) * 0.02)) | 1
    grown = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, labels = cv2.connectedComponents(grown, connectivity=8)
    if n <= 1:
        return None, 0
    counts = np.bincount(labels[ink > 0], minlength=n)
    counts[0] = 0
    best = int(np.argmax(counts))
    main = ((labels == best) & (ink > 0)).astype(np.uint8) * 255
    other_ink = int(counts.sum() - counts[best])
    return main, other_ink


def _merge_segments(segs, size, ink=None):
    """Join Hough fragments that belong to the same drawn edge."""
    return merge_line_segments(segs, size, CUBE_TOL, ink)


def _line_intersection_lsq(segs):
    """Least-squares point closest to all lines (robust corner position)."""
    A, bvec = np.zeros((2, 2)), np.zeros(2)
    for s in segs:
        p, q = s[:2], s[2:]
        d = (q - p) / max(np.linalg.norm(q - p), 1e-9)
        P = np.eye(2) - np.outer(d, d)
        A += P
        bvec += P @ p
    if abs(np.linalg.det(A)) < 1e-6:
        return None
    return np.linalg.solve(A, bvec)


def extract_cube_graph(ink):
    """
    Pen-stroke mask -> {"nodes": Nx2 corners, "edges": [(i, j)], "segments": [...]}.
    Returns (graph, reason). graph is None when no drawing could be found.
    """
    main, other_ink = _main_drawing_mask(ink)
    if main is None:
        return None, "no drawing found on the paper"
    ys, xs = np.nonzero(main)
    size = float(max(xs.max() - xs.min(), ys.max() - ys.min()))
    if size < CUBE_TOL["min_drawing_frac"] * min(ink.shape):
        return None, "drawing too small / nothing drawn"
    # Work on a crop around the drawing at a fixed size, so a small drawing
    # far from the camera is analysed at the same detail as a large one.
    pad = int(0.08 * size) + 4
    y0, y1 = max(0, ys.min() - pad), min(main.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(main.shape[1], xs.max() + pad + 1)
    crop = main[y0:y1, x0:x1]
    scale = CUBE_TOL["work_size"] / size
    crop = cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), max(1, int(crop.shape[0] * scale))),
                      interpolation=cv2.INTER_LINEAR)
    main = ((crop > 127) * 255).astype(np.uint8)
    size = float(CUBE_TOL["work_size"])
    to_image = (scale, x0, y0)   # to map results back onto the photo

    # bridge tiny breaks in the pen line, then thin to 1-px centre lines
    k = max(3, int(size * 0.012)) | 1
    closed = cv2.morphologyEx(main, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    skel = skeletonize_mask(closed)
    # a slightly thickened centre line lets Hough follow a wobbly hand line
    skel_thick = cv2.dilate(skel, np.ones((3, 3), np.uint8))
    lines = cv2.HoughLinesP(skel_thick, 1, np.pi / 180, threshold=max(8, int(size * 0.04)),
                            minLineLength=max(6, int(size * 0.05)),
                            maxLineGap=max(3, int(size * 0.03)))
    if lines is None:
        return None, "no straight edges found"
    ink_support = cv2.dilate(closed, np.ones((5, 5), np.uint8))
    segs = _merge_segments(list(lines.reshape(-1, 4)), size, ink_support)
    min_len = CUBE_TOL["min_edge_frac"] * size
    segs = [s for s in segs if np.hypot(*(s[2:] - s[:2])) >= min_len]
    if not segs:
        return None, "no straight edges found"

    # corners: cluster edge end points (single linkage)
    ends = np.array([p for s in segs for p in (s[:2], s[2:])])
    n = len(ends)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    join = CUBE_TOL["corner_join_frac"] * size
    for i in range(n):
        for j in range(i + 1, n):
            if np.linalg.norm(ends[i] - ends[j]) <= join:
                parent[find(i)] = find(j)
    roots = sorted({find(i) for i in range(n)})
    node_of = {r: k for k, r in enumerate(roots)}
    end_node = [node_of[find(i)] for i in range(n)]

    nodes = []
    for r in roots:
        members = [i for i in range(n) if find(i) == r]
        member_segs = [segs[i // 2] for i in members]
        p = _line_intersection_lsq(member_segs) if len(member_segs) >= 2 else None
        mean = ends[members].mean(axis=0)
        if p is None or np.linalg.norm(p - mean) > join:
            p = mean
        nodes.append(p)

    edges = [(end_node[2 * k], end_node[2 * k + 1]) for k in range(len(segs))]
    # a short stub whose both ends fall into the same corner (a pen flick /
    # overshoot at a corner) is not an edge -- drop it
    keep = [k for k, (a, b) in enumerate(edges) if a != b]
    segs = [segs[k] for k in keep]
    edges = [edges[k] for k in keep]
    used = sorted({v for e in edges for v in e})
    remap = {v: i for i, v in enumerate(used)}
    nodes = [nodes[v] for v in used]
    edges = [(remap[a], remap[b]) for a, b in edges]
    sc, ox, oy = to_image
    nodes_img = np.array([np.asarray(p) / sc + (ox, oy) for p in nodes]).reshape(-1, 2)
    segs_img = [np.concatenate([s[:2] / sc + (ox, oy), s[2:] / sc + (ox, oy)]) for s in segs]
    return {"nodes": np.array(nodes).reshape(-1, 2), "edges": edges, "segments": segs,
            "nodes_image": nodes_img, "segments_image": segs_img,
            "size": size, "other_ink_pixels": other_ink}, ""


def _is_cube_graph(n_nodes, edges):
    """8 corners, 12 distinct edges, 3 per corner, bipartite, connected == cube."""
    if n_nodes != 8:
        return False, f"found {n_nodes} corners (a cube has 8)"
    if any(a == b for a, b in edges):
        return False, "an edge starts and ends at the same corner (malformed)"
    und = {tuple(sorted(e)) for e in edges}
    if len(und) != len(edges):
        return False, "duplicate edges between the same two corners"
    if len(edges) != 12:
        return False, f"found {len(edges)} edges (a cube has 12)"
    deg = np.zeros(8, int)
    adj = {i: set() for i in range(8)}
    for a, b in edges:
        deg[a] += 1
        deg[b] += 1
        adj[a].add(b)
        adj[b].add(a)
    if not np.all(deg == 3):
        return False, f"corner edge-counts {sorted(deg.tolist())} (every cube corner joins 3 edges)"
    color = {0: 0}
    stack = [0]
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if v not in color:
                color[v] = 1 - color[u]
                stack.append(v)
            elif color[v] == color[u]:
                return False, "edges are not connected like a cube"
    if len(color) != 8:
        return False, "drawing is not one connected shape"
    return True, ""


def _graph_isomorphisms(adj_draw, adj_ref):
    """All corner mappings drawn->reference that preserve every edge (48 for a cube)."""
    order = [0]
    seen = {0}
    while len(order) < 8:  # BFS order keeps the search tiny
        for u in list(order):
            for v in sorted(adj_draw[u]):
                if v not in seen:
                    seen.add(v)
                    order.append(v)
    maps = []

    def rec(k, mapping, used):
        if k == 8:
            maps.append(dict(mapping))
            return
        u = order[k]
        for r in range(8):
            if r in used:
                continue
            if all((mapping[v] in adj_ref[r]) == (v in adj_draw[u]) for v in mapping):
                mapping[u] = r
                used.add(r)
                rec(k + 1, mapping, used)
                del mapping[u]
                used.discard(r)

    rec(0, {}, set())
    return maps


def _similarity_fit(src, dst):
    """Best rotation+uniform scale+shift (no mirroring) mapping src -> dst."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    S, D = src - mu_s, dst - mu_d
    H = S.T @ D
    U, sig, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:           # mirroring is not allowed
        Vt[-1] *= -1
        sig = sig.copy()
        sig[-1] *= -1
        R = Vt.T @ U.T
    scale = sig.sum() / max((S ** 2).sum(), 1e-9)
    fitted = (scale * (R @ S.T)).T + mu_d
    rot = np.degrees(np.arctan2(R[1, 0], R[0, 0]))
    return fitted, scale, rot


def score_cube_drawing(ink):
    """
    Core scoring on a pen-stroke mask. Returns a dict with score (0/1),
    per-check results and the reason for the decision.
    """
    ref = reference_cube_geometry()
    ref_pts = ref["vertices"]
    ref_edge_len = np.linalg.norm(ref_pts[1] - ref_pts[0])
    checks = {}

    graph, why = extract_cube_graph(ink)
    if graph is None:
        return {"score": 0, "cube_detected": False, "reason": why, "checks": checks, "graph": None}
    edges = graph["edges"]
    ok, why = _is_cube_graph(len(graph["nodes"]), edges)
    checks["structure"] = ok
    checks["corners_found"] = len(graph["nodes"])
    checks["edges_found"] = len(edges)
    if not ok:
        return {"score": 0, "cube_detected": False, "reason": why, "checks": checks, "graph": graph}

    adj_d = {i: set() for i in range(8)}
    for a, b in edges:
        adj_d[a].add(b)
        adj_d[b].add(a)
    adj_r = {i: set() for i in range(8)}
    for a, b in ref["edges"]:
        adj_r[a].add(b)
        adj_r[b].add(a)

    # Try every structure-preserving corner correspondence; keep the best fit.
    fits = []
    for m in _graph_isomorphisms(adj_d, adj_r):
        drawn = np.array([graph["nodes"][u] for u in sorted(m, key=lambda u: m[u])])
        # fit reference -> drawing; express errors in reference units
        fitted, scale, rot = _similarity_fit(ref_pts, drawn)
        err = np.linalg.norm(fitted - drawn, axis=1) / (scale * ref_edge_len)
        rms = float(np.sqrt((err ** 2).mean()))
        fits.append({"rms": rms, "max": float(err.max()), "rot": float(rot),
                     "scale": float(scale), "drawn": drawn, "mapping": m})
    # A wireframe cube looks identical when turned 180 deg (front/back faces
    # swap), so several correspondences fit equally well: among the
    # near-best fits take the one needing the least rotation.
    min_rms = min(f["rms"] for f in fits)
    best = min((f for f in fits if f["rms"] <= min_rms + 0.02), key=lambda f: abs(f["rot"]))
    tol = CUBE_TOL
    drawn = best["drawn"]
    # undo the global rotation so directions can be compared to the reference
    th = np.radians(-best["rot"])
    Rm = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    dn = (Rm @ (drawn - drawn.mean(0)).T).T / best["scale"]

    families = {"horizontal": [0, 2, 4, 6], "vertical": [1, 3, 5, 7], "depth": [8, 9, 10, 11]}
    fam_info = {}
    fam_ok = True
    for name, idx in families.items():
        angs, lens, ref_angs = [], [], []
        for k in idx:
            a, b = ref["edges"][k]
            v = dn[b] - dn[a]
            rv = ref_pts[b] - ref_pts[a]
            angs.append(np.degrees(np.arctan2(v[1], v[0])) % 180)
            ref_angs.append(np.degrees(np.arctan2(rv[1], rv[0])) % 180)
            lens.append(np.linalg.norm(v))
        base = angs[0]
        rel = [((a - base + 90) % 180) - 90 for a in angs]   # unwrap around first
        spread = max(rel) - min(rel)
        mean_ang = (base + np.mean(rel)) % 180
        offset = angle_diff180(mean_ang, ref_angs[0])
        len_ratio = max(lens) / max(min(lens), 1e-9)
        ok_f = bool(spread <= tol["max_family_spread_deg"]
                    and offset <= tol["max_family_offset_deg"]
                    and len_ratio <= tol["max_family_length_ratio"])
        fam_ok &= ok_f
        fam_info[name] = {"spread_deg": spread, "offset_deg": offset,
                          "length_ratio": len_ratio, "mean_length": float(np.mean(lens)), "ok": ok_f}

    face_aspect = fam_info["horizontal"]["mean_length"] / max(fam_info["vertical"]["mean_length"], 1e-9)
    ref_depth = np.linalg.norm(ref_pts[4] - ref_pts[0])
    depth_ratio = fam_info["depth"]["mean_length"] / ref_depth
    checks.update({
        "fit_rms_error": best["rms"], "fit_max_error": best["max"],
        "rotation_deg": best["rot"], "families": fam_info,
        "face_aspect": face_aspect, "depth_ratio": depth_ratio,
    })
    fails = []
    if best["rms"] > tol["max_rms_error"] or best["max"] > tol["max_corner_error"]:
        fails.append(f"shape differs from the reference (fit error {best['rms']:.2f}, "
                     f"worst corner {best['max']:.2f})")
    if abs(best["rot"]) > tol["max_rotation_deg"]:
        fails.append(f"wrong orientation/perspective (rotated {best['rot']:.0f} deg vs reference)")
    if not fam_ok:
        bad = [k for k, v in fam_info.items() if not v["ok"]]
        fails.append(f"edges not parallel/aligned like the reference: {', '.join(bad)}")
    lo, hi = tol["face_aspect_range"]
    if not lo <= face_aspect <= hi:
        fails.append(f"face proportions differ (aspect {face_aspect:.2f})")
    lo, hi = tol["depth_ratio_range"]
    if not lo <= depth_ratio <= hi:
        fails.append(f"depth proportions differ (depth ratio {depth_ratio:.2f})")

    passed = not fails
    return {"score": 1 if passed else 0, "cube_detected": passed,
            "reason": "matches the reference cube" if passed else "; ".join(fails),
            "checks": checks, "graph": graph, "best_fit": best}


def score_cube(image_path, **_legacy_kwargs):
    """Score a captured photo (path) of the patient's cube drawing: 0 or 1."""
    img = cv2.imread(image_path)
    if img is None:
        return {"score": 0, "max_score": 1, "cube_detected": False,
                "reason": f"could not read image {image_path}", "checks": {}}
    return score_cube_image(img)


def score_cube_image(img_bgr):
    """Photo (BGR array) -> cube result. Same path as a captured photo."""
    img = _photo_to_width(img_bgr)
    ink = find_pen_ink(img)
    best, best_key = None, None
    for mask in drawing_candidates(ink):
        r = score_cube_drawing(mask)
        # prefer a passing candidate; otherwise the one closest to a cube
        key = (r["score"], r["checks"].get("edges_found", 0) == 12,
               r["checks"].get("corners_found", 0))
        if best_key is None or key > best_key:
            best, best_key = (r, mask), key
        if r["score"] == 1:
            break
    if best is None:
        result = score_cube_drawing(np.zeros(ink.shape, np.uint8))
        mask = None
    else:
        result, mask = best
    if result["score"] == 0 and mask is not None and _touches_border(mask):
        result["reason"] = ("the drawing runs off the edge of the photo -- "
                            "hold the paper so the whole cube is in view")
    result["max_score"] = 1
    result["paper_found"] = None
    result["_prep"] = {"bgr": img, "ink": ink, "paper_found": None}
    return result


def annotate_and_save(image_path, out_path=None, result=None):
    """Draw what the scorer saw (edges, corners, decision) for checking/debugging."""
    if out_path is None:
        out_path = str(get_session_dir() / "cube_annotated.png")
    if result is None:
        result = score_cube(image_path)
    prep = result.get("_prep")
    img = prep["bgr"].copy() if prep is not None else cv2.imread(image_path)
    graph = result.get("graph")
    if graph is not None:
        for s in graph["segments_image"]:
            cv2.line(img, tuple(int(v) for v in s[:2]), tuple(int(v) for v in s[2:]), (255, 120, 0), 3)
        for p in graph["nodes_image"]:
            cv2.circle(img, (int(p[0]), int(p[1])), 9, (0, 0, 255), 2)
    cv2.imwrite(out_path, img)
    return out_path


# --------------------------------------------------------------------------
# 4. Main
# --------------------------------------------------------------------------
def run_task2(cam_index=0, show_result=True):
    print("=" * 60)
    print("MoCA Task 2: Cube Copy")
    print("=" * 60)
    photo_path = capture_with_countdown(hold_seconds=10, cam_index=cam_index)
    if photo_path is None:
        print("Cancelled.")
        return None
    return score_and_report(photo_path, show_result=show_result)


def score_and_report(photo_path, show_result=True):
    """Score a captured photo, print/show/save the result, return the standard dict."""
    result = score_cube(photo_path)
    annotated = annotate_and_save(photo_path, result=result)
    checks = result.get("checks", {})

    print("\n--- RESULT ---")
    print(f"Corners found: {checks.get('corners_found', 0)}   Edges found: {checks.get('edges_found', 0)}")
    if "fit_rms_error" in checks:
        print(f"Fit to reference: rms={checks['fit_rms_error']:.3f}  "
              f"worst corner={checks['fit_max_error']:.3f}  rotation={checks['rotation_deg']:.1f} deg")
    print(f"Decision: {result['reason']}")
    print(f"SCORE: {result['score']} / 1")
    print(f"Annotated image saved to: {annotated}")

    std = make_task_result(
        TASK_ID, result["score"], reason=result["reason"],
        details={"checks": checks, "paper_found": result.get("paper_found")},
        evidence_files=[photo_path, annotated])
    saved = save_task_result(std)
    print(f"Result saved to: {saved}")
    if show_result:
        show_result_window("MoCA Task 2 - Result", cv2.imread(annotated),
                           [f"Task 2 (cube) SCORE: {result['score']} / 1", result["reason"][:90]],
                           passed=result["score"] == 1)
    return std


if __name__ == "__main__":
    run_task2()
