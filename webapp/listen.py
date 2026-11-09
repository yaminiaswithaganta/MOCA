"""
Live listening: the browser streams 16 kHz float32 audio over a WebSocket, Whisper
transcribes it here. Holds the speech recogniser, and saves each answer of a task in
progress to the database (and its recording to storage) until the task is scored.
"""

import asyncio
import json
import queue
import threading
import time
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, WebSocket

from moca_speech import get_engine, save_wav

from sqlalchemy import delete, select

from . import storage
from . import web_tasks as wt
from .auth import verify_token
from .db import PendingAnswer, SessionLocal, TestSession, User

SAMPLE_RATE = 16000

router = APIRouter()


# --------------------------------------------------------------------------
# Speech recogniser: loaded once in the background when the server starts
# --------------------------------------------------------------------------
engine_state = {"ready": False, "error": None}
_engine_load_lock = threading.Lock()
_engine_use_lock = threading.Lock()


class SharedEngine:
    """The one Whisper model, used by every patient: one transcription at a time.

    Only the transcribe call is locked, not a whole spoken answer, so a patient
    never waits for someone else to finish talking.
    """

    def __init__(self, inner):
        self.inner = inner
        self.supports_constrained = getattr(inner, "supports_constrained", False)

    def transcribe(self, *args, **kwargs):
        with _engine_use_lock:
            return self.inner.transcribe(*args, **kwargs)


def engine():
    with _engine_load_lock:
        try:
            e = SharedEngine(get_engine())
            engine_state.update(ready=True, error=None)
            return e
        except Exception as exc:
            engine_state["error"] = str(exc)
            raise


def preload_engine():
    def load():
        try:
            engine()
        except Exception as exc:
            print(f"[speech] could not load the speech recogniser: {exc}")
    threading.Thread(target=load, daemon=True).start()


# --------------------------------------------------------------------------
# Answers of tasks in progress: in the database, so any server copy can score them
# --------------------------------------------------------------------------
def save_answer(session_id, number, step, answer):
    data = json.loads(json.dumps(answer, default=str))
    with SessionLocal() as db:
        row = db.scalar(select(PendingAnswer).where(PendingAnswer.session_id == session_id,
                                                    PendingAnswer.task == number,
                                                    PendingAnswer.step == step))
        if row is None:
            db.add(PendingAnswer(session_id=session_id, task=number, step=step, data=data))
        else:
            row.data = data
        db.commit()


def answers_for(session_id, number):
    """{step: answer} of one task."""
    with SessionLocal() as db:
        rows = db.scalars(select(PendingAnswer).where(PendingAnswer.session_id == session_id,
                                                      PendingAnswer.task == number))
        return {r.step: r.data for r in rows}


def clear_answers(session_id, number=None):
    with SessionLocal() as db:
        stmt = delete(PendingAnswer).where(PendingAnswer.session_id == session_id)
        if number is not None:
            stmt = stmt.where(PendingAnswer.task == number)
        db.execute(stmt)
        db.commit()


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


def _listen_worker(session_id, number, step, folder, extra_seconds, rec, send, stop, cancel):
    """Runs in a thread: one spoken answer (or Task 1's whole path)."""
    try:
        eng = engine()
    except Exception as e:
        send({"type": "error", "text": f"Speech recogniser could not start: {e}"})
        return
    send({"type": "ready"})
    Path(folder).mkdir(parents=True, exist_ok=True)     # a fresh server copy has no folder yet
    if number == 1:
        answer, done_msg = _listen_trail(eng, rec, send, stop, folder)
    else:
        answer, done_msg = _listen_answer(eng, number, step, extra_seconds, rec, send, stop, folder)
    if cancel.is_set():
        return
    rec.pull()
    if rec.audio.size == 0:
        # a blocked microphone must never look like a patient who didn't answer
        send({"type": "error", "text": "No sound reached the app. Check your microphone, then try again."})
        return
    for key in ("wav", "transcript"):                  # the next request may run on another copy
        if answer.get(key):
            storage.upload(folder, answer[key])
    save_answer(session_id, number, step, answer)
    send(done_msg)


def _listen_answer(eng, number, step, extra_seconds, rec, send, stop, folder):
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
            end_silence=cfg["end_silence"], no_speech_timeout=cfg["no_speech_timeout"] + extra_seconds,
            is_done=cfg["is_done"], grace_after_done=cfg["grace"],
            reminder=lambda: send({"type": "reminder", "text": cfg["reminder"]}), recorder=rec)
    except StopListening:
        # patient pressed "Done": score what was said so far
        rec.pull()
        final = None
        if rec.audio.size and np.max(np.abs(rec.audio)) > 1e-3:
            send({"type": "status", "text": "Checking the answer..."})
            final = eng.transcribe(rec.audio, whole_session=True, prompt=cfg["prompt"])
        ans = {"audio": rec.audio, "phrases": [{"text": t, "words": []} for t in heard],
               "final": final, "end_reason": "stopped by the patient"}
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
            live.done_reason = "stopped by the patient"
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


def authorize_listen(init):
    """(session_id, task, step, folder, extra seconds) from the first message, or an error."""
    identity = verify_token(str(init.get("token", "")))
    session_id, number, step = int(init["session_id"]), int(init["task"]), str(init["step"])
    if number != 1 and (number, step) not in wt.LISTEN_STEPS:
        raise ValueError(f"unknown step {number}/{step}")
    with SessionLocal() as db:
        user = db.get(User, identity.id)
        s = db.get(TestSession, session_id)
        owner = user is not None and user.deactivated_at is None \
            and user.patient is not None and s is not None \
            and s.patient_id == user.patient.id
        if not owner or number not in s.tasks or s.status != "in_progress":
            raise ValueError("test or task not found")
        return session_id, number, step, s.folder, s.settings.get("extra_answer_seconds", 0)


@router.websocket("/ws/listen")
async def ws_listen(ws: WebSocket):
    """
    Protocol: the browser sends {"token", "session_id", "task", "step"} first, waits for
    {"type": "ready"}, then streams binary float32 audio. The server sends
    "heard" / "status" / "reminder" / "token" messages while listening and one
    "done" (or "error") at the end. {"type": "stop"} from the browser ends the
    answer early; closing the socket cancels it.

    The token comes in the first message because browsers can't set headers on a
    WebSocket, and a token in the address would end up in access logs.
    """
    await ws.accept()
    loop = asyncio.get_running_loop()
    try:
        init = await ws.receive_json()
        session_id, number, step, folder, extra_seconds = authorize_listen(init)
    except HTTPException as e:
        await ws.send_json({"type": "error", "text": e.detail})
        await ws.close()
        return
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
        await asyncio.to_thread(_listen_worker, session_id, number, step, folder, extra_seconds,
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
