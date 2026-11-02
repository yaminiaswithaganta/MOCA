"""
Supabase's admin API, for creating logins on someone's behalf.

Uses the service key, so it runs on the server only.
"""

import httpx
from fastapi import HTTPException

from .auth import SUPABASE_URL
from .storage import SERVICE_KEY

_BASE = f"{SUPABASE_URL}/auth/v1"
_HEADERS = {"Authorization": f"Bearer {SERVICE_KEY}", "apikey": SERVICE_KEY}
PAGE_SIZE = 200


class EmailTaken(Exception):
    pass


def _call(method, path, **kwargs):
    if not (SUPABASE_URL and SERVICE_KEY):
        raise HTTPException(503, "adding people needs MOCA_SUPABASE_SERVICE_KEY on the server")
    try:
        return httpx.request(method, f"{_BASE}{path}", headers=_HEADERS, timeout=30, **kwargs)
    except httpx.HTTPError as e:
        raise HTTPException(502, "could not reach Supabase") from e


def _failed(r):
    data = r.json() if "json" in r.headers.get("content-type", "") else {}
    return HTTPException(502, data.get("msg") or data.get("message") or "Supabase refused the request")


def invite(email, redirect_to):
    """Create a login and email the person a link to choose a password. Returns the user id."""
    r = _call("POST", "/invite", json={"email": email}, params={"redirect_to": redirect_to})
    if r.status_code == 422:
        raise EmailTaken(email)
    if r.status_code >= 400:
        raise _failed(r)
    return r.json()["id"]


def send_password_link(email, redirect_to):
    r = _call("POST", "/recover", json={"email": email}, params={"redirect_to": redirect_to})
    if r.status_code >= 400:
        raise _failed(r)


def link_for(email, redirect_to):
    """(user id, one-time sign-in link) without sending any email, creating the login if needed."""
    existing = find_user(email)
    kind = "recovery" if existing else "invite"
    r = _call("POST", "/admin/generate_link",
              json={"type": kind, "email": email, "redirect_to": redirect_to})
    if r.status_code >= 400:
        raise _failed(r)
    data = r.json()
    return data["id"], data["action_link"]


def find_user(email):
    page = 1
    while True:
        r = _call("GET", "/admin/users", params={"page": page, "per_page": PAGE_SIZE})
        if r.status_code >= 400:
            raise _failed(r)
        users = r.json().get("users", [])
        for u in users:
            if (u.get("email") or "").lower() == email.lower():
                return u
        if len(users) < PAGE_SIZE:
            return None
        page += 1
