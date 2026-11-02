"""Accounts: the signed-in user's profile, first-time setup, and the list of examiners."""

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from moca_tasks import ALL_TASKS

from .auth import Identity, current_identity, current_patient, current_user, get_db
from .db import Examiner, Patient, TestTemplate, User
from .templates import DEFAULT_SETTINGS

router = APIRouter(prefix="/api")


class PatientIn(BaseModel):
    name: str
    date_of_birth: str | None = None
    sex: str | None = None
    education_years: int | None = None


class ExaminerIn(BaseModel):
    name: str
    title: str | None = None
    organization: str | None = None


def clean_patient(p: PatientIn):
    data = p.model_dump()
    data["name"] = data["name"].strip()
    if not data["name"]:
        raise HTTPException(400, "name is required")
    dob = data["date_of_birth"]
    if dob is not None:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob):
            raise HTTPException(400, "date of birth must be YYYY-MM-DD")
        try:
            if date.fromisoformat(dob) >= date.today():
                raise HTTPException(400, "date of birth must be in the past")
        except ValueError:
            raise HTTPException(400, "date of birth is not a real date")
    if data["education_years"] is not None and not 0 <= data["education_years"] <= 40:
        raise HTTPException(400, "years of education must be between 0 and 40")
    return data


def clean_examiner(e: ExaminerIn):
    data = e.model_dump()
    data["name"] = data["name"].strip()
    if not data["name"]:
        raise HTTPException(400, "name is required")
    return data


def new_examiner(data):
    """An examiner starts with the standard test, so patients can choose them right away."""
    return Examiner(**data, templates=[TestTemplate(
        name="Standard MoCA", description="All 13 tasks in the standard order, out of 30 points.",
        tasks=ALL_TASKS, settings=DEFAULT_SETTINGS, published=True)])


def _me(identity, user):
    out = {"id": identity.id, "email": identity.email, "role": user.role if user else None,
           "deactivated": bool(user and user.deactivated_at)}
    if user and user.role == "patient":
        out["profile"] = user.patient.to_dict()
    elif user and user.role == "examiner":
        out["profile"] = user.examiner.to_dict()
    return out


@router.get("/me")
def me(identity: Identity = Depends(current_identity), db: Session = Depends(get_db)):
    return _me(identity, db.get(User, identity.id))


@router.post("/me/onboard")
def onboard(body: PatientIn, identity: Identity = Depends(current_identity),
            db: Session = Depends(get_db)):
    """First sign-in. Anyone can become a patient; examiners and admins are added by an admin."""
    if db.get(User, identity.id) is not None:
        raise HTTPException(409, "this account is already set up")
    user = User(id=identity.id, email=identity.email, role="patient")
    user.patient = Patient(**clean_patient(body))
    db.add(user)
    db.commit()
    return _me(identity, user)


@router.put("/me/profile")
def update_profile(body: dict, identity: Identity = Depends(current_identity),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "admin":
        raise HTTPException(400, "administrators have no profile")
    try:
        if user.role == "patient":
            data, row = clean_patient(PatientIn(**body)), user.patient
        else:
            data, row = clean_examiner(ExaminerIn(**body)), user.examiner
    except ValidationError:
        raise HTTPException(400, "please check your details")
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    return _me(identity, db.get(User, identity.id))


@router.get("/examiners")
def list_examiners(_: Patient = Depends(current_patient), db: Session = Depends(get_db)):
    """Examiners a patient can choose, each with the tests they have published."""
    out = []
    rows = select(Examiner).join(User).where(User.deactivated_at.is_(None)).order_by(Examiner.name)
    for e in db.scalars(rows):
        tests = [t.to_dict() for t in e.templates if t.published and not t.archived]
        if tests:
            out.append({**e.to_dict(), "tests": tests})
    return out
