"""
The PDF report an examiner downloads for one test.

Laid out like the clinic's existing assessment reports (the MPPT reports): a patient block, a
results table with scoring criteria and clinical relevance, clinical analysis, terminology,
recommendations, an AI-written clinical summary, charts and a task-by-task analysis.

    GET /api/sessions/{id}/report.pdf     (the test's examiner only)

Built with ReportLab; the charts are drawn with matplotlib. The AI summary uses webapp/ai.py and
is left out (with a note) when no AI key is set or the service can't be reached.
"""

import io
import logging
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from fastapi import APIRouter, Depends  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.lib.fonts import addMapping  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate,  # noqa: E402
                                Spacer, Table, TableStyle)
from sqlalchemy.orm import Session  # noqa: E402

from moca_tasks import TASK_IDS, TASK_INFO  # noqa: E402

from . import ai, sessions, storage  # noqa: E402
from .auth import current_examiner, get_db  # noqa: E402
from .db import Examiner  # noqa: E402

log = logging.getLogger("moca")
router = APIRouter(prefix="/api")

# --------------------------------------------------------------------------
# What each task measures (from the MoCA administration and scoring instructions)
# --------------------------------------------------------------------------
TASK_TEXT = {
    1: (["1-A-2-B-3-C-4-D-5-E with no crossing lines: 1pt",
         "Any error not immediately self-corrected: 0pts"],
        "Assesses executive function, set-shifting and visual sequencing. Errors may indicate "
        "frontal-subcortical dysfunction."),
    2: (["3-dimensional, all lines drawn, no extra lines, lines roughly parallel and of similar length: 1pt",
         "Any criterion missed: 0pts"],
        "Assesses visuoconstructional ability and visuospatial planning. Difficulty may indicate "
        "parietal lobe involvement."),
    3: (["Contour (circle, minor distortion acceptable): 1pt",
         "Numbers (all present, in order, placed correctly): 1pt",
         "Hands (two hands showing 11:10, hour hand shorter): 1pt"],
        "Assesses visuospatial planning, executive function and conceptual understanding of time. "
        "Sensitive to early cognitive decline."),
    4: (["Lion: 1pt", "Rhinoceros: 1pt", "Camel (or dromedary): 1pt"],
        "Assesses confrontation naming and semantic memory. Difficulty may suggest language "
        "or temporal lobe involvement."),
    5: (["Two learning trials of five words", "Not scored (no points)"],
        "Registration and encoding of new information. The words are recalled later in task 12."),
    6: (["Forward, 5 digits repeated correctly: 1pt", "Backward, 3 digits repeated correctly: 1pt"],
        "Assesses auditory attention and working memory span."),
    7: (["0 or 1 error: 1pt", "2 or more errors: 0pts"],
        "Assesses sustained attention and vigilance. Errors suggest attentional or "
        "concentration deficits."),
    8: (["4 or 5 correct subtractions: 3pts", "2 or 3 correct: 2pts", "1 correct: 1pt", "None correct: 0pts"],
        "Assesses attention, working memory and mental calculation."),
    9: (["Each sentence repeated exactly: 1pt (2 sentences)"],
        "Assesses verbal repetition, auditory comprehension and attention to detail."),
    10: (["11 or more words starting with F in 60 seconds: 1pt", "10 or fewer: 0pts"],
         "Assesses phonemic verbal fluency and executive retrieval. Low output suggests frontal "
         "lobe dysfunction."),
    11: (["Train-bicycle (means of transport): 1pt", "Watch-ruler (measuring instruments): 1pt",
          "Concrete answers: 0pts"],
         "Assesses abstract reasoning and conceptual thinking."),
    12: (["Each of the 5 words recalled without cues: 1pt"],
         "Assesses delayed episodic memory. Impaired free recall is an early marker of mild "
         "cognitive impairment."),
    13: (["Date, month, year, day, place, city: 1pt each", "The exact date and place are required"],
         "Assesses orientation to time and place. Disorientation is common in moderate cognitive "
         "impairment."),
}

DOMAINS = [
    ("visuospatial_executive", "Visuospatial / Executive", "#1b7aaf"),
    ("naming", "Naming", "#22a699"),
    ("attention", "Attention", "#f5b841"),
    ("language", "Language", "#ef7d5b"),
    ("abstraction", "Abstraction", "#8b7fd1"),
    ("delayed_recall", "Delayed Recall", "#5bb8e6"),
    ("orientation", "Orientation", "#3f9b6b"),
]

