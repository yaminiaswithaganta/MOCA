"""
The admin portal: adding and deactivating examiners and patients.

Administrators manage accounts and nothing else. Nothing here returns a score,
a transcript or a recording, and no other route lets an admin read them.
"""

import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import supabase_admin
from .accounts import ExaminerIn, PatientIn, clean_examiner, clean_patient, new_examiner
from .auth import current_admin, get_db
from .db import Examiner, Patient, TestSession, User, utcnow

router = APIRouter(prefix="/api/admin")

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class NewExaminer(ExaminerIn):
    email: str


class NewPatient(PatientIn):
    email: str


def _clean_email(email, db):
    email = email.strip().lower()
    if not EMAIL.fullmatch(email):
        raise HTTPException(400, "that doesn't look like an email address")
    if db.scalar(select(User).where(func.lower(User.email) == email)) is not None:
        raise HTTPException(409, "someone with this email is already in the app")
    return email


def _password_page(request):
    site = os.environ.get("MOCA_SITE_URL", str(request.base_url)).rstrip("/")
    return f"{site}/reset-password"


def _invite(email, request):
    try:
        return supabase_admin.invite(email, _password_page(request))
    except supabase_admin.EmailTaken:
        # Never adopt the existing login: anyone could have registered it with this address
        # and would become an examiner the moment it was added here.
        raise HTTPException(409, "this email already has a login that isn't set up. Delete it in "
                                 "Supabase (Authentication > Users) and add the person again")


def _row(user, db):
    profile = user.patient or user.examiner
    out = {"id": user.id, "email": user.email, "role": user.role,
           "name": profile.name if profile else user.email, "active": user.deactivated_at is None,
           "added_by_admin": user.added_by is not None}
    if user.patient:
        out["details"] = None
        out["tests"] = db.scalar(select(func.count(TestSession.id))
                                 .where(TestSession.patient_id == user.patient.id))
    elif user.examiner:
        out["details"] = " · ".join(x for x in (user.examiner.title, user.examiner.organization) if x) or None
        out["tests"] = db.scalar(select(func.count(TestSession.id))
                                 .where(TestSession.examiner_id == user.examiner.id))
        out["awaiting_review"] = db.scalar(select(func.count(TestSession.id)).where(
            TestSession.examiner_id == user.examiner.id, TestSession.status == "finished",
            TestSession.released_at.is_(None)))
    return out


def _target(db, user_id):
    user = db.get(User, user_id)
    if user is None or user.role == "admin":
        raise HTTPException(404, "person not found")
    return user


@router.get("/stats")
def stats(_: User = Depends(current_admin), db: Session = Depends(get_db)):
    active = User.deactivated_at.is_(None)
    count = lambda role: db.scalar(select(func.count(User.id)).where(User.role == role, active))  # noqa: E731
    return {"examiners": count("examiner"), "patients": count("patient"),
            "deactivated": db.scalar(select(func.count(User.id)).where(~active))}


@router.get("/users")
def list_users(role: str, q: str = "", _: User = Depends(current_admin), db: Session = Depends(get_db)):
    if role not in ("examiner", "patient"):
        raise HTTPException(400, "role must be examiner or patient")
    profile = Examiner if role == "examiner" else Patient
    stmt = select(User).join(profile, profile.user_id == User.id).order_by(profile.name)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(profile.name.ilike(like) | User.email.ilike(like))
    return [_row(u, db) for u in db.scalars(stmt)]


@router.post("/examiners")
def add_examiner(body: NewExaminer, request: Request, admin: User = Depends(current_admin),
                 db: Session = Depends(get_db)):
    email = _clean_email(body.email, db)
    data = clean_examiner(ExaminerIn(**body.model_dump(exclude={"email"})))
    user = User(id=_invite(email, request), email=email, role="examiner", added_by=admin.id)
    user.examiner = new_examiner(data)
    db.add(user)
    db.commit()
    return _row(user, db)


@router.post("/patients")
def add_patient(body: NewPatient, request: Request, admin: User = Depends(current_admin),
                db: Session = Depends(get_db)):
    email = _clean_email(body.email, db)
    data = clean_patient(PatientIn(**body.model_dump(exclude={"email"})))
    user = User(id=_invite(email, request), email=email, role="patient", added_by=admin.id)
    user.patient = Patient(**data)
    db.add(user)
    db.commit()
    return _row(user, db)


@router.post("/users/{user_id}/deactivate")
def deactivate(user_id: str, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    """Takes effect on their next request. Their past tests and results are kept."""
    user = _target(db, user_id)
    user.deactivated_at = user.deactivated_at or utcnow()
    db.commit()
    return _row(user, db)


@router.post("/users/{user_id}/reactivate")
def reactivate(user_id: str, admin: User = Depends(current_admin), db: Session = Depends(get_db)):
    user = _target(db, user_id)
    user.deactivated_at = None
    db.commit()
    return _row(user, db)


@router.post("/users/{user_id}/send-link")
def send_link(user_id: str, request: Request, admin: User = Depends(current_admin),
              db: Session = Depends(get_db)):
    """Email a fresh link to choose a password, for an expired invite or a forgotten one."""
    user = _target(db, user_id)
    if user.deactivated_at:
        raise HTTPException(409, "reactivate this account first")
    supabase_admin.send_password_link(user.email, _password_page(request))
    return {"sent": user.email}
