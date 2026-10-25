"""
Run the MoCA tasks in sequence and score them automatically.

    Task 1   Trail making (voice)        1 point  ┐
    Task 2   Cube copy (camera)          1 point  ├ Visuospatial / Executive  /5
    Task 3   Clock drawing (camera)      3 points ┘
    Task 4   Naming (voice)              3 points   Naming                    /3
    Task 5   Memory (voice)              no points  (2 learning trials, saved for delayed recall)
    Task 6   Digit Span (voice)          2 points ┐
    Task 7   Letters / A (camera)        1 point  ├ Attention                 /6
    Task 8   Serial 7s (voice)           3 points ┘
    Task 9   Language: sentences (voice) 2 points ┐
    Task 10  Language: F words (voice)   1 point  ┘ Language                  /3
    Task 11  Abstraction (voice)         2 points   Abstraction               /2
    Task 12  Delayed recall (voice)      5 points   Delayed recall            /5
    Task 13  Orientation (voice)         6 points   Orientation               /6

Each task is scored as soon as it is completed; the score is shown on screen,
saved to results/<session>/<task>.json, and the running total is printed.
At the end results/<session>/moca_results.json holds the full report.

Usage:
    python run_moca.py                    # all 13 tasks (total out of 30)
    python run_moca.py --tasks 1 2 3 4    # only some tasks (total out of their maximum)
    python run_moca.py --tasks 6 7 8      # only attention tasks
    python run_moca.py --tasks 9 10 11 12 13  # only language to orientation
    python run_moca.py --camera 1         # use a different webcam
"""

import argparse
import json
import os
from datetime import datetime

from moca_common import RESULTS_ROOT, TASK_MAX_SCORES, build_final_report, get_session_dir
from moca_score_sheet import build_sheet, sheet_text
from moca_tasks import ALL_TASKS, TASK_IDS, run_single_task


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", nargs="+", type=int, default=ALL_TASKS, choices=ALL_TASKS)
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()
    selected = [TASK_IDS[t] for t in sorted(set(args.tasks))]
    max_total = sum(TASK_MAX_SCORES[t] for t in selected)

    session = RESULTS_ROOT / datetime.now().strftime("session_%Y%m%d_%H%M%S")
    os.environ["MOCA_SESSION_DIR"] = str(session)
    session = get_session_dir()
    print(f"Results folder: {session}\n")

    patient = None

    results = {}

    def report_running():
        total = sum(r["score"] for r in results.values())
        done = sum(r["max_score"] for r in results.values())
        print(f"\n>>> Running total: {total} / {done} so far (out of {max_total})\n")

    for t in sorted(set(args.tasks)):
        r = run_single_task(t, cam_index=args.camera)
        if r is not None:
            results[TASK_IDS[t]] = r
        report_running()

    report = build_final_report(results, tasks=selected)
    report["session_dir"] = str(session)
    if patient:
        report["patient"] = patient
    out = session / "moca_results.json"
    out.write_text(json.dumps(report, indent=2, default=str))

    sheet = build_sheet(report, patient)
    (session / "score_sheet.json").write_text(json.dumps(sheet, indent=2, default=str))
    (session / "score_sheet.txt").write_text(sheet_text(sheet))

    s = report["summary"]
    print("=" * 64)
    print("MoCA — FINAL SCORE")
    print("=" * 64)
    if "task1_trail_making" in s:
        print(f"Task 1  Trail making : {s['task1_trail_making']} / 1")
    if "task2_cube_copy" in s:
        print(f"Task 2  Cube copy    : {s['task2_cube_copy']} / 1")
    if "task3_clock_draw" in s:
        c = s["task3_clock_draw"]
        print(f"Task 3  Clock        : {sum(c.values())} / 3   "
              f"(contour {c['contour']}, numbers {c['numbers']}, hands {c['hands']})")
    if "task4_naming" in s:
        n = s["task4_naming"]
        print(f"Task 4  Naming       : {sum(n.values())} / 3   "
              f"(lion {n['lion']}, rhino {n['rhino']}, camel {n['camel']})")
    if "task5_memory" in s:
        m = s["task5_memory"]
        print("Task 5  Memory       : not scored   " +
              "  ".join(f"{k}: {len(v)}/5 {v}" for k, v in m.items()))
    if "task6_digit_span" in s:
        d = s["task6_digit_span"]
        print(f"Task 6  Digit Span   : {sum(d.values())} / 2   "
              f"(forward {d['digits_forward']}, backward {d['digits_backward']})")
    if "task7_letters" in s:
        print(f"Task 7  Letters (A)  : {s['task7_letters']['letters_a']} / 1")
    if "task8_serial7s" in s:
        print(f"Task 8  Serial 7s    : {s['task8_serial7s']['serial7']} / 3")
    if "task9_sentence_repetition" in s:
        g = s["task9_sentence_repetition"]
        print(f"Task 9  Sentences    : {sum(g.values())} / 2   "
              f"(sentence 1 {g['sentence_1']}, sentence 2 {g['sentence_2']})")
    if "task10_fluency" in s:
        print(f"Task 10 F words      : {s['task10_fluency']['fluency']} / 1")
    if "task11_abstraction" in s:
        a2 = s["task11_abstraction"]
        print(f"Task 11 Abstraction  : {sum(a2.values())} / 2   "
              f"(train-bicycle {a2['train_bicycle']}, watch-ruler {a2['watch_ruler']})")
    if "task12_delayed_recall" in s:
        r = s["task12_delayed_recall"]
        print(f"Task 12 Delayed rec. : {sum(r.values())} / 5   "
              f"(" + ", ".join(f"{k} {v}" for k, v in r.items()) + ")")
    if "task13_orientation" in s:
        o = s["task13_orientation"]
        print(f"Task 13 Orientation  : {sum(o.values())} / 6   "
              f"(" + ", ".join(f"{k} {v}" for k, v in o.items()) + ")")
    print("-" * 64)
    for name, sec in report["sections"].items():
        if sec["max"]:
            print(f"  {name.replace('_', ' / ').title():28s} {sec['score']} / {sec['max']}")
    print(f"TOTAL                : {report['total']} / {report['max_total']}")
    for tid, r in report["tasks"].items():
        if not r.get("completed", True):
            print(f"  note: {tid} was not completed -> counted as 0")
    print(f"\nFull report saved to: {out}")
    print(f"Score sheet saved to: {session / 'score_sheet.txt'}")
    return report


if __name__ == "__main__":
    main()