# domain -> (deficit description, recommendation strategy, intervention row)
DOMAIN_ADVICE = {
    "visuospatial_executive": (
        "Visuospatial / executive deficit - reduced planning, set-shifting or visuoconstruction",
        "Assess executive function further (for example Trail Making B) and review safety in "
        "complex daily tasks such as driving and managing medication",
        ("Executive Function Training", "Structured planning tasks, sequencing exercises, "
         "visuospatial puzzles and drawing practice", "3x/week, 20-30 minutes",
         "Improved planning, organisation and visuoconstructional ability")),
    "naming": (
        "Naming deficit - reduced confrontation naming or semantic retrieval",
        "Consider a language assessment and screen hearing and vision",
        ("Language Stimulation", "Picture naming, semantic category and word-finding exercises",
         "Daily, 10-15 minutes", "Better word retrieval and semantic access")),
    "attention": (
        "Attention deficit - reduced attention span, vigilance or working memory",
        "Review medications that affect alertness, check sleep quality and screen for delirium",
        ("Attention Training", "Digit span practice, selective attention and dual-task exercises",
         "Daily, 15-20 minutes", "Improved sustained attention and working memory")),
    "language": (
        "Language deficit - reduced repetition or verbal fluency",
        "Consider speech and language therapy review",
        ("Verbal Fluency Training", "Category and letter fluency drills, sentence repetition, "
         "conversation practice", "Daily, 10-15 minutes", "Improved verbal fluency and expression")),
    "abstraction": (
        "Abstraction deficit - concrete rather than conceptual reasoning",
        "Include abstract reasoning in further cognitive assessment",
        ("Reasoning Exercises", "Similarities, categorisation and problem-solving activities",
         "3x/week, 15-20 minutes", "Better conceptual and abstract thinking")),
    "delayed_recall": (
        "Delayed recall deficit - impaired retention or retrieval of new information",
        "Refer for a full neuropsychological memory evaluation; consider B12, thyroid and "
        "other reversible causes",
        ("Memory Strategy Training", "Spaced retrieval, association techniques, memory aids "
         "(calendars, notes, reminders)", "Daily, 15-20 minutes",
         "Improved retention and use of compensatory strategies")),
    "orientation": (
        "Orientation deficit - disorientation to time or place",
        "Evaluate further for moderate cognitive impairment and assess support at home",
        ("Orientation Support", "Reality orientation, visible calendars and clocks, consistent "
         "daily routine", "Daily, ongoing", "Better orientation and reduced confusion")),
}

TERMS = [
    ("Montreal Cognitive Assessment (MoCA)", "A 30-point screening test for mild cognitive dysfunction"),
    ("Mild Cognitive Impairment (MCI)", "Cognitive decline greater than expected for age, with daily function preserved"),
    ("Executive Function", "Planning, organising, shifting between tasks and controlling behaviour"),
    ("Visuospatial Ability", "Understanding and reproducing the position and shape of objects"),
    ("Working Memory", "Holding and using information over a few seconds"),
    ("Episodic Memory", "Memory for specific recently learned information and events"),
    ("Phonemic Fluency", "Producing words that start with a given letter"),
    ("Abstraction", "Recognising conceptual similarities between objects"),
    ("Orientation", "Awareness of the current date, time and place"),
    ("Education Adjustment", "One point added for 12 years of formal education or less"),
]

# --------------------------------------------------------------------------
# Look: matches the reference reports (grey header cells, thin black grid, boxed section titles)
# --------------------------------------------------------------------------
_fonts = {}


