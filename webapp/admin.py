"""
The admin portal: adding and deactivating examiners and patients.

The admin sets each person's password, so they can sign in straight away: no emails.

Administrators manage accounts and nothing else. Nothing here returns a score,
a transcript or a recording, and no other route lets an admin read them.
"""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import supabase_admin
from .accounts import ExaminerIn, PatientIn, clean_examiner, clean_patient, new_examiner
from .auth import current_admin, get_db
from .db import Examiner, Patient, TestSession, User, utcnow

router = APIRouter(prefix="/api/admin")

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
MIN_PASSWORD = 8


class NewExaminer(ExaminerIn):
    email: str
    password: str


class NewPatient(PatientIn):
    email: str
    password: str


class NewPassword(BaseModel):
    password: str = Field(max_length=200)


def _clean_email(email, db):
    email = email.strip().lower()
    if not EMAIL.fullmatch(email):
        raise HTTPException(400, "that doesn't look like an email address")
    if db.scalar(select(User).where(func.lower(User.email) == email)) is not None:
        raise HTTPException(409, "someone with this email is already in the app")
    return email


def _clean_password(password):
    if len(password) < MIN_PASSWORD:
        raise HTTPException(400, f"use a password of at least {MIN_PASSWORD} characters")
    return password


def create_login(email, password):
    """A Supabase login with this password. Shared with the examiners' patient invitations."""
    try:
        return supabase_admin.create_login(email, password)
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
def add_examiner(body: NewExaminer, admin: User = Depends(current_admin),
                 db: Session = Depends(get_db)):
    email, password = _clean_email(body.email, db), _clean_password(body.password)
    data = clean_examiner(ExaminerIn(**body.model_dump(exclude={"email", "password"})))
    user = User(id=create_login(email, password), email=email, role="examiner", added_by=admin.id)
    user.examiner = new_examiner(data)
    db.add(user)
    db.commit()
    return _row(user, db)


@router.post("/patients")
def add_patient(body: NewPatient, admin: User = Depends(current_admin),
                db: Session = Depends(get_db)):
    email, password = _clean_email(body.email, db), _clean_password(body.password)
    data = clean_patient(PatientIn(**body.model_dump(exclude={"email", "password"})))
    user = User(id=create_login(email, password), email=email, role="patient", added_by=admin.id)
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


@router.post("/users/{user_id}/password")
def set_password(user_id: str, body: NewPassword, admin: User = Depends(current_admin),
                 db: Session = Depends(get_db)):
    """A new password for someone who forgot theirs. The admin tells them what it is."""
    user = _target(db, user_id)
    if user.deactivated_at:
        raise HTTPException(409, "reactivate this account first")
    supabase_admin.set_password(user.id, _clean_password(body.password))
    return {"updated": user.email}
