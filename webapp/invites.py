"""
Patient invitations: how an examiner brings in a patient.

The examiner enters the patient's name, email and date of birth and gets a link to share.
The patient opens it and enters their name, email, date of birth and years of education.
If the email and date of birth match, the patient is signed in and connected to that
examiner. Opening the same link again signs them back in, so they never need a password.

The link holds a long random token, so it can't be guessed; the email and date of birth
must match as well, so a forwarded link alone isn't enough.
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import supabase_admin
from .accounts import PatientIn, clean_patient
from .admin import EMAIL, create_login
from .auth import current_examiner, get_db
from .db import Examiner, Patient, PatientInvite, User, iso, utcnow

router = APIRouter(prefix="/api")


class InviteIn(BaseModel):
    name: str
    email: str
    date_of_birth: str


class JoinIn(BaseModel):
    name: str
    email: str
    date_of_birth: str
    education_years: int | None = None
    sex: str | None = None


def _out(inv):
    return {"id": inv.id, "name": inv.name, "email": inv.email, "date_of_birth": inv.date_of_birth,
            "token": inv.token, "patient_id": inv.patient_id, "joined_at": iso(inv.joined_at),
            "created_at": iso(inv.created_at)}


def _clean_email(email):
    email = email.strip().lower()
    if not EMAIL.fullmatch(email):
        raise HTTPException(400, "that doesn't look like an email address")
    return email


# --------------------------------------------------------------------------
# Examiner: create and manage invitations
# --------------------------------------------------------------------------
@router.post("/invites")
def create_invite(body: InviteIn, examiner: Examiner = Depends(current_examiner),
                  db: Session = Depends(get_db)):
    email = _clean_email(body.email)
    data = clean_patient(PatientIn(name=body.name, date_of_birth=body.date_of_birth))
    if not data["date_of_birth"]:
        raise HTTPException(400, "enter the patient's date of birth")
    existing = db.scalar(select(PatientInvite).where(PatientInvite.examiner_id == examiner.id,
                                                     func.lower(PatientInvite.email) == email))
    if existing:                                   # same patient again: same link
        return _out(existing)
    inv = PatientInvite(token=secrets.token_urlsafe(32), examiner_id=examiner.id, name=data["name"],
                        email=email, date_of_birth=data["date_of_birth"])
    db.add(inv)
    db.commit()
    return _out(inv)


@router.get("/invites")
def list_invites(examiner: Examiner = Depends(current_examiner), db: Session = Depends(get_db)):
    rows = db.scalars(select(PatientInvite).where(PatientInvite.examiner_id == examiner.id)
                      .order_by(PatientInvite.created_at.desc()))
    return [_out(i) for i in rows]


@router.delete("/invites/{invite_id}")
def delete_invite(invite_id: int, examiner: Examiner = Depends(current_examiner),
                  db: Session = Depends(get_db)):
    """The link stops working. A patient who already joined keeps their account and results."""
    inv = db.get(PatientInvite, invite_id)
    if inv is None or inv.examiner_id != examiner.id:
        raise HTTPException(404, "invitation not found")
    db.delete(inv)
    db.commit()
    return {"deleted": invite_id}


# --------------------------------------------------------------------------
# Patient: open the link (no sign-in needed)
# --------------------------------------------------------------------------
def _invite(db, token):
    inv = db.scalar(select(PatientInvite).where(PatientInvite.token == token))
    if inv is None or inv.examiner.user.deactivated_at:
        raise HTTPException(404, "this link isn't valid any more. Ask your examiner for a new one")
    return inv


@router.get("/join/{token}")
def join_info(token: str, db: Session = Depends(get_db)):
    """Who invited them. Nothing about the patient, in case the link was forwarded."""
    inv = _invite(db, token)
    return {"examiner": inv.examiner.to_dict(), "joined": inv.patient_id is not None}


@router.post("/join/{token}")
def join(token: str, body: JoinIn, db: Session = Depends(get_db)):
    """Check the details and sign the patient in. Returns a one-time password for the browser."""
    inv = _invite(db, token)
    email = _clean_email(body.email)
    if email != inv.email.lower() or body.date_of_birth != inv.date_of_birth:
        raise HTTPException(400, "your email or date of birth doesn't match what your examiner "
                                 "entered. Check them, or ask your examiner")
    if body.education_years is None:
        raise HTTPException(400, "enter your years of education: it's used to score the test fairly")
    data = clean_patient(PatientIn(name=body.name, date_of_birth=body.date_of_birth,
                                   education_years=body.education_years, sex=body.sex))
    password = secrets.token_urlsafe(24)

    if inv.patient_id is None:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user is not None and user.role != "patient":
            raise HTTPException(409, "this email belongs to a staff account. Ask your examiner")
        if user is not None:
            # they made their own account earlier: connect it, but leave their password alone
            if user.deactivated_at:
                raise HTTPException(403, "this account has been deactivated")
            inv.patient, inv.joined_at = user.patient, utcnow()
            db.commit()
            return {"sign_in": True, "email": email}
        user = User(id=create_login(email, password), email=email, role="patient")
        user.patient = Patient(**data)
        db.add(user)
        inv.patient, inv.created_login = user.patient, True
    else:
        user = inv.patient.user
        if user.deactivated_at:
            raise HTTPException(403, "this account has been deactivated")
        if not inv.created_login:
            return {"sign_in": True, "email": email}     # their own account: they use their password
        for k in ("name", "education_years", "sex"):
            if data[k] is not None:
                setattr(inv.patient, k, data[k])
        supabase_admin.set_password(user.id, password)
    inv.joined_at = inv.joined_at or utcnow()
    db.commit()
    return {"email": email, "password": password, "examiner_id": inv.examiner_id}
