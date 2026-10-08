from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.api import serializers as ser
from app.api.deps import current_profile, current_user, llm_errors
from app.db import get_db
from app.models import (
    Application, CandidateProfile, CompanyResearch, InterviewPrep, Job, JobMatch, OutreachMessage, TailoredResume, User,
)
from app.schemas import DiscoverRequest, ManualJob, PrepRequest, ResearchRequest
from app.services import ai_tasks, applications
from app.services import jobs as job_svc

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _get_job(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def _get_match(db: Session, profile: CandidateProfile, job: Job) -> JobMatch:
    m = db.scalar(select(JobMatch).where(JobMatch.user_id == profile.user_id, JobMatch.job_id == job.id))
    if m is None or m.profile_version != profile.version:
        m = job_svc.compute_match(db, profile, job)
        db.commit()
    return m


@router.post("/discover")
def discover(body: DiscoverRequest, profile: CandidateProfile = Depends(current_profile), db: Session = Depends(get_db)):
    res = job_svc.discover_jobs(db, profile, keywords=body.keywords, companies=body.companies, levels=body.levels,
                                work_modes=body.work_modes, location=body.location,
                                include_ineligible=body.include_ineligible, limit=body.limit)
    return {"fetched": res["fetched"], "relevant": res["relevant"], "errors": res["errors"],
            "matches": [ser.match(m) for m in res["matches"]]}


@router.get("")
def list_matches(
    min_score: float = 0, eligibility: str | None = None, q: str | None = None, level: str | None = None,
    work_mode: str | None = None, limit: int = Query(50, le=200), offset: int = 0,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    stmt = select(JobMatch).join(Job).where(JobMatch.user_id == user.id, Job.is_active.is_(True),
                                           JobMatch.score >= min_score)
    if eligibility:
        stmt = stmt.where(JobMatch.eligibility.in_(eligibility.split(",")))
    if level:
        stmt = stmt.where(Job.level.in_(level.split(",")))
    if work_mode:
        stmt = stmt.where(Job.work_mode.in_(work_mode.split(",")))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Job.title.ilike(like) | Job.company.ilike(like) | Job.location.ilike(like))
    rows = db.scalars(stmt.order_by(JobMatch.score.desc()).offset(offset).limit(limit)).all()
    statuses = dict(db.execute(select(Application.job_id, Application.status).where(Application.user_id == user.id)).all())
    return [ser.match(m, statuses.get(m.job_id)) for m in rows]


@router.post("/manual")
def add_manual(body: ManualJob, profile: CandidateProfile = Depends(current_profile), db: Session = Depends(get_db)):
    job = job_svc.add_manual_job(db, **body.model_dump())
    m = job_svc.compute_match(db, profile, job)
    db.commit()
    return ser.match(m)


@router.post("/refresh-matches")
def refresh(profile: CandidateProfile = Depends(current_profile), db: Session = Depends(get_db)):
    return {"rescored": job_svc.refresh_matches(db, profile)}


@router.get("/{job_id}")
def job_detail(job_id: int, profile: CandidateProfile = Depends(current_profile), db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    m = _get_match(db, profile, job)
    uid = profile.user_id
    app = db.scalar(select(Application).where(Application.user_id == uid, Application.job_id == job_id))

    def latest(model, *conds):
        return db.scalar(select(model).where(model.user_id == uid, *conds).order_by(model.created_at.desc()))

    research = latest(CompanyResearch, CompanyResearch.company.ilike(job.company))
    tailored = latest(TailoredResume, TailoredResume.job_id == job_id)
    prep = latest(InterviewPrep, InterviewPrep.job_id == job_id)
    msgs = db.scalars(select(OutreachMessage).where(OutreachMessage.user_id == uid, OutreachMessage.job_id == job_id)
                      .order_by(OutreachMessage.created_at.desc())).all()
    return {
        "job": ser.job(job, with_description=True),
        "match": ser.match(m, app.status if app else None),
        "application": ser.application(app, with_events=True) if app else None,
        "research": ser.research(research) if research else None,
        "tailored_resume": ser.tailored(tailored) if tailored else None,
        "interview_prep": ser.prep(prep) if prep else None,
        "messages": [ser.message(x) for x in msgs],
    }


@router.post("/{job_id}/explain")
def explain(job_id: int, profile: CandidateProfile = Depends(current_profile), db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    m = _get_match(db, profile, job)
    try:
        exp = ai_tasks.explain_match(profile, job, m)
    except llm.LLMError as e:
        raise llm_errors(e) from e
    m.explanation = exp.summary
    m.breakdown = {**m.breakdown, "llm": exp.model_dump()}
    db.commit()
    return ser.match(m)


@router.post("/{job_id}/research")
def research(job_id: int, body: ResearchRequest, profile: CandidateProfile = Depends(current_profile),
             db: Session = Depends(get_db)):
    from app.agent.tools import ToolContext, research_company

    _get_job(db, job_id)
    try:
        out = research_company(ToolContext(db, profile.user_id, None),
                               {"company": db.get(Job, job_id).company, "job_id": job_id, "refresh": body.refresh})
    except llm.LLMError as e:
        raise llm_errors(e) from e
    return ser.research(db.get(CompanyResearch, out["research_id"]))


@router.post("/{job_id}/tailor")
def tailor(job_id: int, profile: CandidateProfile = Depends(current_profile), db: Session = Depends(get_db)):
    job = _get_job(db, job_id)
    if not profile.experience and not profile.projects:
        raise HTTPException(400, "Upload a resume (or add experience/projects) before tailoring.")
    m = _get_match(db, profile, job)
    try:
        out, warnings = ai_tasks.tailor_resume(profile, job, m)
    except llm.LLMError as e:
        raise llm_errors(e) from e
    rec = TailoredResume(user_id=profile.user_id, job_id=job.id, content=out.model_dump(),
                         markdown=ai_tasks.tailored_markdown(profile, out), change_log=out.change_log, warnings=warnings)
    db.add(rec)
    db.flush()
    applications.update(db, profile.user_id, job.id, tailored_resume_id=rec.id)
    return ser.tailored(rec)


@router.get("/tailored/{tailored_id}/download", response_class=PlainTextResponse)
def download_tailored(tailored_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(TailoredResume, tailored_id)
    if not t or t.user_id != user.id:
        raise HTTPException(404, "Not found")
    return PlainTextResponse(t.markdown, headers={"Content-Disposition": f'attachment; filename="resume_{t.job_id}.md"'})


@router.post("/{job_id}/interview-prep")
def interview_prep(job_id: int, body: PrepRequest, profile: CandidateProfile = Depends(current_profile),
                   db: Session = Depends(get_db)):
    from app.agent.tools import ToolContext, prepare_interview

    _get_job(db, job_id)
    try:
        out = prepare_interview(ToolContext(db, profile.user_id, None), {"job_id": job_id, "days": body.days})
    except llm.LLMError as e:
        raise llm_errors(e) from e
    return ser.prep(db.get(InterviewPrep, out["interview_prep_id"]))
