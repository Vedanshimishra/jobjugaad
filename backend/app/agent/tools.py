"""Agent tool registry.

Each tool = strict JSON schema + handler(ctx, args) -> JSON-serializable dict.
Tools that touch the outside world do NOT exist here; the agent can only *propose*
such actions via `request_approval_to_send`, which a human must approve.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    APPLICATION_STATUSES, Application, CandidateProfile, CompanyResearch, InterviewPrep, Job, JobMatch,
    OutreachMessage, TailoredResume,
)
from app.services import ai_tasks, applications, approvals, jobs as job_svc, memory, prioritization


@dataclass
class ToolContext:
    db: Session
    user_id: int
    run_id: int | None

    @property
    def profile(self) -> CandidateProfile:
        p = self.db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == self.user_id))
        if p is None:
            raise ToolError("No candidate profile exists yet. Ask the user to upload a resume first.")
        return p


class ToolError(Exception):
    """Expected, user-facing tool failure (returned to the model as is_error)."""


@dataclass
class Tool:
    name: str
    description: str
    properties: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]

    @property
    def required(self) -> list[str]:
        return [k for k, v in self.properties.items()
                if not isinstance(v.get("type"), list) and v.get("type") not in ("array", "boolean")]

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.properties,
                "required": self.required,
                "additionalProperties": False,
            },
        }

    def normalize(self, args: Any) -> dict[str, Any]:
        """Validate model-supplied args and fill optional fields with neutral defaults,
        so handlers can index every declared property."""
        if not isinstance(args, dict):
            raise ToolError("Tool input must be a JSON object.")
        missing = [k for k in self.required if args.get(k) in (None, "")]
        if missing:
            raise ToolError(f"Missing required argument(s): {', '.join(missing)}")
        out: dict[str, Any] = {}
        for k, spec in self.properties.items():
            v = args.get(k)
            t = spec.get("type")
            if v is None:
                v = [] if t == "array" else False if t == "boolean" else None
            elif (t == "integer" or t == ["integer", "null"]) and not isinstance(v, int):
                try:
                    v = int(v)
                except (TypeError, ValueError) as e:
                    raise ToolError(f"Argument '{k}' must be an integer") from e
            elif t == "array" and not isinstance(v, list):
                v = [v]
            allowed = spec.get("enum") or (spec.get("items") or {}).get("enum")
            if allowed:
                bad = [x for x in (v if isinstance(v, list) else [v]) if x not in allowed]
                if bad:
                    raise ToolError(f"Argument '{k}' has invalid value(s) {bad}; allowed: {[a for a in allowed if a]}")
            out[k] = v
        return out


def S(desc: str, nullable: bool = False, enum: list[str] | None = None) -> dict:
    d: dict[str, Any] = {"type": ["string", "null"] if nullable else "string", "description": desc}
    if enum:
        d["enum"] = enum + ([None] if nullable else [])
    return d


def I(desc: str, nullable: bool = False) -> dict:
    return {"type": ["integer", "null"] if nullable else "integer", "description": desc}


def A(desc: str, items: dict | None = None) -> dict:
    return {"type": "array", "items": items or {"type": "string"}, "description": desc}


LEVELS = ["internship", "new_grad", "entry", "mid", "senior", "unknown"]


# ---------- helpers ----------

def _job(ctx: ToolContext, job_id: int) -> Job:
    job = ctx.db.get(Job, job_id)
    if job is None:
        raise ToolError(f"Job {job_id} not found. Use search_jobs or list_known_jobs to get valid ids.")
    return job


def _match(ctx: ToolContext, job: Job) -> JobMatch:
    m = ctx.db.scalar(select(JobMatch).where(JobMatch.user_id == ctx.user_id, JobMatch.job_id == job.id))
    profile = ctx.profile
    if m is None or m.profile_version != profile.version:
        m = job_svc.compute_match(ctx.db, profile, job)
        ctx.db.commit()
    return m


def _match_summary(m: JobMatch) -> dict:
    j = m.job
    return {
        "job_id": j.id, "company": j.company, "title": j.title, "location": j.location, "work_mode": j.work_mode,
        "level": j.level, "score": m.score, "eligibility": m.eligibility,
        "strengths": m.strengths[:3], "gaps": m.gaps[:3], "url": j.url,
        "posted": j.posted_at.date().isoformat() if j.posted_at else None,
    }


# ---------- handlers ----------

def get_candidate_profile(ctx: ToolContext, _: dict) -> dict:
    p = ctx.profile
    missing = [label for label, ok in [
        ("graduation_year", p.graduation_year), ("preferred_roles", p.preferred_roles),
        ("preferred_locations", p.preferred_locations), ("work_authorization", p.work_authorization),
        ("skills", p.skills),
    ] if not ok]
    return {
        "profile": ai_tasks.profile_context(p) if p else None,
        "work_authorization": p.work_authorization,
        "min_salary": p.min_salary,
        "missing_fields": missing,
        "note": "Missing fields reduce eligibility accuracy; mention them to the user." if missing else "",
    }


def search_jobs(ctx: ToolContext, a: dict) -> dict:
    res = job_svc.discover_jobs(
        ctx.db, ctx.profile, keywords=a["keywords"], companies=a["companies"] or None,
        levels=a["levels"] or None, work_modes=a["work_modes"] or None, location=a["location"],
        include_ineligible=bool(a["include_ineligible"]), limit=a["limit"] or 15,
    )
    return {
        "fetched_postings": res["fetched"], "relevant_postings": res["relevant"], "source_errors": res["errors"],
        "results": [_match_summary(m) for m in res["matches"]],
    }


def list_known_jobs(ctx: ToolContext, a: dict) -> dict:
    stmt = select(JobMatch).join(Job).where(JobMatch.user_id == ctx.user_id, Job.is_active.is_(True))
    if a["min_score"] is not None:
        stmt = stmt.where(JobMatch.score >= a["min_score"])
    if a["eligibility"]:
        stmt = stmt.where(JobMatch.eligibility == a["eligibility"])
    if a["query"]:
        q = f"%{a['query']}%"
        stmt = stmt.where((Job.title.ilike(q)) | (Job.company.ilike(q)))
    rows = ctx.db.scalars(stmt.order_by(JobMatch.score.desc()).limit(a["limit"] or 20)).all()
    return {"results": [_match_summary(m) for m in rows]}


def get_job_details(ctx: ToolContext, a: dict) -> dict:
    job = _job(ctx, a["job_id"])
    m = _match(ctx, job)
    app = ctx.db.scalar(select(Application).where(Application.user_id == ctx.user_id, Application.job_id == job.id))
    return {
        "job": ai_tasks.job_context(job)[:12000],
        "match": {"score": m.score, "eligibility": m.eligibility, "eligibility_reasons": m.eligibility_reasons,
                  "breakdown": m.breakdown, "strengths": m.strengths, "gaps": m.gaps, "explanation": m.explanation},
        "application_status": app.status if app else None,
    }


def evaluate_job_match(ctx: ToolContext, a: dict) -> dict:
    job = _job(ctx, a["job_id"])
    m = _match(ctx, job)
    out: dict[str, Any] = {"score": m.score, "eligibility": m.eligibility, "eligibility_reasons": m.eligibility_reasons,
                           "components": m.breakdown.get("components"), "strengths": m.strengths, "gaps": m.gaps}
    if a["explain"]:
        exp = ai_tasks.explain_match(ctx.profile, job, m)
        m.explanation = exp.summary
        m.breakdown = {**m.breakdown, "llm": exp.model_dump()}
        ctx.db.commit()
        out["explanation"] = exp.model_dump()
    return out


def add_job_from_text(ctx: ToolContext, a: dict) -> dict:
    job = job_svc.add_manual_job(ctx.db, company=a["company"], title=a["title"], description=a["description"],
                                 location=a["location"] or "", url=a["url"] or "")
    m = job_svc.compute_match(ctx.db, ctx.profile, job)
    ctx.db.commit()
    return _match_summary(m)


def research_company(ctx: ToolContext, a: dict) -> dict:
    company = a["company"].strip()
    cutoff = datetime.now(UTC) - timedelta(days=14)
    cached = ctx.db.scalar(
        select(CompanyResearch).where(CompanyResearch.user_id == ctx.user_id, CompanyResearch.company.ilike(company))
        .order_by(CompanyResearch.created_at.desc())
    )
    if cached and (cached.created_at.replace(tzinfo=UTC) if not cached.created_at.tzinfo else cached.created_at) > cutoff \
            and not a["refresh"]:
        return {"research_id": cached.id, "cached": True, **cached.content}
    job = _job(ctx, a["job_id"]) if a["job_id"] else None
    out = ai_tasks.research_company(company, job)
    rec = CompanyResearch(user_id=ctx.user_id, company=company, job_id=job.id if job else None, content=out.model_dump())
    ctx.db.add(rec)
    ctx.db.flush()
    if job:
        applications.log_event_for_job(ctx.db, ctx.user_id, job.id, "research", {"research_id": rec.id})
    ctx.db.commit()
    return {"research_id": rec.id, "cached": False, **out.model_dump()}


def tailor_resume(ctx: ToolContext, a: dict) -> dict:
    job = _job(ctx, a["job_id"])
    m = _match(ctx, job)
    out, warnings = ai_tasks.tailor_resume(ctx.profile, job, m)
    rec = TailoredResume(user_id=ctx.user_id, job_id=job.id, content=out.model_dump(),
                         markdown=ai_tasks.tailored_markdown(ctx.profile, out), change_log=out.change_log,
                         warnings=warnings)
    ctx.db.add(rec)
    ctx.db.flush()
    applications.update(ctx.db, ctx.user_id, job.id, tailored_resume_id=rec.id)
    return {"tailored_resume_id": rec.id, "change_log": out.change_log, "keywords_covered": out.keywords_covered,
            "honest_gaps": out.honest_gaps, "fabrication_warnings": warnings,
            "note": "The user can review/download it in the UI. Surface any fabrication_warnings to them."}


def draft_outreach_message(ctx: ToolContext, a: dict) -> dict:
    job = _job(ctx, a["job_id"]) if a["job_id"] else None
    talking_points = None
    if job:
        r = ctx.db.scalar(select(CompanyResearch).where(CompanyResearch.user_id == ctx.user_id,
                                                        CompanyResearch.company.ilike(job.company))
                          .order_by(CompanyResearch.created_at.desc()))
        talking_points = (r.content or {}).get("talking_points") if r else None
    past = memory.recall(ctx.db, ctx.user_id, f"{a['recipient_name'] or ''} {job.company if job else ''} outreach",
                         kinds=["interaction", "feedback"], limit=5)
    context = "\n".join(filter(None, [a["context"] or "", *(f"[memory] {m.content}" for m in past)]))
    out = ai_tasks.generate_outreach(
        ctx.profile, job, kind=a["kind"], channel=a["channel"], recipient_name=a["recipient_name"] or "",
        recipient_role=a["recipient_role"] or "", context=context, talking_points=talking_points,
    )
    msg = OutreachMessage(
        user_id=ctx.user_id, job_id=job.id if job else None, kind=a["kind"],
        channel="linkedin" if a["channel"].startswith("linkedin") else "email",
        recipient_name=a["recipient_name"] or "", recipient_role=a["recipient_role"] or "",
        recipient_contact=(a["recipient_contact"] or "")[:255], subject=out.subject[:500], body=out.body, status="draft",
    )
    ctx.db.add(msg)
    ctx.db.commit()
    return {"message_id": msg.id, "subject": out.subject, "body": out.body, "status": "draft",
            "next": "Show the draft to the user. To send, call request_approval_to_send; never claim it was sent."}


def request_approval_to_send(ctx: ToolContext, a: dict) -> dict:
    msg = ctx.db.get(OutreachMessage, a["message_id"])
    if not msg or msg.user_id != ctx.user_id:
        raise ToolError("Message not found")
    if msg.status not in ("draft", "rejected"):
        raise ToolError(f"Message is already '{msg.status}'")
    req = approvals.propose(
        ctx.db, ctx.user_id, "send_outreach_message",
        summary=f"Send {msg.kind} {msg.channel} message to {msg.recipient_name or 'recipient'}: {a['reason']}",
        payload={"message_id": msg.id}, agent_run_id=ctx.run_id,
    )
    return {"approval_request_id": req.id, "status": "pending_human_approval",
            "note": "Nothing has been sent. The user must approve this in the Approvals inbox."}


def track_application(ctx: ToolContext, a: dict) -> dict:
    due = datetime.now(UTC) + timedelta(days=a["next_action_due_in_days"]) if a["next_action_due_in_days"] else None
    try:
        app = applications.update(ctx.db, ctx.user_id, a["job_id"], status=a["status"], notes=a["notes"],
                                  next_action=a["next_action"], next_action_due=due)
    except ValueError as e:
        raise ToolError(str(e)) from e
    return {"application_id": app.id, "job_id": app.job_id, "status": app.status, "next_action": app.next_action,
            "next_action_due": app.next_action_due.isoformat() if app.next_action_due else None}


def list_applications(ctx: ToolContext, a: dict) -> dict:
    stmt = select(Application).where(Application.user_id == ctx.user_id)
    if a["status"]:
        stmt = stmt.where(Application.status == a["status"])
    rows = ctx.db.scalars(stmt.order_by(Application.updated_at.desc()).limit(50)).all()
    return {"applications": [
        {"job_id": r.job_id, "company": r.job.company, "title": r.job.title, "status": r.status,
         "applied_at": r.applied_at.isoformat() if r.applied_at else None, "next_action": r.next_action,
         "notes": r.notes[:300]} for r in rows]}


def prioritize(ctx: ToolContext, a: dict) -> dict:
    return prioritization.recommend(ctx.db, ctx.user_id, limit=a["limit"] or 10)


def prepare_interview(ctx: ToolContext, a: dict) -> dict:
    job = _job(ctx, a["job_id"])
    r = ctx.db.scalar(select(CompanyResearch).where(CompanyResearch.user_id == ctx.user_id,
                                                    CompanyResearch.company.ilike(job.company))
                      .order_by(CompanyResearch.created_at.desc()))
    out = ai_tasks.interview_prep(ctx.profile, job, r.content if r else None, days=a["days"] or 7)
    rec = InterviewPrep(user_id=ctx.user_id, job_id=job.id, content=out.model_dump())
    ctx.db.add(rec)
    applications.log_event_for_job(ctx.db, ctx.user_id, job.id, "prep", {})
    ctx.db.commit()
    return {"interview_prep_id": rec.id, "role_summary": out.role_summary,
            "technical_topics": [t.topic for t in out.technical_topics], "study_plan_days": len(out.study_plan),
            "note": "Full prep (questions, guidance) is viewable in the UI."}


def save_memory(ctx: ToolContext, a: dict) -> dict:
    m = memory.remember(ctx.db, ctx.user_id, a["content"], kind=a["kind"], tags=a["tags"],
                        importance=a["importance"], source="agent", job_id=a["job_id"])
    return {"memory_id": m.id}


def recall_memories(ctx: ToolContext, a: dict) -> dict:
    mems = memory.recall(ctx.db, ctx.user_id, a["query"], job_id=a["job_id"], limit=a["limit"] or 10)
    return {"memories": [{"id": m.id, "kind": m.kind, "content": m.content, "created": m.created_at.date().isoformat()}
                         for m in mems]}


# ---------- registry ----------

TOOLS: list[Tool] = [
    Tool("get_candidate_profile", "Get the candidate's structured profile, preferences and which important fields are missing. Call this first in most tasks.", {}, get_candidate_profile),
    Tool("search_jobs",
         "Discover fresh job postings from configured company job boards (Greenhouse/Lever/Ashby), store them, and return them scored for this candidate (score 0-100 + eligibility). Network call; prefer list_known_jobs for jobs already found.",
         {"keywords": A("Keywords that must appear in title/description, e.g. ['machine learning']. Empty for all tech roles."),
          "companies": A("Restrict to these board names (e.g. ['stripe','openai']). Empty for all configured boards."),
          "levels": A("Filter levels", {"type": "string", "enum": LEVELS}),
          "work_modes": A("Filter work modes", {"type": "string", "enum": ["remote", "hybrid", "onsite"]}),
          "location": S("Substring the location must contain (remote jobs always pass)", nullable=True),
          "include_ineligible": {"type": "boolean", "description": "Include jobs the candidate is ineligible for"},
          "limit": I("Max results (default 15)", nullable=True)},
         search_jobs),
    Tool("list_known_jobs", "List jobs already stored in the database with their match scores (no network).",
         {"min_score": I("Minimum match score", nullable=True),
          "eligibility": S("Filter by eligibility", nullable=True, enum=["eligible", "uncertain", "ineligible"]),
          "query": S("Substring of title or company", nullable=True), "limit": I("Max results", nullable=True)},
         list_known_jobs),
    Tool("get_job_details", "Full job description plus the detailed match breakdown and application status.",
         {"job_id": I("Job id")}, get_job_details),
    Tool("evaluate_job_match", "Recompute the match score/eligibility for a job; with explain=true also produce a coach-style written explanation and recommendation.",
         {"job_id": I("Job id"), "explain": {"type": "boolean", "description": "Generate an LLM explanation"}},
         evaluate_job_match),
    Tool("add_job_from_text", "Add a job the user found elsewhere (pasted description) and score it.",
         {"company": S("Company"), "title": S("Job title"), "description": S("Full job description text"),
          "location": S("Location", nullable=True), "url": S("Posting URL", nullable=True)},
         add_job_from_text),
    Tool("research_company", "Research a company (web search): products, stack, culture, recent news, interview process, talking points. Cached for 14 days.",
         {"company": S("Company name"), "job_id": I("Related job id", nullable=True),
          "refresh": {"type": "boolean", "description": "Ignore cache"}},
         research_company),
    Tool("tailor_resume", "Create a truthful, job-specific version of the candidate's resume. Returns change log, honest gaps and fabrication warnings.",
         {"job_id": I("Job id")}, tailor_resume),
    Tool("draft_outreach_message", "Draft a personalized recruiter/referral/hiring-manager/follow-up/thank-you message. Saves it as a DRAFT; does not send.",
         {"job_id": I("Related job id", nullable=True),
          "kind": S("Message type", enum=["recruiter", "referral", "hiring_manager", "follow_up", "thank_you"]),
          "channel": S("Channel", enum=["email", "linkedin", "linkedin_note"]),
          "recipient_name": S("Recipient name if known", nullable=True),
          "recipient_role": S("Recipient role if known", nullable=True),
          "recipient_contact": S("Recipient email or profile URL if known", nullable=True),
          "context": S("Extra context: shared background, how they're connected, what to emphasize", nullable=True)},
         draft_outreach_message),
    Tool("request_approval_to_send", "Ask the human to approve sending a drafted message. This is the ONLY way any message can be sent. Returns immediately with a pending request.",
         {"message_id": I("Outreach message id"), "reason": S("Why this message should be sent now")},
         request_approval_to_send),
    Tool("track_application", "Create or update the application record for a job (status, notes, next action). Internal bookkeeping; no external effect.",
         {"job_id": I("Job id"), "status": S("New status", nullable=True, enum=list(APPLICATION_STATUSES)),
          "notes": S("Notes (replaces existing)", nullable=True), "next_action": S("Next action", nullable=True),
          "next_action_due_in_days": I("Days until next action is due", nullable=True)},
         track_application),
    Tool("list_applications", "List tracked applications, optionally by status.",
         {"status": S("Status filter", nullable=True, enum=list(APPLICATION_STATUSES))}, list_applications),
    Tool("prioritize_jobs", "Rank which unapplied jobs to apply to next and list follow-ups that are due.",
         {"limit": I("How many jobs", nullable=True)}, prioritize),
    Tool("prepare_interview", "Generate an interview prep plan (topics, questions, study plan) for a job.",
         {"job_id": I("Job id"), "days": I("Days available to prepare", nullable=True)}, prepare_interview),
    Tool("save_memory", "Persist a durable fact, preference or piece of feedback about the user for future sessions.",
         {"content": S("The memory, one self-contained sentence"),
          "kind": S("Kind", enum=["preference", "fact", "interaction", "feedback", "outcome"]),
          "importance": I("1 (trivial) to 5 (critical)"), "tags": A("Tags"), "job_id": I("Related job", nullable=True)},
         save_memory),
    Tool("recall_memories", "Search long-term memory about the user's past preferences, feedback and interactions.",
         {"query": S("What to look for"), "job_id": I("Related job", nullable=True), "limit": I("Max", nullable=True)},
         recall_memories),
]

TOOL_MAP = {t.name: t for t in TOOLS}


def definitions() -> list[dict[str, Any]]:
    return [t.definition() for t in TOOLS]