def _font(bold=False):
    """DejaVu Sans (ships with matplotlib) so symbols like ≥ and – print correctly."""
    name = "DejaVu-Bold" if bold else "DejaVu"
    if name not in _fonts:
        folder = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        pdfmetrics.registerFont(TTFont(name, str(folder / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"))))
        _fonts[name] = True
    return name


def _styles():
    f, fb = _font(), _font(bold=True)
    for bold, italic in ((0, 0), (1, 0), (0, 1), (1, 1)):     # so <b> and <i> work in paragraphs
        addMapping(f, bold, italic, fb if bold else f)
    return {
        "title": ParagraphStyle("title", fontName=f, fontSize=17, leading=22, alignment=TA_CENTER, spaceAfter=6),
        "subtitle": ParagraphStyle("subtitle", fontName=f, fontSize=9, leading=12, alignment=TA_CENTER,
                                   textColor=colors.HexColor("#9a9a9a"), spaceAfter=14),
        "section": ParagraphStyle("section", fontName=f, fontSize=11.5, leading=15),
        "body": ParagraphStyle("body", fontName=f, fontSize=8.6, leading=12.2, spaceAfter=5),
        "bullet": ParagraphStyle("bullet", fontName=f, fontSize=8.6, leading=12.2, spaceAfter=5),
        "label": ParagraphStyle("label", fontName=f, fontSize=8.6, leading=12.2, spaceBefore=6, spaceAfter=5),
        "cell": ParagraphStyle("cell", fontName=f, fontSize=7.3, leading=9.3),
        "cell_head": ParagraphStyle("cell_head", fontName=f, fontSize=7.8, leading=9.8, alignment=TA_CENTER),
        "info_label": ParagraphStyle("info_label", fontName=f, fontSize=8.6, leading=11, alignment=2),
        "info": ParagraphStyle("info", fontName=f, fontSize=8.6, leading=11),
        "bold": ParagraphStyle("bold", fontName=fb, fontSize=8.6, leading=12.2),
        "footer": ParagraphStyle("footer", fontName=f, fontSize=8.5, leading=11, alignment=TA_CENTER,
                                 textColor=colors.HexColor("#9a9a9a"), spaceBefore=18),
    }


GRID = colors.black
HEAD_BG = colors.HexColor("#d9d9d9")
ROW_BG = colors.HexColor("#f5f5f5")
PAGE_W = A4[0] - 30 * mm


def _section(title, st):
    """A section title in a thin box, like the reference reports."""
    t = Table([[Paragraph(escape(title), st["section"])]], colWidths=[PAGE_W * 0.86])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, GRID),
                           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    t.hAlign = "LEFT"
    return [Spacer(1, 10), t, Spacer(1, 8)]


def _grid_table(rows, widths, st, zebra=True, head=True):
    data = [[c if not isinstance(c, str) else Paragraph(escape(c), st["cell_head" if head and i == 0 else "cell"])
             for c in row] for i, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    style = [("GRID", (0, 0), (-1, -1), 0.6, GRID), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if head:
        style.append(("BACKGROUND", (0, 0), (-1, 0), HEAD_BG))
    if zebra:
        style += [("BACKGROUND", (0, r), (-1, r), ROW_BG) for r in range(2 if head else 1, len(rows), 2)]
    t.setStyle(TableStyle(style))
    return t


def _bullets(items, st):
    return [Paragraph("• " + escape(x), st["bullet"]) for x in items]


def _figure(fig, width):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    w, h = fig.get_size_inches()
    return Image(buf, width=width, height=width * h / w)


# --------------------------------------------------------------------------
# Reading the test
# --------------------------------------------------------------------------
def _age(dob, on):
    if not dob:
        return None
    born = dob if isinstance(dob, date) else datetime.fromisoformat(str(dob)).date()
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def _impression(score, max_total, completed, scored_tasks):
    """Screening band from the commonly used MoCA cut-offs (full 30-point test only)."""
    if scored_tasks and completed < scored_tasks / 2:
        return (f"Incomplete assessment: only {completed} of {scored_tasks} scored tasks were completed, so the "
                f"total of {score}/{max_total} can't be interpreted as a level of cognitive function.",
                "Missing tasks are scored 0, which may reflect skipping, technical problems or difficulty "
                "taking part rather than cognitive ability. Repeat the assessment before drawing conclusions.")
    if max_total != 30:
        pct = round(100 * score / max_total) if max_total else 0
        return (f"Partial MoCA ({score}/{max_total}, {pct}%). Only the selected tasks were given, so the "
                "standard cut-off of 26/30 does not apply.",
                "Interpret each task on its own. Give the full MoCA for an overall screening score.")
    if score >= 26:
        return ("Score within the normal range (26-30). No cognitive impairment indicated on screening.",
                "The patient's performance is consistent with normal cognitive function across the "
                "assessed domains.")
    if score >= 18:
        return ("Score in the range commonly associated with mild cognitive impairment (18-25).",
                "Performance below the normal cut-off suggests mild cognitive difficulties that warrant "
                "further clinical evaluation.")
    if score >= 10:
        return ("Score in the range commonly associated with moderate cognitive impairment (10-17).",
                "Performance indicates cognitive difficulties across several domains that warrant "
                "comprehensive clinical and neuropsychological evaluation.")
    return ("Score in the range commonly associated with severe cognitive impairment (below 10).",
            "Performance indicates marked cognitive difficulties. Comprehensive clinical evaluation and "
            "support planning are recommended.")


def _data(s):
    report, sheet, patient = sessions._report(s)
    full = report["max_total"] == sessions.FULL_TEST_POINTS
    bonus = sheet["education_bonus"] if full else 0
    total = min(report["max_total"], report["total"] + bonus)
    tasks = []
    for n in s.tasks:
        r = report["tasks"].get(TASK_IDS[n])
        if r is None:
            continue
        tasks.append({"n": n, "id": TASK_IDS[n], "title": TASK_INFO[n][0], "r": r})
    domains = [(key, label, color, report["sections"][key]["score"], report["sections"][key]["max"])
               for key, label, color in DOMAINS if report["sections"].get(key, {}).get("max", 0) > 0]
    on = s.started_at.date()
    return {"s": s, "report": report, "sheet": sheet, "patient": patient, "full": full, "bonus": bonus,
            "raw": report["total"], "total": total, "max": report["max_total"], "tasks": tasks,
            "domains": domains, "age": _age(patient.get("date_of_birth"), on), "date": on}


def _task_line(t):
    r = t["r"]
    if r["max_score"] == 0:
        status = "not scored"
    else:
        status = f"{r['score']}/{r['max_score']}"
    reason = (r.get("reason") or "").rstrip(".")
    if r.get("corrected_at"):
        reason += f". Corrected by the examiner: {r.get('correction_note') or 'no note'}"
    return f"{t['title']} ({status}): {reason or 'no details'}."


# --------------------------------------------------------------------------
# AI summary
# --------------------------------------------------------------------------
SUMMARY_SYSTEM = """You write the clinical summary section of a Montreal Cognitive Assessment (MoCA)
report for the examiner who gave the test. Use only the results provided.

Write these parts, each starting with its label in double asterisks on its own line:
**Clinical Summary**, **Visuospatial and Executive Function Assessment**, **Memory Assessment**,
**Attention, Language and Abstraction Assessment**, **Orientation Assessment**,
**Clinical Interpretation**, **Recommendations** (a numbered list of 3 to 5 practical items).

- Refer to the patient by their patient ID, never by name.
- This is a screening test scored automatically and checked by the examiner: describe findings
  and what they may suggest, don't state a diagnosis.
- Mention tasks that were skipped or not completed, since their scores of 0 may not reflect ability.
- Plain prose, no tables, about 350 to 500 words."""


def _summary_prompt(d):
    lines = [f"Patient ID: {d['s'].patient_id}",
             f"Age: {d['age'] if d['age'] is not None else 'unknown'}, sex: {d['patient'].get('sex') or 'unknown'}, "
             f"years of education: {d['patient'].get('education_years') if d['patient'].get('education_years') is not None else 'unknown'}",
             f"Total: {d['total']}/{d['max']}" + (f" (raw {d['raw']} + {d['bonus']} education point)" if d["bonus"] else ""),
             "Domains: " + "; ".join(f"{label} {sc}/{mx}" for _, label, _, sc, mx in d["domains"]),
             "Tasks:"]
    for t in d["tasks"]:
        r = t["r"]
        crit = ", ".join(f"{k}={v}" for k, v in (r.get("criteria") or {}).items())
        done = "completed" if r.get("completed") else "NOT completed"
        lines.append(f"- {t['title']}: {r['score']}/{r['max_score']}, {done}. {r.get('reason') or ''}"
                     + (f" Criteria: {crit}." if crit else ""))
    return "\n".join(lines)


def _ai_summary(d):
    if ai.provider() is None:
        return None
    try:
        return ai.complete(SUMMARY_SYSTEM, _summary_prompt(d)) or None
    except Exception as e:                 # the report is still useful without the summary
        log.error("report summary failed: %s", e)
        return None


def _summary_paragraphs(text, st):
    out = []
    for block in text.split("\n"):
        block = block.strip()
        if not block:
            continue
        safe = escape(block)
        while "**" in safe:                 # **bold** -> <b>bold</b>
            safe = safe.replace("**", "<b>", 1).replace("**", "</b>", 1) if safe.count("**") >= 2 \
                else safe.replace("**", "")
        out.append(Paragraph(safe, st["body"]))
    return out


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------
def _level(score, mx):
    if mx == 0:
        return "Not scored", "#cfcfcf"
    p = score / mx
    return (("Excellent", "#4caf50") if p == 1 else ("Good", "#8bc34a") if p >= .67
            else ("Moderate", "#ffc107") if p >= .5 else ("Poor", "#ff9800") if p > 0 else ("Very Poor", "#f44336"))


def _domain_chart(d):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    labels = [label for _, label, _, _, _ in d["domains"]]
    pct = [100 * sc / mx for _, _, _, sc, mx in d["domains"]]
    cols = [c for _, _, c, _, _ in d["domains"]]
    ax = axes[0]
    bars = ax.barh(labels[::-1], pct[::-1], color=cols[::-1], edgecolor="black", linewidth=.6)
    for b, (_, _, _, sc, mx) in zip(bars, d["domains"][::-1]):
        ax.text(b.get_width() + 1.5, b.get_y() + b.get_height() / 2, f"{sc}/{mx}", va="center", fontsize=9)
    ax.set_xlim(0, 115)
    ax.axvline(100, color="#888", ls="--", lw=.8)
    ax.set_xlabel("Score (% of maximum)")
    ax.set_title("Cognitive Domain Profile", fontweight="bold")
    ax.grid(axis="x", alpha=.3)

    ax = axes[1]
    ax.set_title(f"Overall Score: {d['total']}/{d['max']}", fontweight="bold")
    rest = max(d["max"] - d["total"], 0)
    ax.pie([d["total"], rest] if d["total"] else [1e-9, max(rest, 1)],
           colors=["#4caf50" if d["full"] and d["total"] >= 26 else "#ff9800", "#eeeeee"],
           labels=["Score", "Remaining"], autopct=lambda p: f"{p:.0f}%" if p > 0.5 else "",
           startangle=90, wedgeprops={"edgecolor": "white"})
    if d["full"]:
        ax.text(0, -1.35, "Normal range: 26 or more", ha="center", fontsize=9, color="#555")
    fig.tight_layout()
    return fig


def _trends_chart(d):
    scored = [t for t in d["tasks"] if t["r"]["max_score"] > 0]
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    fig.suptitle("Performance Trends and Clinical Indicators", fontweight="bold", fontsize=13)

    ax = axes[0][0]
    names = [t["title"] for t in scored]
    vals = [t["r"]["score"] for t in scored]
    maxes = [t["r"]["max_score"] for t in scored]
    lv = [_level(v, m) for v, m in zip(vals, maxes)]
    ax.bar(range(len(scored)), maxes, color="#eeeeee", edgecolor="#999", linewidth=.5, label="Maximum")
    ax.bar(range(len(scored)), vals, color=[c for _, c in lv], edgecolor="black", linewidth=.5)
    for i, (v, m) in enumerate(zip(vals, maxes)):
        ax.text(i, m + .08, f"{v}/{m}", ha="center", fontsize=7)
    ax.set_xticks(range(len(scored)))
    ax.set_xticklabels(names, rotation=50, ha="right", fontsize=7)
    ax.set_ylabel("Points")
    ax.set_title("MoCA Score Distribution\n(Color-coded Performance Levels)", fontsize=10)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=c, label=n) for n, c in [("Excellent", "#4caf50"), ("Good", "#8bc34a"),
              ("Moderate", "#ffc107"), ("Poor", "#ff9800"), ("Very Poor", "#f44336")]], fontsize=6, loc="upper right")
    ax.set_ylim(0, max(maxes or [1]) + .8)
    ax.grid(axis="y", alpha=.3)

    ax = axes[0][1]
    done = sum(1 for t in d["tasks"] if t["r"].get("completed"))
    skipped = len(d["tasks"]) - done
    ax.pie([done, skipped] if skipped else [done], labels=["Completed", "Not completed"][: 2 if skipped else 1],
           colors=["#5bb8e6", "#f44336"][: 2 if skipped else 1], autopct="%1.0f%%", startangle=90,
           wedgeprops={"edgecolor": "white"})
    ax.set_title(f"Task Completion\n{done} of {len(d['tasks'])} tasks completed", fontsize=10)

    ax = axes[1][0]
    deficit = [(label, 100 * (mx - sc) / mx) for _, label, _, sc, mx in d["domains"]]
    ax.bar([x[0] for x in deficit], [x[1] for x in deficit],
           color=["#f44336" if v >= 50 else "#ff9800" if v > 0 else "#4caf50" for _, v in deficit],
           edgecolor="black", linewidth=.5)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Points missed (%)")
    ax.set_title("Clinical Risk Assessment\n(Points Missed per Domain)", fontsize=10)
    ax.tick_params(axis="x", rotation=40, labelsize=7)
    ax.grid(axis="y", alpha=.3)

    ax = axes[1][1]
    pri = [(label, 0 if sc == mx else 1 if sc / mx >= .67 else 2 if sc / mx >= .34 else 3)
           for _, label, _, sc, mx in d["domains"]]
    ax.scatter(range(len(pri)), [p for _, p in pri], s=120,
               c=[["#4caf50", "#ffc107", "#ff9800", "#f44336"][p] for _, p in pri], edgecolors="black")
    ax.set_xticks(range(len(pri)))
    ax.set_xticklabels([x for x, _ in pri], rotation=40, ha="right", fontsize=7)
    ax.set_yticks(range(4))
    ax.set_yticklabels(["None", "Low", "Medium", "High"])
    ax.set_ylim(-.5, 3.5)
    ax.set_title("Follow-up Priority Matrix\n(Higher = More Urgent)", fontsize=10)
    ax.grid(alpha=.3)
    fig.tight_layout()
    return fig


def _criteria_chart(d):
    rows = [(t["title"], t["r"]["criteria"]) for t in d["tasks"] if t["r"].get("criteria")]
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(11, .45 * len(rows) + 1.4))
    for y, (title, crit) in enumerate(rows):
        for x, (k, v) in enumerate(crit.items()):
            mx = 3 if k == "serial7" else 1
            ax.add_patch(plt.Rectangle((x, y), .95, .85, color="#4caf50" if v >= mx else "#ffc107" if v else "#f44336"))
            ax.text(x + .47, y + .42, f"{k.replace('_', ' ')}\n{v}/{mx}", ha="center", va="center", fontsize=6.5)
    ax.set_xlim(0, max(len(c) for _, c in rows))
    ax.set_ylim(len(rows), 0)
    ax.set_yticks([i + .42 for i in range(len(rows))])
    ax.set_yticklabels([t for t, _ in rows], fontsize=8)
    ax.set_xticks([])
    ax.set_title("Item-Level Analysis (green = full marks, amber = partial, red = missed)", fontweight="bold", fontsize=10)
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    return fig


