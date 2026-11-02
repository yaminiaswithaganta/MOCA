"""
MoCA web app -- the server.

    .venv/bin/python -m uvicorn webapp.server:app --port 8000
    (or double-click start.command)

Serves the React app (frontend/dist) and the API. The browser does the screens,
voice, microphone and camera; this server checks who is calling (webapp/auth.py),
transcribes speech with Whisper (webapp/listen.py), scores every task with the
original task modules and keeps everything in the database (webapp/db.py) and
Supabase Storage (webapp/storage.py).

Run one worker process: Whisper and the answers of tests in progress live in memory.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from moca_common import PROJECT_DIR, RESULTS_ROOT  # noqa: E402

from . import accounts, admin, listen, sessions, storage, templates  # noqa: E402
from . import web_tasks as wt  # noqa: E402
from .auth import SUPABASE_URL, current_patient, current_user  # noqa: E402
from .db import Patient, User, init_db  # noqa: E402

DIST_DIR = PROJECT_DIR / "frontend" / "dist"

log = logging.getLogger("moca")


@asynccontextmanager
async def lifespan(_):
    init_db()
    try:
        storage.ensure_bucket()
    except Exception as e:
        log.error("could not reach Supabase Storage: %s", e)
    listen.preload_engine()
    yield


app = FastAPI(title="MoCA", lifespan=lifespan)
RESULTS_ROOT.mkdir(exist_ok=True)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "microphone=(self), camera=(self)",
}


@app.middleware("http")
async def _headers(request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif not request.url.path.startswith("/assets/"):
        # the page is re-checked on every load, so an update shows up at once
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


app.include_router(accounts.router)
app.include_router(admin.router)
app.include_router(templates.router)
app.include_router(sessions.router)
app.include_router(listen.router)


# --------------------------------------------------------------------------
# Status + configuration
# --------------------------------------------------------------------------
@app.get("/api/status")
def status():
    return {"speech_ready": listen.engine_state["ready"], "speech_error": listen.engine_state["error"]}


@app.get("/api/public-config")
def public_config():
    """What the browser needs to reach Supabase. All of it is safe to be public."""
    return {"supabase_url": SUPABASE_URL,
            "supabase_anon_key": os.environ.get("MOCA_SUPABASE_ANON_KEY", ""),
            "google_login": os.environ.get("MOCA_GOOGLE_LOGIN", "") == "1"}


@app.get("/api/config")
def config(_: User = Depends(current_user)):
    return wt.client_config()


@app.get("/api/reference-cube.png")
def reference_cube():
    from task2_cube_copy import make_reference_cube_image
    ok, png = cv2.imencode(".png", make_reference_cube_image())
    return Response(png.tobytes(), media_type="image/png")


@app.post("/api/face")
async def face(file: UploadFile = File(...), _: Patient = Depends(current_patient)):
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
# Pages and files
# --------------------------------------------------------------------------
app.mount("/images", StaticFiles(directory=PROJECT_DIR / "images"), name="images")
if (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    """The React app: a real file if there is one, otherwise index.html (it does the routing)."""
    if path.startswith(("api/", "ws/")):
        raise HTTPException(404, "not found")
    target = (DIST_DIR / path).resolve()
    if path and target.is_file() and target.is_relative_to(DIST_DIR.resolve()):
        return FileResponse(target)
    index = DIST_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(503, "the frontend isn't built yet: run npm run build in frontend/")
    return FileResponse(index)
