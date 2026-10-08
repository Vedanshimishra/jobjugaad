"""Application tracking with an event history."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import APPLICATION_STATUSES, Application, ApplicationEvent, Job


def get_or_create(db: Session, user_id: int, job_id: int) -> Application:
    app = db.scalar(select(Application).where(Application.user_id == user_id, Application.job_id == job_id))
    if app is None:
        if db.get(Job, job_id) is None:
            raise ValueError(f"Job {job_id} not found")
        app = Application(user_id=user_id, job_id=job_id, status="saved")
        db.add(app)
        db.flush()
        app.events.append(ApplicationEvent(kind="status_change", detail={"from": None, "to": "saved"}))
    return app


def update(
    db: Session, user_id: int, job_id: int, *, status: str | None = None, notes: str | None = None,
    priority: int | None = None, next_action: str | None = None, next_action_due: datetime | None = None,
    tailored_resume_id: int | None = None,
) -> Application:
    from app.services import memory  # local import: memory <-> approvals <-> applications

    app = get_or_create(db, user_id, job_id)
    if status and status != app.status:
        if status not in APPLICATION_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Use one of {APPLICATION_STATUSES}")
        app.events.append(ApplicationEvent(kind="status_change", detail={"from": app.status, "to": status}))
        prev, app.status = app.status, status
        if status == "applied" and not app.applied_at:
            app.applied_at = datetime.now(UTC)
        job = db.get(Job, job_id)
        memory.remember(db, user_id, f"Application to {job.company} — {job.title}: {prev} → {status}",
                        kind="outcome" if status in ("offer", "rejected") else "interaction",
                        importance=4 if status in ("offer", "rejected", "interviewing") else 2,
                        source="system", job_id=job_id, commit=False)
    if notes is not None and notes != app.notes:
        app.events.append(ApplicationEvent(kind="note", detail={"notes": notes}))
        app.notes = notes
    if priority is not None:
        app.priority = priority
    if next_action is not None:
        app.next_action = next_action[:500]
    if next_action_due is not None:
        app.next_action_due = next_action_due
    if tailored_resume_id is not None:
        app.tailored_resume_id = tailored_resume_id
    db.commit()
    return app


def log_event_for_job(db: Session, user_id: int, job_id: int, kind: str, detail: dict) -> None:
    app = get_or_create(db, user_id, job_id)
    app.events.append(ApplicationEvent(kind=kind, detail=detail))
