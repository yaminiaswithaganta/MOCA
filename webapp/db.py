"""
The web app's database: PostgreSQL (Supabase) in production, one SQLite file for
quick local runs and the tests. The schema is managed by Alembic (migrations/).

Tables:
  * users          -- one row per login; id is the Supabase user id, role lives here
                      ("patient", "examiner" or "admin")
  * patients       -- a patient's own details (name, date of birth, sex, education)
  * examiners      -- an examiner's public details (name, title, organisation)
  * test_templates -- tests an examiner designed (tasks, order, settings)
  * test_sessions  -- one row per test taken (a snapshot of the template, totals, review)
  * task_results   -- one row per scored task (score, criteria, reason, evidence files)

Audio recordings and photos are written to results/session_.../ while a test runs and
copied to private Supabase Storage when it is configured; the database stores their paths.

The role is kept here and never read from the Supabase token: users can edit their
own Supabase metadata, so anything in it could be used to become an examiner.
"""

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from moca_common import PROJECT_DIR, TASK_MAX_SCORES
from moca_tasks import ALL_TASKS, TASK_IDS

load_dotenv(PROJECT_DIR / ".env")

DATABASE_URL = os.environ.get("MOCA_DATABASE_URL", f"sqlite:///{PROJECT_DIR / 'moca_local.db'}")


def _engine_for(url):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    if url.startswith(("postgresql://", "postgres://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    # prepare_threshold=None: Supabase's connection pooler can't use prepared statements
    return create_engine(url, pool_pre_ping=True, connect_args={"prepare_threshold": None})


engine = _engine_for(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    """Timestamp for the API, always with its time zone (SQLite drops it)."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat(timespec="seconds")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)      # Supabase user id
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    added_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)   # an admin
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped["Patient | None"] = relationship(back_populates="user")
    examiner: Mapped["Examiner | None"] = relationship(back_populates="user")


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)   # YYYY-MM-DD
    sex: Mapped[str | None] = mapped_column(String(20), nullable=True)
    education_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="patient")
    sessions: Mapped[list["TestSession"]] = relationship(back_populates="patient",
                                                         order_by="TestSession.started_at.desc()")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "date_of_birth": self.date_of_birth,
                "sex": self.sex, "education_years": self.education_years,
                "created_at": iso(self.created_at)}

    def sheet_info(self, test_date):
        """Patient block in the format moca_score_sheet / patient.json use."""
        return {"name": self.name, "education_years": self.education_years, "sex": self.sex,
                "date_of_birth": self.date_of_birth, "test_date": test_date}


class Examiner(Base):
    __tablename__ = "examiners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    organization: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="examiner")
    templates: Mapped[list["TestTemplate"]] = relationship(back_populates="examiner",
                                                           order_by="TestTemplate.name")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "title": self.title,
                "organization": self.organization}


class TestTemplate(Base):
    __tablename__ = "test_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    examiner_id: Mapped[int] = mapped_column(ForeignKey("examiners.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tasks: Mapped[list] = mapped_column(JSON)                 # task numbers, in the order given
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow,
                                                 onupdate=utcnow)

    examiner: Mapped[Examiner] = relationship(back_populates="templates")

    def to_dict(self):
        return {"id": self.id, "examiner_id": self.examiner_id, "name": self.name,
                "description": self.description, "tasks": self.tasks, "settings": self.settings,
                "published": self.published, "max_points": max_points(self.tasks),
                "standard": self.tasks == ALL_TASKS, "updated_at": iso(self.updated_at)}


class TestSession(Base):
    __tablename__ = "test_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    examiner_id: Mapped[int] = mapped_column(ForeignKey("examiners.id"))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("test_templates.id"), nullable=True)
    template_name: Mapped[str] = mapped_column(String(200))
    folder: Mapped[str] = mapped_column(String(500))
    tasks: Mapped[list] = mapped_column(JSON)                 # task numbers, in the order given
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")   # for Task 13's date
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="in_progress")   # or "finished"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    education_bonus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adjusted_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)     # shown on release

    patient: Mapped[Patient] = relationship(back_populates="sessions")
    examiner: Mapped[Examiner] = relationship()
    results: Mapped[list["TaskResult"]] = relationship(back_populates="session",
                                                       cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "patient_id": self.patient_id, "examiner_id": self.examiner_id,
                "template_id": self.template_id, "template_name": self.template_name,
                "tasks": self.tasks, "settings": self.settings, "status": self.status,
                "started_at": iso(self.started_at), "finished_at": iso(self.finished_at),
                "released_at": iso(self.released_at), "review_note": self.review_note,
                "total": self.total, "max_total": self.max_total,
                "education_bonus": self.education_bonus, "adjusted_total": self.adjusted_total}


class TaskResult(Base):
    __tablename__ = "task_results"
    __table_args__ = (UniqueConstraint("session_id", "task_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("test_sessions.id"))
    task_id: Mapped[str] = mapped_column(String(50))          # e.g. "task4_naming"
    score: Mapped[int] = mapped_column(Integer)
    max_score: Mapped[int] = mapped_column(Integer)
    criteria: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_files: Mapped[list] = mapped_column(JSON, default=list)
    completed: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # kept when an examiner corrects the automatic score
    auto_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_criteria: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correction_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped[TestSession] = relationship(back_populates="results")

    def to_result(self):
        """Back to the standard result dict that make_task_result() builds."""
        return {"task": self.task_id, "score": self.score, "max_score": self.max_score,
                "criteria": self.criteria, "completed": self.completed, "reason": self.reason,
                "details": self.details, "evidence_files": self.evidence_files,
                "timestamp": iso(self.created_at), "auto_score": self.auto_score,
                "auto_criteria": self.auto_criteria, "corrected_at": iso(self.corrected_at),
                "correction_note": self.correction_note}


def max_points(tasks):
    return sum(TASK_MAX_SCORES[TASK_IDS[t]] for t in tasks)


def init_db():
    """Bring the database up to the latest migration."""
    from alembic import command
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    command.upgrade(cfg, "head")
