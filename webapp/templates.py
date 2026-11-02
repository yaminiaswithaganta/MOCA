"""
Test templates: the tests an examiner designs.

An examiner picks which tasks, in which order, and a few settings. The task content
and the scoring stay exactly the standard MoCA's, so results stay comparable. A test
taken from a template keeps its own copy, so later edits don't change past tests.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from moca_tasks import TASK_IDS

from .auth import current_examiner, get_db
from .db import Examiner, TestTemplate

router = APIRouter(prefix="/api/templates")

MEMORY_TASK, RECALL_TASK = 5, 12


class Settings(BaseModel):
    voice_speed: Literal["normal", "slow"] = "normal"
    extra_answer_seconds: int = Field(default=0, ge=0, le=60)   # longer wait for an answer to start
    allow_skip: bool = True
    intro: str = Field(default="", max_length=1000)             # shown before the test starts


DEFAULT_SETTINGS = Settings().model_dump()


class TemplateIn(BaseModel):
    name: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    tasks: list[int]
    settings: Settings = Settings()
    published: bool = False


def _clean(body: TemplateIn):
    name = body.name.strip()
    tasks = body.tasks
    if not name:
        raise HTTPException(400, "give the test a name")
    if not tasks:
        raise HTTPException(400, "choose at least one task")
    if len(set(tasks)) != len(tasks) or any(t not in TASK_IDS for t in tasks):
        raise HTTPException(400, "tasks must be different numbers between 1 and 13")
    if RECALL_TASK in tasks and (MEMORY_TASK not in tasks
                                 or tasks.index(MEMORY_TASK) > tasks.index(RECALL_TASK)):
        raise HTTPException(400, "Delayed recall needs Memory (learning) earlier in the test")
    return {"name": name, "description": (body.description or "").strip() or None, "tasks": tasks,
            "settings": body.settings.model_dump(), "published": body.published}


def _own(db, template_id, examiner):
    t = db.get(TestTemplate, template_id)
    if t is None or t.examiner_id != examiner.id or t.archived:
        raise HTTPException(404, "test not found")
    return t


@router.get("")
def list_templates(examiner: Examiner = Depends(current_examiner), db: Session = Depends(get_db)):
    rows = db.scalars(select(TestTemplate).where(TestTemplate.examiner_id == examiner.id,
                                                 TestTemplate.archived.is_(False))
                      .order_by(TestTemplate.name))
    return [t.to_dict() for t in rows]


@router.post("")
def create_template(body: TemplateIn, examiner: Examiner = Depends(current_examiner),
                    db: Session = Depends(get_db)):
    row = TestTemplate(examiner_id=examiner.id, **_clean(body))
    db.add(row)
    db.commit()
    return row.to_dict()


@router.get("/{template_id}")
def get_template(template_id: int, examiner: Examiner = Depends(current_examiner),
                 db: Session = Depends(get_db)):
    return _own(db, template_id, examiner).to_dict()


@router.put("/{template_id}")
def update_template(template_id: int, body: TemplateIn,
                    examiner: Examiner = Depends(current_examiner), db: Session = Depends(get_db)):
    row = _own(db, template_id, examiner)
    for k, v in _clean(body).items():
        setattr(row, k, v)
    db.commit()
    return row.to_dict()


@router.delete("/{template_id}")
def delete_template(template_id: int, examiner: Examiner = Depends(current_examiner),
                    db: Session = Depends(get_db)):
    """Archives it: past tests still point at it."""
    _own(db, template_id, examiner).archived = True
    db.commit()
    return {"deleted": template_id}
