"""
The web app's database: one SQLite file, moca.db, next to the scripts.

Three tables:
  * patients      -- name, date of birth, sex, years of education
  * test_sessions -- one row per MoCA test (which tasks, totals, results folder)
  * task_results  -- one row per scored task (score, criteria, reason, evidence files)

Audio recordings and photos stay as files in results/session_<date>_<time>/,
exactly where the command-line version puts them; the database stores their paths.

To move to PostgreSQL later (e.g. Supabase), set MOCA_DATABASE_URL to the
postgresql:// address -- nothing else changes.
"""

import os
from datetime import datetime

from sqlalchemy import (JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
                        create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from moca_common import PROJECT_DIR

DATABASE_URL = os.environ.get("MOCA_DATABASE_URL", f"sqlite:///{PROJECT_DIR / 'moca.db'}")

engine = create_engine(DATABASE_URL,
                       connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)   # YYYY-MM-DD
    sex: Mapped[str | None] = mapped_column(String(20), nullable=True)
    education_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    sessions: Mapped[list["TestSession"]] = relationship(back_populates="patient",
                                                         order_by="TestSession.started_at.desc()")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "date_of_birth": self.date_of_birth,
                "sex": self.sex, "education_years": self.education_years, "notes": self.notes,
                "created_at": self.created_at.isoformat(timespec="seconds")}

    def sheet_info(self, test_date):
        """Patient block in the format moca_score_sheet / patient.json use."""
        return {"name": self.name, "education_years": self.education_years, "sex": self.sex,
                "date_of_birth": self.date_of_birth, "test_date": test_date}


class TestSession(Base):
    __tablename__ = "test_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    folder: Mapped[str] = mapped_column(String(500))
    tasks: Mapped[list] = mapped_column(JSON)                 # task numbers, e.g. [1, 2, ..., 13]
    status: Mapped[str] = mapped_column(String(20), default="in_progress")   # or "finished"
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    education_bonus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adjusted_total: Mapped[int | None] = mapped_column(Integer, nullable=True)

    patient: Mapped[Patient] = relationship(back_populates="sessions")
    results: Mapped[list["TaskResult"]] = relationship(back_populates="session",
                                                       cascade="all, delete-orphan")

    def to_dict(self):
        return {"id": self.id, "patient_id": self.patient_id, "folder": self.folder,
                "tasks": self.tasks, "status": self.status,
                "started_at": self.started_at.isoformat(timespec="seconds"),
                "finished_at": self.finished_at.isoformat(timespec="seconds") if self.finished_at else None,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    session: Mapped[TestSession] = relationship(back_populates="results")

    def to_result(self):
        """Back to the standard result dict that make_task_result() builds."""
        return {"task": self.task_id, "score": self.score, "max_score": self.max_score,
                "criteria": self.criteria, "completed": self.completed, "reason": self.reason,
                "details": self.details, "evidence_files": self.evidence_files,
                "timestamp": self.created_at.isoformat(timespec="seconds")}


def init_db():
    Base.metadata.create_all(engine)
