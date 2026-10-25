"""
Task 7 camera check -- run this on the Mac before a session (about 40 seconds).

    python tools/check_task7_camera.py            # camera 0
    python tools/check_task7_camera.py --camera 1

What it does
  1. Calibrates the hand detector exactly as Task 7 does (hands down, then one practice raise).
  2. Records 20 seconds while you raise and lower your hand 3 times, with pauses.
  3. Shows the live picture with the detection zone (yellow), the skin pixels (green)
     and HAND UP / hand down.
  4. Saves results/camera_check_<time>/ with a trace (task7_camera_trace.json) and
     a picture of the detection at the end. Send that folder back for tuning.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import task7_letters as t7  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "results" / f"camera_check_{time.strftime('%Y%m%d_%H%M%S')}"


def overlay(frame, det, up, frac):
    disp = frame.copy()
    small_h, small_w = det.last_bgr.shape[:2]
    if det.zone is not None:
        zone = cv2.resize(det.zone.astype(np.uint8) * 255, (disp.shape[1], disp.shape[0]),
                          interpolation=cv2.INTER_NEAREST) > 0
        disp[zone] = (0.75 * disp[zone] + 0.25 * np.array([255, 200, 0])).astype(np.uint8)
        skin = cv2.resize((det.skin_mask(det.last_bgr) & det.zone).astype(np.uint8) * 255,
                          (disp.shape[1], disp.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
        disp[skin] = (0.5 * disp[skin] + 0.5 * np.array([0, 255, 0])).astype(np.uint8)
    if up is not None:
        cv2.putText(disp, "HAND UP" if up else "hand down", (20, 50), cv2.FONT_HERSHEY_SIMPLEX,
                    1.4, (0, 0, 255) if up else (0, 160, 0), 3)
    if frac is not None:
        cv2.putText(disp, f"signal {frac:.3f}", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (255, 255, 255), 2)
    return cv2.resize(disp, (960, int(960 * disp.shape[0] / disp.shape[1])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    t7.say = lambda *a, **k: None          # the examiner reads these instructions in the real task
    det = t7.HandRaiseDetector(args.camera)
    if not det.ok():
        print("Camera could not be opened.")
        return

    def preview(frame, value):
        if frame is not None:
            cv2.imshow("Task 7 camera check", overlay(frame, det, None, value))
        return cv2.waitKey(1) & 0xFF

    print("Step 1: sit still with hands down on your lap for about 3 seconds ...")
    ok, info = det.calibrate(preview)
    print(f"Calibration: {'OK' if ok else 'FAILED'}  {info}")
    print("Step 2: now raise your hand, hold 2 seconds, put it down; repeat 3 times (20 seconds).")
    trace, t0 = [], time.time()
    prev_up = False
    while time.time() - t0 < 20:
        frame, g = det.read()
        if g is None:
            preview(None, None)
            continue
        up, frac = det.update(g)
        trace.append({"t": round(time.time() - t0, 2), "signal": round(float(frac), 4), "up": bool(up)})
        cv2.imshow("Task 7 camera check", overlay(frame, det, up, frac))
        if cv2.waitKey(1) & 0xFF == 27:
            break
        prev_up = up
    det.release()
    cv2.destroyAllWindows()

    runs = t7._hand_up_runs([(p["t"], p["up"]) for p in trace])
    summary = {"calibration": info, "signal_used": det.mode, "frames": len(trace),
               "hand_up_periods_s": [[round(a, 2), round(b, 2)] for a, b in runs],
               "thr_up": det.thr_up, "thr_down": det.thr_down}
    (OUT / "task7_camera_trace.json").write_text(json.dumps({"summary": summary, "trace": trace}, indent=1))
    print("\nHand-up periods detected (seconds from start):", summary["hand_up_periods_s"])
    print(f"Frames: {len(trace)}   Signal used: {det.mode}")
    print(f"Saved to: {OUT}")
    print("Please send this folder (task7_camera_trace.json) back.")


if __name__ == "__main__":
    main()
