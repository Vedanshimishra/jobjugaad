from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import runner
from app.api import serializers as ser
from app.api.deps import current_user
from app.db import get_db
from app.models import AgentRun, User
from app.schemas import AgentFollowUp, AgentGoal

router = APIRouter(prefix="/agent", tags=["agent"])
ACTIVE = ("queued", "running", "stopping")


def _run(db: Session, user: User, run_id: int) -> AgentRun:
    r = db.get(AgentRun, run_id)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Run not found")
    return r


@router.post("/runs", status_code=202)
def start_run(body: AgentGoal, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = AgentRun(user_id=user.id, goal=body.goal.strip(), status="queued")
    db.add(r)
    db.commit()
    runner.start_run_async(r.id)
    return ser.run(r)


@router.get("/runs")
def list_runs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AgentRun).where(AgentRun.user_id == user.id).order_by(AgentRun.created_at.desc()).limit(50)).all()
    return [ser.run(r) for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return ser.run(_run(db, user, run_id), with_steps=True)


@router.post("/runs/{run_id}/messages", status_code=202)
def follow_up(run_id: int, body: AgentFollowUp, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _run(db, user, run_id)
    if r.status in ACTIVE:
        raise HTTPException(409, "The agent is still working on this run")
    if not r.transcript:
        raise HTTPException(409, "This run cannot be continued")
    r.status, r.error, r.finished_at = "queued", "", None
    db.commit()
    runner.start_run_async(r.id, follow_up=body.text.strip())
    return ser.run(r)


@router.post("/runs/{run_id}/stop")
def stop(run_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _run(db, user, run_id)
    if r.status in ("queued", "running"):
        r.status = "stopping"
        db.commit()
    return ser.run(r)
