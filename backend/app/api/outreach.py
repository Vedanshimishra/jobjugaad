from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.api import serializers as ser
from app.api.deps import current_profile, current_user, llm_errors
from app.db import get_db
from app.models import ActionRequest, CandidateProfile, OutreachMessage, User
from app.schemas import ApprovalRequestBody, Decision, OutreachCreate, OutreachEdit
from app.services import applications, approvals, memory

router = APIRouter(tags=["outreach"])


def _msg(db: Session, user: User, message_id: int) -> OutreachMessage:
    m = db.get(OutreachMessage, message_id)
    if not m or m.user_id != user.id:
        raise HTTPException(404, "Message not found")
    return m


@router.post("/outreach")
def create_draft(body: OutreachCreate, profile: CandidateProfile = Depends(current_profile),
                 db: Session = Depends(get_db)):
    from app.agent.tools import ToolContext, ToolError, draft_outreach_message

    try:
        out = draft_outreach_message(ToolContext(db, profile.user_id, None), body.model_dump())
    except ToolError as e:
        raise HTTPException(400, str(e)) from e
    except llm.LLMError as e:
        raise llm_errors(e) from e
    return ser.message(db.get(OutreachMessage, out["message_id"]))


@router.get("/outreach")
def list_messages(job_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(OutreachMessage).where(OutreachMessage.user_id == user.id)
    if job_id:
        stmt = stmt.where(OutreachMessage.job_id == job_id)
    return [ser.message(m) for m in db.scalars(stmt.order_by(OutreachMessage.created_at.desc())).all()]


@router.patch("/outreach/{message_id}")
def edit_message(message_id: int, body: OutreachEdit, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = _msg(db, user, message_id)
    if m.status in ("sent", "pending_approval"):
        raise HTTPException(409, f"Cannot edit a message that is {m.status}")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    if m.status in ("approved", "rejected"):
        m.status = "draft"  # edits after a decision need a fresh approval
    db.commit()
    return ser.message(m)


@router.post("/outreach/{message_id}/request-approval")
def request_approval(message_id: int, body: ApprovalRequestBody, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    m = _msg(db, user, message_id)
    if m.status not in ("draft", "rejected"):
        raise HTTPException(409, f"Message is {m.status}")
    req = approvals.propose(db, user.id, "send_outreach_message",
                            f"Send {m.kind} {m.channel} message to {m.recipient_name or 'recipient'}: {body.reason}",
                            {"message_id": m.id})
    return ser.approval(req, m)


@router.post("/outreach/{message_id}/mark-sent")
def mark_sent(message_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The user confirms they sent an approved message themselves (e.g. on LinkedIn)."""
    m = _msg(db, user, message_id)
    if m.status != "approved":
        raise HTTPException(409, "Only approved messages can be marked as sent")
    m.status, m.sent_at = "sent", datetime.now(UTC)
    if m.job_id:
        applications.log_event_for_job(db, user.id, m.job_id, "message", {"message_id": m.id, "status": "sent"})
    memory.remember(db, user.id, f"Sent {m.kind} message to {m.recipient_name or 'contact'} ({m.recipient_role}).",
                    kind="interaction", source="user", job_id=m.job_id, commit=False)
    db.commit()
    return ser.message(m)


@router.get("/approvals")
def list_approvals(status: str | None = "pending", user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(ActionRequest).where(ActionRequest.user_id == user.id)
    if status:
        stmt = stmt.where(ActionRequest.status == status)
    out = []
    for a in db.scalars(stmt.order_by(ActionRequest.created_at.desc()).limit(100)).all():
        msg = db.get(OutreachMessage, a.payload.get("message_id")) if a.action_type == "send_outreach_message" else None
        out.append(ser.approval(a, msg))
    return out


@router.post("/approvals/{request_id}/decision")
def decide(request_id: int, body: Decision, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        req = approvals.decide(db, user.id, request_id, approve=body.approve, note=body.note,
                               edits=body.edits.model_dump(exclude_unset=True) if body.edits else None)
    except approvals.ApprovalError as e:
        raise HTTPException(409, str(e)) from e
    msg = db.get(OutreachMessage, req.payload.get("message_id")) if req.action_type == "send_outreach_message" else None
    return ser.approval(req, msg)