def _drawings(d):
    """The patient's drawings (trail making, cube, clock photos), when they can be found."""
    out = []
    s = d["s"]
    for r in sorted(s.results, key=lambda r: r.task_id):
        for f in r.evidence_files or []:
            name = Path(f).name
            if not name.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            path = Path(s.folder) / name
            data = path.read_bytes() if path.is_file() else storage.download(s.folder, name)
            if data:
                out.append((r.task_id, name, _shrink(data)))
    return out[:6]


DRAWING_MAX_PX = 1000     # printed about 80 mm wide, so this is still sharp


def _shrink(data):
    """A smaller JPEG of a photo. Full-size camera PNGs are about 2 MB each and pushed the PDF past
    Vercel's 4.5 MB response limit."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return data
    h, w = img.shape[:2]
    if w > DRAWING_MAX_PX:
        img = cv2.resize(img, (DRAWING_MAX_PX, round(h * DRAWING_MAX_PX / w)), interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return jpg.tobytes() if ok else data


# --------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------
def build_pdf(s):
    d = _data(s)
    st = _styles()
    story = []

    # --- title and patient block
    story += [Paragraph("MoCA Cognitive Assessment Report", st["title"]),
              Paragraph("Comprehensive Clinical Analysis with AI-Enhanced Assessment", st["subtitle"])]
    examiner = s.examiner
    total_text = f"{d['total']}/{d['max']}" + (f"  ({d['raw']} + 1 education point)" if d["bonus"] else "")
    info = [("Patient ID", str(s.patient_id)), ("Patient Name", d["patient"].get("name") or ""),
            ("Age / Sex", f"{d['age'] if d['age'] is not None else '-'} / {d['patient'].get('sex') or '-'}"),
            ("Education", f"{d['patient'].get('education_years')} years" if d["patient"].get("education_years") is not None else "-"),
            ("Assessment Date", d["date"].strftime("%B %d, %Y")),
            ("Examiner", ", ".join(x for x in (examiner.name, examiner.title) if x)),
            ("Clinical Context", f"MoCA Assessment - {sum(1 for t in d['tasks'] if t['r'].get('completed'))} "
                                 f"of {len(d['tasks'])} tasks completed"),
            ("Total MoCA Score", total_text)]
    t = Table([[Paragraph(escape(a), st["info_label"]), Paragraph(escape(b), st["info"])] for a, b in info],
              colWidths=[38 * mm, 82 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, GRID), ("BACKGROUND", (0, 0), (0, -1), HEAD_BG),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [t]

    # --- results table
    story += _section("Complete MoCA Assessment Results", st)
    rows = [["Task", "MoCA Assessment Task", "Score", "Scoring Criteria", "Clinical Relevance"]]
    for tk in d["tasks"]:
        r = tk["r"]
        crit, rel = TASK_TEXT[tk["n"]]
        score = "Not scored" if r["max_score"] == 0 else f"{r['score']}/{r['max_score']}"
        if not r.get("completed"):
            score += "\n(not completed)"
        rows.append([f"#{tk['n']}", tk["title"], score, "\n".join("• " + c for c in crit), rel])
    rows = [[Paragraph(escape(c).replace("\n", "<br/>"), st["cell_head" if i == 0 else "cell"]) for c in row]
            for i, row in enumerate(rows)]
    story += [_grid_table(rows, [11 * mm, 30 * mm, 18 * mm, 58 * mm, 58 * mm], st)]

    # --- clinical analysis
    scored_tasks = [tk for tk in d["tasks"] if tk["r"]["max_score"] > 0]
    primary, interpretation = _impression(d["total"], d["max"],
                                          sum(1 for tk in scored_tasks if tk["r"].get("completed")), len(scored_tasks))
    incomplete = primary.startswith("Incomplete")
    weak = [(key, label, sc, mx) for key, label, _, sc, mx in d["domains"] if sc < mx]
    story += _section("Technical Medical Analysis & Clinical Diagnosis", st)
    story += [Paragraph("CLINICAL DIAGNOSIS:", st["label"]),
              Paragraph("Primary Diagnosis: " + escape(primary), st["body"]),
              Paragraph("Clinical Interpretation: " + escape(interpretation), st["body"]),
              Paragraph("CURRENT PROBLEMS IDENTIFIED:", st["label"])]
    story += _bullets([f"{DOMAIN_ADVICE[k][0]} (Score: {sc}/{mx})" for k, _, sc, mx in weak]
                      or ["No significant deficits identified in the assessed cognitive domains"], st)
    skipped = [tk["title"] for tk in d["tasks"] if not tk["r"].get("completed")]
    if skipped:
        story += _bullets([f"Tasks not completed, scored 0 and may not reflect ability: {', '.join(skipped)}"], st)
    story += [Paragraph("MEDICAL RECOMMENDATION STRATEGIES:", st["label"])]
    recs = [DOMAIN_ADVICE[k][1] for k, _, _, _ in weak]
    if incomplete:
        recs = ["Repeat the MoCA under supervised conditions before interpreting the results"] + recs
    elif d["full"] and d["total"] < 26:
        recs += ["Screen for depression (for example the Geriatric Depression Scale) and review medications",
                 "Repeat the MoCA in 6 to 12 months to monitor change, using an alternate version"]
    else:
        recs += ["Maintain cognitive, physical and social activity",
                 "Repeat screening if new concerns arise or as part of routine follow-up"]
    story += _bullets(recs, st)
    story += [Paragraph("<i>This is a screening result. It supports, but does not replace, a clinical diagnosis "
                        "by a qualified professional.</i>", st["body"])]

    # --- terminology
    story += _section("Medical Terminology & Clinical Context", st)
    story += [_grid_table([["Medical Term", "Definition"]] + [list(x) for x in TERMS], [62 * mm, 113 * mm], st)]

    # --- recommendations
    story += _section("Evidence-Based Cognitive Recommendations", st)
    story += [Paragraph("COGNITIVE ASSESSMENT: Based on individual MoCA task analysis, the following results "
                        "were identified:", st["body"])]
    story += _bullets([f"{tk['title']} - Score: " + ("not scored" if tk["r"]["max_score"] == 0 else
                       f"{tk['r']['score']}/{tk['r']['max_score']}") +
                       ("" if tk["r"]["max_score"] == 0 else
                        " (Within expected performance)" if tk["r"]["score"] == tk["r"]["max_score"] else
                        " (Deficit requiring follow-up)") for tk in d["tasks"]], st)
    plan = [list(DOMAIN_ADVICE[k][2]) for k, _, _, _ in weak] or [
        ["Cognitive Maintenance", "Reading, puzzles, learning new skills, social engagement",
         "Daily, 20-30 minutes", "Maintain current cognitive function"]]
    story += [Spacer(1, 4),
              _grid_table([["Category", "Specific Intervention", "Frequency & Duration", "Expected Outcomes"]] + plan,
                          [36 * mm, 64 * mm, 34 * mm, 41 * mm], st),
              Paragraph("Clinical Notes:", st["label"])]
    story += _bullets(["Confirm automatically scored items against the recordings and drawings before release",
                       "Consider hearing, vision, mood and education level when interpreting the score",
                       "Involve family or caregivers in follow-up where appropriate",
                       "Reassess every 6 to 12 months, or sooner if there are new concerns"], st)

    # --- AI summary
    story += _section("AI-Generated Clinical Summary & Recommendations", st)
    summary = _ai_summary(d)
    story += (_summary_paragraphs(summary, st) if summary else
              [Paragraph("The AI summary isn't available for this report (no AI key is set, or the service "
                         "couldn't be reached). All other sections are complete.", st["body"])])

    # --- charts
    story += [PageBreak()]
    story += _section("Graph Analysis and Performance Assessment", st)
    story += _section("Task-Specific Performance Analysis", st)
    story += [Paragraph("The following graphs show performance for each cognitive domain and task based on "
                        "the automatically scored results.", st["body"]),
              _figure(_domain_chart(d), PAGE_W)]
    crit_fig = _criteria_chart(d)
    if crit_fig:
        story += [Spacer(1, 8), _figure(crit_fig, PAGE_W)]
    story += [PageBreak(), _figure(_trends_chart(d), PAGE_W)]

    drawings = _drawings(d)
    if drawings:
        story += _section("Patient Drawings", st)
        cells = []
        for task_id, name, data in drawings:
            try:
                img = Image(io.BytesIO(data))
                ratio = img.imageHeight / img.imageWidth
                img.drawWidth, img.drawHeight = 80 * mm, 80 * mm * ratio
                if img.drawHeight > 75 * mm:
                    img.drawHeight, img.drawWidth = 75 * mm, 75 * mm / ratio
                # a plain list: KeepTogether reports a huge height to force a page break, which a table
                # cell takes literally (LayoutError on every test with a cube or clock photo)
                cells.append([img, Paragraph(escape(name), st["cell"])])
            except Exception as e:
                log.error("report: could not add %s: %s", name, e)
        grid = [cells[i:i + 2] + [""] * (2 - len(cells[i:i + 2])) for i in range(0, len(cells), 2)]
        if grid:
            story += [Table(grid, colWidths=[PAGE_W / 2] * 2)]

    # --- task by task
    story += _section("Detailed Clinical Analysis:", st)
    story += _bullets([_task_line(tk) for tk in d["tasks"]], st)
    story += [Paragraph("Generated by MoCA AutoScoring System | AI-Assisted Scoring | Reviewed by the Examiner",
                        st["footer"])]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm,
                            title=f"MoCA Assessment Report - Patient {s.patient_id}", author="MoCA AutoScoring")
    doc.build(story)
    return buf.getvalue()


@router.get("/sessions/{session_id}/report.pdf")
def report_pdf(session_id: int, examiner: Examiner = Depends(current_examiner), db: Session = Depends(get_db)):
    s = sessions._examiner_session(db, session_id, examiner)
    pdf = build_pdf(s)
    name = f"assessment_report_{s.started_at:%Y%m%d_%H%M%S}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"',
                             "Cache-Control": "private, no-store"})
