"""
Tests being taken and their results.

A patient starts a test from an examiner's template and takes it. The patient gets no
scores while taking it, or afterwards until the examiner has reviewed and released them.
An examiner only ever sees tests taken with them.
"""

import asyncio
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moca_common import (DEFAULT_CRITERIA, RESULTS_ROOT, TASK_MAX_SCORES, build_final_report,
                         make_task_result)
from moca_score_sheet import build_sheet, sheet_text
from moca_tasks import TASK_IDS

from . import storage
from . import web_tasks as wt
from .auth import current_examiner, current_patient, current_user, get_db
from .db import (Examiner, Patient, PatientInvite, SessionLocal, TaskResult, TestSession, TestTemplate, User, iso,
                 max_points, utcnow)
from .listen import answers

router = APIRouter(prefix="/api")

MAX_PHOTO_BYTES = 25 * 1024 * 1024
FULL_TEST_POINTS = 30


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _patient_session(db, session_id, patient):
    s = db.get(TestSession, session_id)
    if s is None or s.patient_id != patient.id:
        raise HTTPException(404, "test not found")
    return s


def _examiner_session(db, session_id, examiner):
    s = db.get(TestSession, session_id)
    if s is None or s.examiner_id != examiner.id:
        raise HTTPException(404, "test not found")
    return s


def _taking(db, session_id, patient):
    """The patient's test, while it can still be taken."""
    s = _patient_session(db, session_id, patient)
    if s.status != "in_progress":
        raise HTTPException(409, "this test is already finished")
    return s


def _check_task(s, number):
    if number not in s.tasks:
        raise HTTPException(400, f"task {number} is not part of this test")


def _file_url(session_id, path):
    return f"/api/sessions/{session_id}/files/{Path(path).name}"


def _result_out(session_id, r):
    out = dict(r)
    out["evidence_urls"] = [_file_url(session_id, p) for p in r.get("evidence_files") or []]
    del out["evidence_files"]
    return out


def _store_result(session_id, folder, std):
    """Insert or replace the task's row, then copy its files to storage."""
    with SessionLocal() as db:
        row = db.scalar(select(TaskResult).where(TaskResult.session_id == session_id,
                                                 TaskResult.task_id == std["task"]))
        if row is None:
            row = TaskResult(session_id=session_id, task_id=std["task"])
            db.add(row)
        row.score, row.max_score = std["score"], std["max_score"]
        row.criteria, row.reason = std["criteria"], std["reason"]
        row.details = json.loads(json.dumps(std["details"], default=str))
        row.evidence_files = std["evidence_files"]
        row.completed = std["completed"]
        row.created_at = utcnow()
        db.commit()
    for path in std["evidence_files"]:
        storage.upload(folder, path)
    return {"task": std["task"], "saved": True}      # the score stays with the examiner


def _report(s):
    """Final report + paper-form score sheet from the session's stored results."""
    selected = [TASK_IDS[n] for n in s.tasks]
    results = {r.task_id: r.to_result() for r in s.results if r.task_id in selected}
    report = build_final_report(results, tasks=selected)
    patient = s.patient.sheet_info(s.started_at.date().isoformat())
    sheet = build_sheet(report, patient)
    return report, sheet, patient


def _apply_totals(s):
    """Set the totals from the task results and write the report files."""
    report, sheet, patient = _report(s)
    report["session_dir"] = s.folder
    report["patient"] = patient
    folder = Path(s.folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "moca_results.json").write_text(json.dumps(report, indent=2, default=str))
    (folder / "score_sheet.json").write_text(json.dumps(sheet, indent=2, default=str))
    (folder / "score_sheet.txt").write_text(sheet_text(sheet))
    s.total, s.max_total = sheet["total"], report["max_total"]
    # the education point belongs to the full 30-point test only
    s.education_bonus = sheet["education_bonus"] if report["max_total"] == FULL_TEST_POINTS else 0
    s.adjusted_total = min(report["max_total"], sheet["total"] + s.education_bonus)
    for name in ("moca_results.json", "score_sheet.json", "score_sheet.txt"):
        storage.upload(s.folder, folder / name)


def _stage(s):
    if s.status != "finished":
        return "in_progress"
    return "released" if s.released_at else "awaiting_review"


