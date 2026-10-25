"""
MoCA score sheet (no windows): arranges the task scores in the same order and boxes as
the paper MoCA form.

  * build_sheet(report, patient) -- sections and totals, as on the paper form
                                    (Visuospatial/Executive /5, Naming /3, Attention /6,
                                    Language /3, Abstraction /2, Delayed recall /5,
                                    Orientation /6, total /30, plus the education point).
  * sheet_text(sheet)            -- the sheet as plain text (saved as score_sheet.txt).
"""

from moca_common import MAX_TOTAL_SCORE

HEADER = "MONTREAL COGNITIVE ASSESSMENT (MOCA)"


# --------------------------------------------------------------------------
# 2. Score sheet laid out like the paper form
# --------------------------------------------------------------------------
# (section title, section key used in the report, max, [(label, task_id, criterion or None, max)])
PAPER_SECTIONS = [
    ("VISUOSPATIAL / EXECUTIVE", "visuospatial_executive", 5, [
        ("Trail making (1-A-2-B-3-C-4-D-5-E)", "task1_trail_making", None, 1),
        ("Copy cube", "task2_cube_copy", None, 1),
        ("Clock: contour", "task3_clock_draw", "contour", 1),
        ("Clock: numbers", "task3_clock_draw", "numbers", 1),
        ("Clock: hands", "task3_clock_draw", "hands", 1),
    ]),
    ("NAMING", "naming", 3, [
        ("Lion", "task4_naming", "lion", 1),
        ("Rhino", "task4_naming", "rhino", 1),
        ("Camel", "task4_naming", "camel", 1),
    ]),
    ("ATTENTION", "attention", 6, [
        ("Digits forward", "task6_digit_span", "digits_forward", 1),
        ("Digits backward", "task6_digit_span", "digits_backward", 1),
        ("Letters (tap at A)", "task7_letters", "letters_a", 1),
        ("Serial 7 subtraction", "task8_serial7s", "serial7", 3),
    ]),
    ("LANGUAGE", "language", 3, [
        ("Repeat: sentence 1", "task9_sentence_repetition", "sentence_1", 1),
        ("Repeat: sentence 2", "task9_sentence_repetition", "sentence_2", 1),
        ("Fluency: F words (11 or more)", "task10_fluency", "fluency", 1),
    ]),
    ("ABSTRACTION", "abstraction", 2, [
        ("Train - bicycle", "task11_abstraction", "train_bicycle", 1),
        ("Watch - ruler", "task11_abstraction", "watch_ruler", 1),
    ]),
    ("DELAYED RECALL", "delayed_recall", 5, [
        ("FACE", "task12_delayed_recall", "face", 1),
        ("VELVET", "task12_delayed_recall", "velvet", 1),
        ("CHURCH", "task12_delayed_recall", "church", 1),
        ("DAISY", "task12_delayed_recall", "daisy", 1),
        ("RED", "task12_delayed_recall", "red", 1),
    ]),
    ("ORIENTATION", "orientation", 6, [
        ("Date", "task13_orientation", "date", 1),
        ("Month", "task13_orientation", "month", 1),
        ("Year", "task13_orientation", "year", 1),
        ("Day", "task13_orientation", "day", 1),
        ("Place", "task13_orientation", "place", 1),
        ("City", "task13_orientation", "city", 1),
    ]),
]


def _item_score(report, task_id, criterion, max_points):
    """Score of one line of the form. Missing tasks count as 0."""
    r = report["tasks"].get(task_id)
    if r is None:
        return 0
    if criterion is None:
        return int(r["score"])
    crit = r.get("criteria") or {}
    return int(crit.get(criterion, 0))


def build_sheet(report, patient=None):
    sections = []
    for title, key, max_pts, items in PAPER_SECTIONS:
        rows = [{"label": lab, "score": _item_score(report, tid, crit, mx), "max": mx}
                for lab, tid, crit, mx in items]
        total = sum(r["score"] for r in rows)
        sections.append({"title": title, "key": key, "max": max_pts, "score": total, "rows": rows})
    total = sum(s["score"] for s in sections)
    education = (patient or {}).get("education_years")
    bonus = 1 if education is not None and education <= 12 else 0
    return {"patient": patient or {}, "sections": sections, "total": total,
            "max_total": MAX_TOTAL_SCORE, "education_bonus": bonus,
            "adjusted_total": min(MAX_TOTAL_SCORE, total + bonus),
            "memory_recall": _memory_recall(report),
            "tasks_not_completed": [t for t, r in report["tasks"].items() if not r.get("completed", True)]}


def _memory_recall(report):
    """Memory is not scored; the 2 learning trials are listed for the examiner."""
    trials = report.get("summary", {}).get("task5_memory")
    return trials or {}


def sheet_text(sheet):
    p = sheet["patient"]
    lines = [HEADER, "=" * len(HEADER)]
    if p:
        lines += [f"Name           : {p.get('name', '')}",
                  f"Education      : {p.get('education_years', '')} years",
                  f"Sex            : {p.get('sex', '')}",
                  f"Date of birth  : {p.get('date_of_birth', '')}",
                  f"Date of test   : {p.get('test_date', '')}", ""]
    for s in sheet["sections"]:
        lines.append(f"{s['title']:<26} {s['score']} / {s['max']}")
        for r in s["rows"]:
            lines.append(f"    {r['label']:<34} {r['score']} / {r['max']}")
    if sheet["memory_recall"]:
        recalled = "; ".join(f"{k} {len(v) if isinstance(v, list) else v}" for k, v in sheet["memory_recall"].items())
        lines.append(f"MEMORY (not scored)     learning trials: {recalled}")
    lines += ["", f"TOTAL                    {sheet['total']} / {sheet['max_total']}"]
    if sheet["education_bonus"]:
        lines.append(f"Add 1 point (education 12 years or less): {sheet['adjusted_total']} / {sheet['max_total']}")
    for t in sheet["tasks_not_completed"]:
        lines.append(f"note: {t} was not completed -> counted as 0")
    return "\n".join(lines)
