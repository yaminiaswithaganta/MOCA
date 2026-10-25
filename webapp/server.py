"""
MoCA web app -- the server.

    .venv/bin/python -m uvicorn webapp.server:app --port 8000
    (or double-click start.command)

Runs on this computer only (127.0.0.1). The browser page does the screens,
voice, microphone and camera; this server transcribes speech with Whisper,
scores every task with the original task modules, and keeps patients, tests
and scores in the SQLite database (moca.db). Photos and recordings are saved
in results/session_<date>_<time>/ as before.
"""

import asyncio
import json
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from moca_common import (PROJECT_DIR, RESULTS_ROOT, TASK_MAX_SCORES,  # noqa: E402
                         build_final_report, make_task_result)
from moca_score_sheet import build_sheet, sheet_text  # noqa: E402
from moca_speech import get_engine, save_wav  # noqa: E402
from moca_tasks import ALL_TASKS, TASK_IDS  # noqa: E402

from . import web_tasks as wt  # noqa: E402
from .db import Patient, SessionLocal, TaskResult, TestSession, init_db  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent / "static"
SAMPLE_RATE = 16000

app = FastAPI(title="MoCA")
init_db()


@app.middleware("http")
async def _no_stale_pages(request, call_next):
    """The page and its scripts are re-checked on every load, so an update shows up at once."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response
RESULTS_ROOT.mkdir(exist_ok=True)


# --------------------------------------------------------------------------
# Speech recogniser: loaded once in the background when the server starts
# --------------------------------------------------------------------------
_engine_state = {"ready": False, "error": None}
_engine_load_lock = threading.Lock()
_engine_use_lock = threading.Lock()        # one answer is transcribed at a time


def engine():
    with _engine_load_lock:
        try:
            e = get_engine()
            _engine_state.update(ready=True, error=None)
            return e
        except Exception as exc:
            _engine_state["error"] = str(exc)
            raise


@app.on_event("startup")
def _preload_engine():
    threading.Thread(target=lambda: _safe(engine), daemon=True).start()


def _safe(fn):
    try:
        fn()
    except Exception as exc:
        print(f"[speech] could not load the speech recogniser: {exc}")


# Recorded answers of the task in progress: {session_id: {task: {step: answer}}}
_answers = {}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _url_for(path):
    """results/... file -> URL the browser can open, or None."""
    try:
        rel = Path(path).resolve().relative_to(RESULTS_ROOT.resolve())
    except (ValueError, TypeError):
        return None
    return "/results/" + rel.as_posix()


def _result_out(r):
    out = dict(r)
    out["evidence_urls"] = [u for u in (_url_for(p) for p in r.get("evidence_files") or []) if u]
    return out


def _get_session(db, session_id):
    s = db.get(TestSession, session_id)
    if s is None:
        raise HTTPException(404, "test not found")
    return s


def _store_result(session_id, std):
    """Insert or replace the task's row in task_results."""
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
        row.created_at = datetime.now()
        db.commit()
    return _result_out(std)


def _report(s):
    """Final report + paper-form score sheet from the session's stored results."""
    selected = [TASK_IDS[n] for n in s.tasks]
    results = {r.task_id: r.to_result() for r in s.results if r.task_id in selected}
    report = build_final_report(results, tasks=selected)
    patient = s.patient.sheet_info(s.started_at.date().isoformat())
    sheet = build_sheet(report, patient)
    return report, sheet, patient


def _session_out(s, with_results=True):
    out = s.to_dict()
    out["patient"] = s.patient.to_dict()
    if with_results:
        report, sheet, _ = _report(s)
        out["report"] = {**report, "tasks": {k: _result_out(v) for k, v in report["tasks"].items()}}
        out["sheet"] = sheet
        out["done_tasks"] = [n for n in s.tasks if any(r.task_id == TASK_IDS[n] for r in s.results)]
    return out