def _examiner_out(s, with_results=True):
    out = {**s.to_dict(), "stage": _stage(s), "patient": s.patient.to_dict(),
           "done_tasks": [n for n in s.tasks if any(r.task_id == TASK_IDS[n] for r in s.results)]}
    if with_results:
        report, sheet, _ = _report(s)
        out["report"] = {**report, "tasks": {k: _result_out(s.id, v)
                                             for k, v in report["tasks"].items()}}
        out["sheet"] = sheet
    return out


def _patient_out(s):
    """What a patient may see: progress always, the score only once it is released."""
    out = {"id": s.id, "template_name": s.template_name, "tasks": s.tasks, "settings": s.settings,
           "stage": _stage(s), "started_at": iso(s.started_at), "finished_at": iso(s.finished_at),
           "examiner": s.examiner.to_dict(),
           "done_tasks": [n for n in s.tasks if any(r.task_id == TASK_IDS[n] for r in s.results)]}
    if s.released_at:
        report, sheet, _ = _report(s)
        out["result"] = {"total": s.total, "education_bonus": s.education_bonus,
                         "adjusted_total": s.adjusted_total, "max_total": s.max_total,
                         "released_at": iso(s.released_at), "note": s.review_note,
                         "sections": report["sections"], "sheet_sections": sheet["sections"]}
    return out


# --------------------------------------------------------------------------
# Patient: taking a test
# --------------------------------------------------------------------------
class SessionIn(BaseModel):
    template_id: int
    consent: bool
    timezone: str = "UTC"


def _timezone(name):
    try:
        ZoneInfo(name)
        return name
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return "UTC"


@router.post("/sessions")
def create_session(body: SessionIn, patient: Patient = Depends(current_patient),
                   db: Session = Depends(get_db)):
    if not body.consent:
        raise HTTPException(400, "please agree to the recording of your answers first")
    if patient.education_years is None:
        raise HTTPException(400, "please add your years of education to your profile first")
    t = db.get(TestTemplate, body.template_id)
    if t is None or not t.published or t.archived or t.examiner.user.deactivated_at:
        raise HTTPException(404, "test not found")
    invited = set(db.scalars(select(PatientInvite.examiner_id).where(PatientInvite.patient_id == patient.id)))
    if invited and t.examiner_id not in invited:
        raise HTTPException(404, "test not found")        # invited patients test with their own examiners
    now = utcnow()
    folder = RESULTS_ROOT / f"session_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True)
    (folder / "patient.json").write_text(json.dumps(patient.sheet_info(now.date().isoformat()), indent=2))
    s = TestSession(patient_id=patient.id, examiner_id=t.examiner_id, template_id=t.id,
                    template_name=t.name, folder=str(folder), tasks=t.tasks, settings=t.settings,
                    timezone=_timezone(body.timezone), consented_at=now, started_at=now,
                    max_total=max_points(t.tasks))
    db.add(s)
    db.commit()
    return _patient_out(s)


@router.post("/sessions/{session_id}/finish")
def finish_session(session_id: int, patient: Patient = Depends(current_patient),
                   db: Session = Depends(get_db)):
    s = _taking(db, session_id, patient)
    _apply_totals(s)
    s.status, s.finished_at = "finished", utcnow()
    db.commit()
    answers.pop(session_id, None)
    return _patient_out(s)


@router.post("/sessions/{session_id}/tasks/{number}/finish")
def finish_spoken_task(session_id: int, number: int, patient: Patient = Depends(current_patient),
                       db: Session = Depends(get_db)):
    s = _taking(db, session_id, patient)
    _check_task(s, number)
    given = answers.get(session_id, {}).get(number, {})
    # the date the patient should say is the one where they are, not where the server is
    local_now = datetime.now(ZoneInfo(s.timezone)).replace(tzinfo=None)
    try:
        std = wt.finish_task(number, given, s.folder, local_now)
    except wt.MissingAnswers as e:
        raise HTTPException(400, str(e))
    answers.get(session_id, {}).pop(number, None)
    return _store_result(session_id, s.folder, std)


@router.post("/sessions/{session_id}/tasks/{number}/skip")
def skip_task(session_id: int, number: int, patient: Patient = Depends(current_patient),
              db: Session = Depends(get_db)):
    """Skipped: the task counts as 0 and is listed as not completed."""
    s = _taking(db, session_id, patient)
    _check_task(s, number)
    task_id = TASK_IDS[number]
    std = make_task_result(task_id, 0, reason="skipped by the patient", completed=False,
                           criteria=DEFAULT_CRITERIA.get(task_id))
    answers.get(session_id, {}).pop(number, None)
    return _store_result(session_id, s.folder, std)


