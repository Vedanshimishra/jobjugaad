from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models import (
    ActionRequest, AgentRun, Application, CandidateProfile, CompanyResearch, InterviewPrep, Job, JobMatch, Memory,
    OutreachMessage, Resume, TailoredResume,
)


def _dt(v: datetime | None) -> str | None:
    if not v:
        return None
    return (v if v.tzinfo else v.replace(tzinfo=UTC)).isoformat()  # SQLite drops tzinfo; values are UTC


def profile(p: CandidateProfile) -> dict[str, Any]:
    fields = [
        "id", "version", "full_name", "email", "phone", "location", "links", "headline", "summary", "education",
        "experience", "projects", "skills", "certifications", "graduation_year", "experience_months",
        "preferred_roles", "preferred_levels", "preferred_locations", "work_modes", "willing_to_relocate",
        "min_salary", "salary_currency", "target_companies", "required_technologies", "avoid_technologies",
        "work_authorization",
    ]
    return {f: getattr(p, f) for f in fields} | {"updated_at": _dt(p.updated_at)}


def resume(r: Resume, full: bool = False) -> dict[str, Any]:
    d = {"id": r.id, "filename": r.filename, "content_type": r.content_type, "parse_method": r.parse_method,
         "is_primary": r.is_primary, "created_at": _dt(r.created_at)}
    if full:
        d |= {"raw_text": r.raw_text, "parsed": r.parsed}
    return d


def job(j: Job, with_description: bool = False) -> dict[str, Any]:
    d = {"id": j.id, "source": j.source, "company": j.company, "title": j.title, "location": j.location,
         "work_mode": j.work_mode, "url": j.url, "level": j.level, "employment_type": j.employment_type,
         "salary_min": j.salary_min, "salary_max": j.salary_max, "salary_currency": j.salary_currency,
         "posted_at": _dt(j.posted_at), "fetched_at": _dt(j.fetched_at)}
    if with_description:
        d["description"] = j.description
    return d


def match(m: JobMatch, app_status: str | None = None) -> dict[str, Any]:
    return {"job": job(m.job), "score": m.score, "eligibility": m.eligibility,
            "eligibility_reasons": m.eligibility_reasons, "breakdown": m.breakdown, "strengths": m.strengths,
            "gaps": m.gaps, "explanation": m.explanation, "computed_at": _dt(m.computed_at),
            "application_status": app_status}


def application(a: Application, with_events: bool = False) -> dict[str, Any]:
    d = {"id": a.id, "job": job(a.job), "status": a.status, "priority": a.priority, "applied_at": _dt(a.applied_at),
         "next_action": a.next_action, "next_action_due": _dt(a.next_action_due), "notes": a.notes,
         "tailored_resume_id": a.tailored_resume_id, "created_at": _dt(a.created_at), "updated_at": _dt(a.updated_at)}
    if with_events:
        d["events"] = [{"id": e.id, "kind": e.kind, "detail": e.detail, "created_at": _dt(e.created_at)} for e in a.events]
    return d


def research(r: CompanyResearch) -> dict[str, Any]:
    return {"id": r.id, "company": r.company, "job_id": r.job_id, "content": r.content, "created_at": _dt(r.created_at)}


def tailored(t: TailoredResume) -> dict[str, Any]:
    return {"id": t.id, "job_id": t.job_id, "content": t.content, "markdown": t.markdown, "change_log": t.change_log,
            "warnings": t.warnings, "created_at": _dt(t.created_at)}


def prep(p: InterviewPrep) -> dict[str, Any]:
    return {"id": p.id, "job_id": p.job_id, "content": p.content, "created_at": _dt(p.created_at)}


def message(m: OutreachMessage) -> dict[str, Any]:
    return {"id": m.id, "job_id": m.job_id, "kind": m.kind, "channel": m.channel, "recipient_name": m.recipient_name,
            "recipient_role": m.recipient_role, "recipient_contact": m.recipient_contact, "subject": m.subject,
            "body": m.body, "status": m.status, "sent_at": _dt(m.sent_at), "created_at": _dt(m.created_at)}


def approval(a: ActionRequest, msg: OutreachMessage | None = None) -> dict[str, Any]:
    return {"id": a.id, "action_type": a.action_type, "summary": a.summary, "payload": a.payload,
            "status": a.status, "agent_run_id": a.agent_run_id, "decision_note": a.decision_note, "result": a.result,
            "created_at": _dt(a.created_at), "decided_at": _dt(a.decided_at),
            "message": message(msg) if msg else None}


def memory(m: Memory) -> dict[str, Any]:
    return {"id": m.id, "kind": m.kind, "content": m.content, "tags": m.tags, "importance": m.importance,
            "source": m.source, "job_id": m.job_id, "created_at": _dt(m.created_at)}


def run(r: AgentRun, with_steps: bool = False) -> dict[str, Any]:
    d = {"id": r.id, "goal": r.goal, "status": r.status, "final_answer": r.final_answer, "error": r.error,
         "usage": r.usage, "created_at": _dt(r.created_at), "finished_at": _dt(r.finished_at)}
    if with_steps:
        d["steps"] = [{"index": s.index, "kind": s.kind, "tool_name": s.tool_name, "content": s.content,
                       "created_at": _dt(s.created_at)} for s in r.steps]
    return d