# --------------------------------------------------------------------------
# Status + configuration
# --------------------------------------------------------------------------
@app.get("/api/status")
def status():
    return {"speech_ready": _engine_state["ready"], "speech_error": _engine_state["error"]}


@app.get("/api/config")
def config():
    return wt.client_config()


@app.get("/api/reference-cube.png")
def reference_cube():
    from task2_cube_copy import make_reference_cube_image
    ok, png = cv2.imencode(".png", make_reference_cube_image())
    return Response(png.tobytes(), media_type="image/png")


@app.post("/api/face")
async def face(file: UploadFile = File(...)):
    """Largest face in a small camera frame (Task 7 uses it to place the hand-raise zone)."""
    img = cv2.imdecode(np.frombuffer(await file.read(), np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return {"face": None}
    w = img.shape[1]
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = casc.detectMultiScale(img, 1.1, 5, minSize=(w // 10, w // 10))
    if not len(faces):
        return {"face": None}
    return {"face": [int(v) for v in max(faces, key=lambda f: f[2] * f[3])]}


# --------------------------------------------------------------------------
# Patients
# --------------------------------------------------------------------------
class PatientIn(BaseModel):
    name: str
    date_of_birth: str | None = None
    sex: str | None = None
    education_years: int | None = None
    notes: str | None = None


def _clean_patient(p: PatientIn):
    data = p.model_dump()
    data["name"] = data["name"].strip()
    if not data["name"]:
        raise HTTPException(400, "name is required")
    if data["education_years"] is not None and not 0 <= data["education_years"] <= 40:
        raise HTTPException(400, "years of education must be between 0 and 40")
    return data


@app.get("/api/patients")
def list_patients(q: str = ""):
    with SessionLocal() as db:
        stmt = select(Patient).order_by(Patient.name)
        if q.strip():
            stmt = stmt.where(Patient.name.ilike(f"%{q.strip()}%"))
        out = []
        for p in db.scalars(stmt):
            d = p.to_dict()
            last = next((s for s in p.sessions), None)
            d["tests"] = len(p.sessions)
            d["last_test"] = last.to_dict() if last else None
            out.append(d)
        return out


@app.post("/api/patients")
def create_patient(p: PatientIn):
    with SessionLocal() as db:
        row = Patient(**_clean_patient(p))
        db.add(row)
        db.commit()
        return row.to_dict()


@app.get("/api/patients/{patient_id}")
def get_patient(patient_id: int):
    with SessionLocal() as db:
        p = db.get(Patient, patient_id)
        if p is None:
            raise HTTPException(404, "patient not found")
        d = p.to_dict()
        d["sessions"] = [s.to_dict() for s in p.sessions]
        return d


@app.put("/api/patients/{patient_id}")
def update_patient(patient_id: int, p: PatientIn):
    with SessionLocal() as db:
        row = db.get(Patient, patient_id)
        if row is None:
            raise HTTPException(404, "patient not found")
        for k, v in _clean_patient(p).items():
            setattr(row, k, v)
        db.commit()
        return row.to_dict()


# --------------------------------------------------------------------------
# Test sessions
# --------------------------------------------------------------------------
class SessionIn(BaseModel):
    patient_id: int
    tasks: list[int] = ALL_TASKS


@app.get("/api/sessions")
def list_sessions(limit: int = 20):
    with SessionLocal() as db:
        rows = db.scalars(select(TestSession).order_by(TestSession.started_at.desc()).limit(limit))
        return [{**s.to_dict(), "patient": s.patient.to_dict()} for s in rows]


@app.get("/api/stats")
def stats():
    with SessionLocal() as db:
        full = select(TestSession).where(TestSession.status == "finished", TestSession.max_total == 30)
        return {"patients": db.scalar(select(func.count(Patient.id))),
                "tests": db.scalar(select(func.count(TestSession.id))),
                "finished": db.scalar(select(func.count(TestSession.id))
                                      .where(TestSession.status == "finished")),
                "in_progress": db.scalar(select(func.count(TestSession.id))
                                         .where(TestSession.status != "finished")),
                "average_full": db.scalar(select(func.avg(TestSession.adjusted_total))
                                          .where(TestSession.status == "finished",
                                                 TestSession.max_total == 30)),
                "full_tests": len(db.scalars(full).all())}


@app.post("/api/sessions")
def create_session(body: SessionIn):
    tasks = sorted(set(body.tasks))
    if not tasks or any(t not in TASK_IDS for t in tasks):
        raise HTTPException(400, "choose tasks between 1 and 13")
    with SessionLocal() as db:
        p = db.get(Patient, body.patient_id)
        if p is None:
            raise HTTPException(404, "patient not found")
        now = datetime.now()
        folder = RESULTS_ROOT / now.strftime("session_%Y%m%d_%H%M%S")
        k = 2
        while folder.exists():
            folder = RESULTS_ROOT / f"{now.strftime('session_%Y%m%d_%H%M%S')}_{k}"
            k += 1
        folder.mkdir(parents=True)
        (folder / "patient.json").write_text(json.dumps(p.sheet_info(now.date().isoformat()), indent=2))
        s = TestSession(patient_id=p.id, folder=str(folder), tasks=tasks, started_at=now,
                        max_total=sum(TASK_MAX_SCORES[TASK_IDS[t]] for t in tasks))
        db.add(s)
        db.commit()
        return _session_out(s)


@app.get("/api/sessions/{session_id}")
def get_session(session_id: int):
    with SessionLocal() as db:
        return _session_out(_get_session(db, session_id))


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: int):
    """Remove a test from the database (its results folder is kept on disk)."""
    with SessionLocal() as db:
        db.delete(_get_session(db, session_id))
        db.commit()
    _answers.pop(session_id, None)
    return {"deleted": session_id}


@app.post("/api/sessions/{session_id}/finish")
def finish_session(session_id: int):
    with SessionLocal() as db:
        s = _get_session(db, session_id)
        report, sheet, patient = _report(s)
        report["session_dir"] = s.folder
        report["patient"] = patient
        folder = Path(s.folder)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "moca_results.json").write_text(json.dumps(report, indent=2, default=str))
        (folder / "score_sheet.json").write_text(json.dumps(sheet, indent=2, default=str))
        (folder / "score_sheet.txt").write_text(sheet_text(sheet))
        s.status, s.finished_at = "finished", datetime.now()
        s.total, s.max_total = sheet["total"], report["max_total"]
        # the education point belongs to the full 30-point test only
        s.education_bonus = sheet["education_bonus"] if report["max_total"] == 30 else 0
        s.adjusted_total = min(report["max_total"], sheet["total"] + s.education_bonus)
        db.commit()
        _answers.pop(session_id, None)
        return _session_out(s)


def _check_task(s, number):
    if number not in s.tasks:
        raise HTTPException(400, f"task {number} is not part of this test")


@app.post("/api/sessions/{session_id}/tasks/{number}/finish")
def finish_spoken_task(session_id: int, number: int):
    with SessionLocal() as db:
        s = _get_session(db, session_id)
        _check_task(s, number)
        folder = s.folder
    answers = _answers.get(session_id, {}).get(number, {})
    try:
        std = wt.finish_task(number, answers, folder)
    except wt.MissingAnswers as e:
        raise HTTPException(400, str(e))
    _answers.get(session_id, {}).pop(number, None)
    return _store_result(session_id, std)


@app.post("/api/sessions/{session_id}/tasks/{number}/skip")
def skip_task(session_id: int, number: int):
    """Examiner skipped the task: it counts as 0 and is listed as not completed."""
    with SessionLocal() as db:
        s = _get_session(db, session_id)
        _check_task(s, number)
    task_id = TASK_IDS[number]
    from moca_common import DEFAULT_CRITERIA
    std = make_task_result(task_id, 0, reason="skipped by the examiner", completed=False,
                           criteria=DEFAULT_CRITERIA.get(task_id))
    _answers.get(session_id, {}).pop(number, None)
    return _store_result(session_id, std)


@app.post("/api/sessions/{session_id}/tasks/{number}/photo")
async def task_photo(session_id: int, number: int, file: UploadFile = File(...)):
    if number not in (2, 3):
        raise HTTPException(400, "only tasks 2 and 3 take a photo")
    with SessionLocal() as db:
        s = _get_session(db, session_id)
        _check_task(s, number)
        folder = Path(s.folder)
    img = cv2.imdecode(np.frombuffer(await file.read(), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "could not read the photo")
    path = folder / wt.photo_name(number)
    cv2.imwrite(str(path), img)
    std = await asyncio.to_thread(wt.score_photo, number, path, folder)
    return _store_result(session_id, std)


@app.post("/api/sessions/{session_id}/tasks/7/letters")
def task_letters(session_id: int, data: dict):
    with SessionLocal() as db:
        s = _get_session(db, session_id)
        _check_task(s, 7)
        folder = s.folder
    try:
        std = wt.score_letters(data, folder)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _store_result(session_id, std)


# --------------------------------------------------------------------------
# Live listening: the browser streams 16 kHz float32 audio over a WebSocket
# --------------------------------------------------------------------------
class StreamRecorder:
    """Same interface as task1's MicRecorder (pull() / .audio), fed by the browser."""

    def __init__(self):
        self._chunks = queue.Queue()
        self.audio = np.zeros(0, np.float32)

    def push(self, data):
        self._chunks.put(np.frombuffer(data, dtype=np.float32).copy())

    def start(self):
        pass

    def stop(self):
        pass

    def pull(self):
        parts = []
        while True:
            try:
                parts.append(self._chunks.get_nowait())
            except queue.Empty:
                break
        if parts:
            self.audio = np.concatenate([self.audio] + parts)
        return len(self.audio) / SAMPLE_RATE


class StopListening(Exception):
    pass


def _listen_worker(session_id, number, step, folder, rec, send, stop, cancel):
    """Runs in a thread: one spoken answer (or Task 1's whole path)."""
    try:
        eng = engine()
    except Exception as e:
        send({"type": "error", "text": f"Speech recogniser could not start: {e}"})
        return
    with _engine_use_lock:
        send({"type": "ready"})
        if number == 1:
            answer, done_msg = _listen_trail(eng, rec, send, stop, folder)
        else:
            answer, done_msg = _listen_answer(eng, number, step, rec, send, stop, folder)
    if cancel.is_set():
        return
    _answers.setdefault(session_id, {}).setdefault(number, {})[step] = answer
    send(done_msg)


def _listen_answer(eng, number, step, rec, send, stop, folder):
    from moca_speech import listen_for_answer
    cfg = wt.LISTEN_STEPS[(number, step)]
    heard = []

    def pump():
        if stop.is_set():
            raise StopListening()

    def status(text):
        if text.startswith('Heard: "') and text.endswith('"'):
            heard.append(text[8:-1])
            send({"type": "heard", "text": text[8:-1]})
        else:
            send({"type": "status", "text": text})

    try:
        ans = listen_for_answer(
            eng, cfg["prompt"], pump=pump, status=status, max_seconds=cfg["max_seconds"],
            end_silence=cfg["end_silence"], no_speech_timeout=cfg["no_speech_timeout"],
            is_done=cfg["is_done"], grace_after_done=cfg["grace"],
            reminder=lambda: send({"type": "reminder", "text": cfg["reminder"]}), recorder=rec)
    except StopListening:
        # examiner pressed "Done": score what was said so far
        rec.pull()
        final = None
        if rec.audio.size and np.max(np.abs(rec.audio)) > 1e-3:
            send({"type": "status", "text": "Checking the answer..."})
            final = eng.transcribe(rec.audio, whole_session=True, prompt=cfg["prompt"])
        ans = {"audio": rec.audio, "phrases": [{"text": t, "words": []} for t in heard],
               "final": final, "end_reason": "stopped by the examiner"}
    wav = Path(folder) / cfg["wav"]
    save_wav(wav, ans["audio"])
    answer = {"phrases": ans["phrases"], "final": ans["final"], "end_reason": ans["end_reason"],
              "wav": str(wav)}
    return answer, {"type": "done", "heard": wt.heard_text(answer), "end_reason": ans["end_reason"]}


def _listen_trail(eng, rec, send, stop, folder):
    import task1_trail_making as t1

    def emit(kind, payload):
        send({"type": kind, "text": payload} if kind != "token" else {"type": "token", "token": payload})

    live = t1.LiveSession(eng, emit)
    t0 = time.time()
    while True:
        if stop.is_set():
            live.done_reason = "stopped by the examiner"
            break
        time.sleep(0.25)
        rec.pull()
        if live.feed(rec.audio):
            break
        if time.time() - t0 > t1.MAX_TASK_SECONDS + 30:      # no audio arriving
            live.done_reason = "time limit reached"
            break
    rec.pull()
    live.audio = rec.audio
    send({"type": "status", "text": "Checking the full recording..."})
    score, reason, details = live.final_result()
    wav = Path(folder) / "task1_audio.wav"
    save_wav(wav, live.audio)
    transcript = Path(folder) / "task1_transcript.json"
    transcript.write_text(json.dumps(details, indent=2, default=str))
    answer = {"result": (score, reason, details), "wav": str(wav), "transcript": str(transcript)}
    return answer, {"type": "done", "heard": details.get("final_transcript", ""),
                    "spoken_sequence": details["spoken_sequence"], "end_reason": details["end_reason"]}


@app.websocket("/ws/listen")
async def ws_listen(ws: WebSocket):
    """
    Protocol: the browser sends {"session_id", "task", "step"} first, waits for
    {"type": "ready"}, then streams binary float32 audio. The server sends
    "heard" / "status" / "reminder" / "token" messages while listening and one
    "done" (or "error") at the end. {"type": "stop"} from the browser ends the
    answer early; closing the socket cancels it.
    """
    await ws.accept()
    loop = asyncio.get_running_loop()
    try:
        init = await ws.receive_json()
        session_id, number, step = int(init["session_id"]), int(init["task"]), str(init["step"])
        if number != 1 and (number, step) not in wt.LISTEN_STEPS:
            raise ValueError(f"unknown step {number}/{step}")
        with SessionLocal() as db:
            s = db.get(TestSession, session_id)
            if s is None or number not in s.tasks:
                raise ValueError("test or task not found")
            folder = s.folder
    except Exception as e:
        await ws.send_json({"type": "error", "text": f"bad request: {e}"})
        await ws.close()
        return

    out_q: asyncio.Queue = asyncio.Queue()
    rec, stop, cancel = StreamRecorder(), threading.Event(), threading.Event()

    def send(msg):
        loop.call_soon_threadsafe(out_q.put_nowait, msg)

    async def receiver():
        try:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    break
                if m.get("bytes"):
                    rec.push(m["bytes"])
                elif m.get("text") and json.loads(m["text"]).get("type") == "stop":
                    stop.set()
        except Exception:
            pass
        cancel.set()
        stop.set()

    async def sender():
        while True:
            msg = await out_q.get()
            if msg is None:
                return
            try:
                await ws.send_json(msg)
            except Exception:
                return

    recv_task = asyncio.create_task(receiver())
    send_task = asyncio.create_task(sender())
    try:
        await asyncio.to_thread(_listen_worker, session_id, number, step, folder,
                                rec, send, stop, cancel)
    except Exception as e:
        send({"type": "error", "text": f"listening failed: {e}"})
    send(None)
    await send_task
    recv_task.cancel()
    try:
        await ws.close()
    except Exception:
        pass


# --------------------------------------------------------------------------
# Pages and files
# --------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/images", StaticFiles(directory=PROJECT_DIR / "images"), name="images")
app.mount("/results", StaticFiles(directory=RESULTS_ROOT), name="results")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