@router.post("/sessions/{session_id}/tasks/{number}/photo")
async def task_photo(session_id: int, number: int, file: UploadFile = File(...),
                     patient: Patient = Depends(current_patient), db: Session = Depends(get_db)):
    if number not in (2, 3):
        raise HTTPException(400, "only tasks 2 and 3 take a photo")
    s = _taking(db, session_id, patient)
    _check_task(s, number)
    folder = Path(s.folder)
    data = await file.read()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "the photo is too large")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "could not read the photo")
    path = folder / wt.photo_name(number)
    cv2.imwrite(str(path), img)
    std = await asyncio.to_thread(wt.score_photo, number, path, folder)
    return await asyncio.to_thread(_store_result, session_id, s.folder, std)


@router.post("/sessions/{session_id}/tasks/7/letters")
def task_letters(session_id: int, data: dict, patient: Patient = Depends(current_patient),
                 db: Session = Depends(get_db)):
    s = _taking(db, session_id, patient)
    _check_task(s, 7)
    try:
        std = wt.score_letters(data, s.folder)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _store_result(session_id, s.folder, std)


# --------------------------------------------------------------------------
# Reading tests: each role gets its own view
# --------------------------------------------------------------------------
@router.get("/sessions")
def list_sessions(limit: int = 50, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "admin":
        raise HTTPException(403, "administrators can't see test results")
    limit = max(1, min(limit, 200))
    stmt = select(TestSession).order_by(TestSession.started_at.desc()).limit(limit)
    if user.role == "patient":
        rows = db.scalars(stmt.where(TestSession.patient_id == user.patient.id))
        return [_patient_out(s) for s in rows]
    rows = db.scalars(stmt.where(TestSession.examiner_id == user.examiner.id))
    return [_examiner_out(s, with_results=False) for s in rows]


@router.get("/sessions/{session_id}")
def get_session(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "admin":
        raise HTTPException(403, "administrators can't see test results")
    if user.role == "patient":
        return _patient_out(_patient_session(db, session_id, user.patient))
    return _examiner_out(_examiner_session(db, session_id, user.examiner))


# --------------------------------------------------------------------------
# Examiner: patients, review, release
# --------------------------------------------------------------------------
@router.get("/stats")
def stats(examiner: Examiner = Depends(current_examiner), db: Session = Depends(get_db)):
    mine = TestSession.examiner_id == examiner.id
    finished = TestSession.status == "finished"
    return {"patients": db.scalar(select(func.count(func.distinct(TestSession.patient_id))).where(mine)),
            "awaiting_review": db.scalar(select(func.count(TestSession.id))
                                         .where(mine, finished, TestSession.released_at.is_(None))),
            "released": db.scalar(select(func.count(TestSession.id))
                                  .where(mine, TestSession.released_at.is_not(None))),
            "in_progress": db.scalar(select(func.count(TestSession.id)).where(mine, ~finished)),
            "average_full": db.scalar(select(func.avg(TestSession.adjusted_total))
                                      .where(mine, finished, TestSession.max_total == FULL_TEST_POINTS))}


def _patient_ids(examiner):
    """Patients who took a test with this examiner, or joined through one of their links."""
    tested = select(TestSession.patient_id.label("pid")).where(TestSession.examiner_id == examiner.id)
    invited = select(PatientInvite.patient_id.label("pid")).where(PatientInvite.examiner_id == examiner.id,
                                                                  PatientInvite.patient_id.is_not(None))
    return select(Patient.id).where(Patient.id.in_(tested.union(invited)))


@router.get("/patients")
def list_patients(q: str = "", examiner: Examiner = Depends(current_examiner),
                  db: Session = Depends(get_db)):
    """Patients who have taken a test with this examiner."""
    stmt = select(Patient).where(Patient.id.in_(_patient_ids(examiner))).order_by(Patient.name)
    if q.strip():
        stmt = stmt.where(Patient.name.ilike(f"%{q.strip()}%"))
    out = []
    for p in db.scalars(stmt):
        mine = [s for s in p.sessions if s.examiner_id == examiner.id]
        out.append({**p.to_dict(), "tests": len(mine),
                    "last_test": _examiner_out(mine[0], with_results=False) if mine else None})
    return out


@router.get("/patients/{patient_id}")
def get_patient(patient_id: int, examiner: Examiner = Depends(current_examiner),
                db: Session = Depends(get_db)):
    p = db.get(Patient, patient_id)
    if p is None or not db.scalar(select(func.count()).select_from(
            _patient_ids(examiner).where(Patient.id == patient_id).subquery())):
        raise HTTPException(404, "patient not found")
    mine = [s for s in p.sessions if s.examiner_id == examiner.id]
    return {**p.to_dict(), "sessions": [_examiner_out(s, with_results=False) for s in mine]}


class CorrectionIn(BaseModel):
    score: int | None = None                  # tasks scored as a whole (1 and 2)
    criteria: dict[str, int] | None = None    # every other scored task, item by item
    note: str = Field(min_length=1, max_length=1000)


@router.patch("/sessions/{session_id}/tasks/{number}")
def correct_task(session_id: int, number: int, body: CorrectionIn,
                 examiner: Examiner = Depends(current_examiner), db: Session = Depends(get_db)):
    """Correct an automatic score. The original score is kept next to the correction."""
    s = _examiner_session(db, session_id, examiner)
    _check_task(s, number)
    if s.status != "finished" or s.released_at:
        raise HTTPException(409, "only finished tests that aren't released yet can be corrected")
    task_id = TASK_IDS[number]
    if TASK_MAX_SCORES[task_id] == 0:
        raise HTTPException(400, "this task isn't scored")
    row = next((r for r in s.results if r.task_id == task_id), None)
    if row is None:
        row = TaskResult(session_id=s.id, task_id=task_id, score=0, max_score=TASK_MAX_SCORES[task_id],
                         criteria=DEFAULT_CRITERIA.get(task_id), reason="task not completed",
                         details={}, evidence_files=[], completed=False)
        s.results.append(row)
    expected = DEFAULT_CRITERIA.get(task_id)
    if expected is None:
        criteria, score = None, body.score
    else:
        criteria = body.criteria or {}
        if set(criteria) != set(expected):
            raise HTTPException(400, f"give a score for each of: {', '.join(expected)}")
        score = sum(criteria.values())
    if score is None:
        raise HTTPException(400, "give a score")
    try:
        make_task_result(task_id, score, criteria=criteria)      # checks the ranges
    except ValueError as e:
        raise HTTPException(400, str(e))
    if row.corrected_at is None:
        row.auto_score, row.auto_criteria = row.score, row.criteria
    row.score, row.criteria = score, criteria
    row.corrected_at, row.correction_note = utcnow(), body.note.strip()
    db.flush()
    _apply_totals(s)
    db.commit()
    return _examiner_out(s)


class ReleaseIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


@router.post("/sessions/{session_id}/release")
def release(session_id: int, body: ReleaseIn, examiner: Examiner = Depends(current_examiner),
            db: Session = Depends(get_db)):
    """Show the reviewed result to the patient. Final: corrections stop here."""
    s = _examiner_session(db, session_id, examiner)
    if s.status != "finished":
        raise HTTPException(409, "the patient hasn't finished this test yet")
    if s.released_at:
        raise HTTPException(409, "this result is already released")
    s.released_at, s.review_note = utcnow(), (body.note or "").strip() or None
    db.commit()
    return _examiner_out(s)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, examiner: Examiner = Depends(current_examiner),
                   db: Session = Depends(get_db)):
    """Permanently remove a test, with its recordings and photos."""
    s = _examiner_session(db, session_id, examiner)
    folder = Path(s.folder)
    names = [p.name for p in folder.iterdir()] if folder.is_dir() else []
    names += [Path(f).name for r in s.results for f in r.evidence_files]
    db.delete(s)
    db.commit()
    answers.pop(session_id, None)
    storage.delete_folder(folder, sorted(set(names)))
    shutil.rmtree(folder, ignore_errors=True)
    return {"deleted": session_id}


@router.get("/sessions/{session_id}/files/{name}")
def session_file(session_id: int, name: str, examiner: Examiner = Depends(current_examiner),
                 db: Session = Depends(get_db)):
    """A recording or photo of a test: only those listed on the test, only for its examiner."""
    s = _examiner_session(db, session_id, examiner)
    listed = {Path(f).name for r in s.results for f in r.evidence_files}
    if name not in listed:
        raise HTTPException(404, "file not found")
    path = Path(s.folder) / name
    if path.is_file():
        return FileResponse(path, headers={"Cache-Control": "private, no-store"})
    data = storage.download(s.folder, name)
    if data is None:
        raise HTTPException(404, "file not found")
    return Response(data, media_type=storage._content_type(name),
                    headers={"Cache-Control": "private, no-store"})
