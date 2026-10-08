"""Human-in-the-loop gate for consequential external actions.

Neither the agent nor any API route can perform an external action directly. They can
only *propose* one (an ActionRequest in 'pending'). Execution happens exclusively in
`decide()`, which is reachable only from the approvals endpoint a human calls.
"""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ActionRequest, OutreachMessage
from app.services import memory
from app.services.applications import log_event_for_job

log = logging.getLogger(__name__)


class ApprovalError(ValueError):
    pass


def propose(db: Session, user_id: int, action_type: str, summary: str, payload: dict,
            agent_run_id: int | None = None) -> ActionRequest:
    if action_type not in EXECUTORS:
        raise ApprovalError(f"Unknown action type '{action_type}'")
    req = ActionRequest(user_id=user_id, action_type=action_type, summary=summary[:1000], payload=payload,
                        agent_run_id=agent_run_id)
    db.add(req)
    if action_type == "send_outreach_message":
        msg = db.get(OutreachMessage, payload.get("message_id"))
        if not msg or msg.user_id != user_id:
            raise ApprovalError("Outreach message not found")
        msg.status = "pending_approval"
    db.commit()
    return req


def decide(db: Session, user_id: int, request_id: int, *, approve: bool, note: str = "",
           edits: dict | None = None) -> ActionRequest:
    req = db.get(ActionRequest, request_id)
    if not req or req.user_id != user_id:
        raise ApprovalError("Approval request not found")
    if req.status != "pending":
        raise ApprovalError(f"Request already {req.status}")
    req.decided_at = datetime.now(UTC)
    req.decision_note = note
    if not approve:
        req.status = "rejected"
        if req.action_type == "send_outreach_message":
            msg = db.get(OutreachMessage, req.payload.get("message_id"))
            if msg:
                msg.status = "rejected"
        if note:
            memory.remember(db, user_id, f"Rejected proposed action ({req.summary}): {note}", kind="feedback",
                            importance=4, source="user", commit=False)
        db.commit()
        return req

    req.status = "approved"
    try:
        req.result = EXECUTORS[req.action_type](db, req, edits or {})
        req.status = "executed"
    except Exception as e:  # executor failures must be visible, never silent
        log.exception("Executing approved action %s failed", req.id)
        req.status = "failed"
        req.result = {"error": str(e)}
    db.commit()
    return req


# ---------- executors ----------

def _send_outreach(db: Session, req: ActionRequest, edits: dict) -> dict:
    msg = db.get(OutreachMessage, req.payload["message_id"])
    if msg is None:
        raise ApprovalError("Message no longer exists")
    for field in ("subject", "body", "recipient_contact", "recipient_name"):
        if field in edits and edits[field] is not None:
            setattr(msg, field, edits[field])

    s = get_settings()
    can_email = msg.channel == "email" and "@" in (msg.recipient_contact or "") and s.smtp_host and s.smtp_from
    if can_email:
        em = EmailMessage()
        em["From"], em["To"], em["Subject"] = s.smtp_from, msg.recipient_contact, msg.subject or "(no subject)"
        em.set_content(msg.body)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password or "")
            smtp.send_message(em)
        msg.status, msg.sent_at = "sent", datetime.now(UTC)
        outcome = {"delivery": "sent_via_smtp", "to": msg.recipient_contact}
    else:
        # No automated channel (e.g. LinkedIn or SMTP not configured): approved for the
        # user to send manually; they mark it sent from the UI.
        msg.status = "approved"
        outcome = {"delivery": "manual", "instructions": "Copy the approved message and send it yourself, then mark it sent."}

    if msg.job_id:
        log_event_for_job(db, msg.user_id, msg.job_id, "message",
                          {"message_id": msg.id, "kind": msg.kind, "status": msg.status, "to": msg.recipient_name})
    memory.remember(db, msg.user_id, f"Outreach ({msg.kind}) to {msg.recipient_name or 'contact'} "
                    f"[{msg.recipient_role}] approved; status {msg.status}.", kind="interaction", source="system",
                    job_id=msg.job_id, commit=False)
    return outcome


EXECUTORS: dict[str, Callable[[Session, ActionRequest, dict], dict]] = {
    "send_outreach_message": _send_outreach,
}
