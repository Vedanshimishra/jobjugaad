"""What should the user do next? Ranks unapplied jobs and surfaces due follow-ups."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, JobMatch

CLOSED = {"applied", "assessment", "interviewing", "offer", "rejected", "withdrawn", "ghosted"}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def recommend(db: Session, user_id: int, limit: int = 10) -> dict:
    now = datetime.now(UTC)
    apps = {a.job_id: a for a in db.scalars(select(Application).where(Application.user_id == user_id)).all()}
    matches = db.scalars(
        select(JobMatch).where(JobMatch.user_id == user_id, JobMatch.eligibility != "ineligible")
        .order_by(JobMatch.score.desc()).limit(300)
    ).all()

    ranked = []
    for m in matches:
        app = apps.get(m.job_id)
        if app and app.status in CLOSED:
            continue
        if not m.job.is_active:
            continue
        reasons = [f"match {m.score:.0f}/100"]
        priority = m.score * 0.7
        posted = _aware(m.job.posted_at)
        if posted:
            age = (now - posted).days
            fresh = max(0.0, 15 - age * 0.5)  # early applications get more attention
            priority += fresh
            if age <= 7:
                reasons.append(f"posted {age}d ago")
        if m.eligibility == "eligible":
            priority += 8
            reasons.append("clearly eligible")
        if m.breakdown.get("target_company"):
            priority += 10
            reasons.append("target company")
        if app:
            priority += 5 + app.priority * 3
            reasons.append(f"you {app.status} it")
        ranked.append({"job_id": m.job_id, "company": m.job.company, "title": m.job.title, "url": m.job.url,
                       "score": m.score, "eligibility": m.eligibility, "priority": round(priority, 1),
                       "reasons": reasons})
    ranked.sort(key=lambda r: r["priority"], reverse=True)

    follow_ups = []
    for app in apps.values():
        applied = _aware(app.applied_at)
        due = _aware(app.next_action_due)
        if due and due <= now + timedelta(days=1):
            follow_ups.append({"job_id": app.job_id, "company": app.job.company, "title": app.job.title,
                               "action": app.next_action or "Scheduled action due", "due": due.isoformat()})
        elif app.status == "applied" and applied and now - applied > timedelta(days=7):
            last = _aware(app.events[-1].created_at) if app.events else applied
            if now - last > timedelta(days=7):
                follow_ups.append({"job_id": app.job_id, "company": app.job.company, "title": app.job.title,
                                   "action": f"No update for {(now - last).days} days — consider a follow-up or referral",
                                   "due": now.isoformat()})
    return {"apply_next": ranked[:limit], "follow_ups": follow_ups}
