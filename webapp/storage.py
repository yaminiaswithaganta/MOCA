"""
Keeps recordings and photos in a private Supabase Storage bucket.

A test's files are first written to its local results/session_.../ folder, because
the scoring code works on files. They are then copied here, so they survive a server
redeploy. Without MOCA_SUPABASE_SERVICE_KEY only the local folder is used.

The service key bypasses all access rules: it stays on the server, and the browser
only ever gets files through GET /api/sessions/{id}/files/{name}.
"""

import logging
import os
from pathlib import Path

import httpx

from .auth import SUPABASE_URL

log = logging.getLogger("moca.storage")

SERVICE_KEY = os.environ.get("MOCA_SUPABASE_SERVICE_KEY", "")
BUCKET = os.environ.get("MOCA_STORAGE_BUCKET", "moca-evidence")
_BASE = f"{SUPABASE_URL}/storage/v1"
_HEADERS = {"Authorization": f"Bearer {SERVICE_KEY}", "apikey": SERVICE_KEY}


def enabled():
    return bool(SUPABASE_URL and SERVICE_KEY)


def ensure_bucket():
    """Create the private bucket on first start."""
    if not enabled():
        return
    r = httpx.get(f"{_BASE}/bucket/{BUCKET}", headers=_HEADERS, timeout=30)
    if r.status_code == 200:
        return
    r = httpx.post(f"{_BASE}/bucket", headers=_HEADERS, timeout=30,
                   json={"id": BUCKET, "name": BUCKET, "public": False})
    r.raise_for_status()


def _key(folder, name):
    return f"{Path(folder).name}/{name}"


def upload(folder, path):
    """Copy one file to the bucket. A failure is logged; the local copy is still there."""
    if not enabled():
        return
    path = Path(path)
    try:
        r = httpx.post(f"{_BASE}/object/{BUCKET}/{_key(folder, path.name)}", timeout=120,
                       headers={**_HEADERS, "x-upsert": "true",
                                "Content-Type": _content_type(path.name)},
                       content=path.read_bytes())
        r.raise_for_status()
    except (httpx.HTTPError, OSError) as e:
        log.error("could not upload %s: %s", path.name, e)


def download(folder, name):
    """A file's bytes from the bucket, or None."""
    if not enabled():
        return None
    r = httpx.get(f"{_BASE}/object/{BUCKET}/{_key(folder, name)}", headers=_HEADERS, timeout=120)
    return r.content if r.status_code == 200 else None


def delete_folder(folder, names):
    if not enabled() or not names:
        return
    try:
        r = httpx.request("DELETE", f"{_BASE}/object/{BUCKET}", headers=_HEADERS, timeout=60,
                          json={"prefixes": [_key(folder, n) for n in names]})
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.error("could not delete files of %s: %s", Path(folder).name, e)


def _content_type(name):
    suffix = Path(name).suffix.lower()
    return {".wav": "audio/wav", ".png": "image/png", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".json": "application/json"}.get(suffix, "application/octet-stream")
