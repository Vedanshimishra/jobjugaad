from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import current_user
from app.db import get_db
from app.models import APPLICATION_STATUSES, Application, Memory, User
from app.schemas import ApplicationUpdate, MemoryCreate
from app.services import applications, memory, prioritization

router = APIRouter(tags=["tracking"])


@router.get("/applications")
def list_applications(status: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Application).where(Application.user_id == user.id)
    if status:
        stmt = stmt.where(Application.status.in_(status.split(",")))
    rows = db.scalars(stmt.order_by(Application.updated_at.desc())).all()
    return {"statuses": list(APPLICATION_STATUSES), "applications": [ser.application(a) for a in rows]}


@router.put("/applications/{job_id}")
def upsert_application(job_id: int, body: ApplicationUpdate, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    try:
        app = applications.update(db, user.id, job_id, **body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return ser.application(app, with_events=True)


@router.get("/applications/{job_id}")
def get_application(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    app = db.scalar(select(Application).where(Application.user_id == user.id, Application.job_id == job_id))
    if not app:
        raise HTTPException(404, "No application for this job")
    return ser.application(app, with_events=True)


@router.get("/recommendations")
def recommendations(limit: int = 10, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return prioritization.recommend(db, user.id, limit=limit)


@router.get("/memories")
def list_memories(q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    if q:
        return [ser.memory(m) for m in memory.recall(db, user.id, q, limit=50)]
    rows = db.scalars(select(Memory).where(Memory.user_id == user.id).order_by(Memory.created_at.desc()).limit(200)).all()
    return [ser.memory(m) for m in rows]


@router.post("/memories")
def add_memory(body: MemoryCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = memory.remember(db, user.id, body.content, kind=body.kind, tags=body.tags, importance=body.importance)
    return ser.memory(m)


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(Memory, memory_id)
    if not m or m.user_id != user.id:
        raise HTTPException(404, "Memory not found")
    db.delete(m)
    db.commit()
