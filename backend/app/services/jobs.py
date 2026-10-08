"""Job discovery, normalization, persistence and match computation."""

from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CandidateProfile, Job, JobMatch
from app.services.jd_parser import detect_level, detect_work_mode, parse_salary
from app.services.job_sources.base import RawJob
from app.services.job_sources.providers import SOURCES
from app.services.matching import score_job

log = logging.getLogger(__name__)
settings = get_settings()

TECH_TITLE = re.compile(
    r"\b(software|engineer|engineering|developer|swe|sde|machine\s+learning|ml|ai|artificial\s+intelligence|"
    r"data\s+(scientist|engineer)|backend|back[\s-]end|frontend|front[\s-]end|full[\s-]?stack|infrastructure|"
    r"platform|devops|sre|reliability|research\s+(engineer|scientist)|applied\s+scientist|mobile|ios|android)\b",
    re.I,
)
NON_TECH = re.compile(r"\b(sales|account\s+executive|recruit|marketing|legal|counsel|finance|accountant|hr\b|people\s+partner)\b", re.I)


def configured_boards() -> list[tuple[str, str]]:
    def split(s: str) -> list[str]:
        return [x.strip() for x in s.split(",") if x.strip()]

    return (
        [("greenhouse", b) for b in split(settings.greenhouse_boards)]
        + [("lever", b) for b in split(settings.lever_companies)]
        + [("ashby", b) for b in split(settings.ashby_boards)]
    )


def is_relevant_title(title: str) -> bool:
    return bool(TECH_TITLE.search(title)) and not NON_TECH.search(title)


def upsert_job(db: Session, raw: RawJob, existing: dict[tuple[str, str], Job] | None = None) -> Job:
    if existing is not None:
        job = existing.get((raw.source, raw.external_id))
    else:
        job = db.scalar(select(Job).where(Job.source == raw.source, Job.external_id == raw.external_id))
    if job is None:
        job = Job(source=raw.source, external_id=raw.external_id)
        db.add(job)
        if existing is not None:
            existing[(raw.source, raw.external_id)] = job  # guards against duplicate postings in one batch
    # Truncate to column sizes (Postgres enforces VARCHAR lengths; SQLite does not).
    job.company = raw.company[:255]
    job.title = raw.title[:500]
    job.location = raw.location[:500]
    job.url = raw.url[:2048]
    job.description = raw.description
    job.employment_type = (raw.employment_type or "")[:64]
    job.posted_at = raw.posted_at
    job.work_mode = detect_work_mode(raw.location, raw.description, raw.work_mode_hint)
    job.level = detect_level(raw.title, raw.description)
    if raw.salary_max:
        job.salary_min, job.salary_max, job.salary_currency = raw.salary_min, raw.salary_max, raw.salary_currency
    else:
        job.salary_min, job.salary_max, job.salary_currency = parse_salary(raw.description)
    job.is_active = True
    return job


def add_manual_job(db: Session, *, company: str, title: str, description: str, location: str = "", url: str = "") -> Job:
    ext = hashlib.sha1(f"{company}|{title}|{url or description[:200]}".encode()).hexdigest()[:16]
    job = upsert_job(db, RawJob(source="manual", external_id=ext, company=company, title=title,
                                location=location, url=url, description=description))
    db.commit()
    return job


def fetch_boards(boards: list[tuple[str, str]]) -> tuple[list[RawJob], list[str]]:
    raws: list[RawJob] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(SOURCES[src].fetch, board): (src, board) for src, board in boards if src in SOURCES}
        for fut in as_completed(futures):
            src, board = futures[fut]
            try:
                raws.extend(fut.result())
            except (httpx.HTTPError, ValueError, KeyError) as e:
                log.warning("Fetching %s/%s failed: %s", src, board, e)
                errors.append(f"{src}/{board}: {type(e).__name__}")
    return raws, errors


def compute_match(db: Session, profile: CandidateProfile, job: Job,
                  existing: dict[int, JobMatch] | None = None) -> JobMatch:
    result = score_job(profile, job)
    if existing is not None:
        m = existing.get(job.id)
    else:
        m = db.scalar(select(JobMatch).where(JobMatch.user_id == profile.user_id, JobMatch.job_id == job.id))
    if m is None:
        m = JobMatch(user_id=profile.user_id, job_id=job.id)
        db.add(m)
    elif m.profile_version != profile.version or m.score != result.score:
        m.explanation = ""  # narrative is stale once inputs change
    m.score = result.score
    m.breakdown = result.breakdown
    m.eligibility = result.eligibility.verdict
    m.eligibility_reasons = result.eligibility.as_dicts()
    m.strengths = result.strengths
    m.gaps = result.gaps
    m.profile_version = profile.version
    m.job = job
    return m


def discover_jobs(
    db: Session,
    profile: CandidateProfile,
    *,
    keywords: list[str] | None = None,
    companies: list[str] | None = None,
    levels: list[str] | None = None,
    work_modes: list[str] | None = None,
    location: str | None = None,
    include_ineligible: bool = False,
    limit: int = 20,
) -> dict:
    """Fetch configured boards (optionally a subset), store relevant jobs, score them, return the best."""
    boards = configured_boards()
    if companies:
        wanted = {c.lower().replace(" ", "") for c in companies}
        boards = [b for b in boards if b[1].lower().replace("-", "") in wanted] or boards

    raws, errors = fetch_boards(boards)
    kw = [k.lower() for k in keywords or [] if k.strip()]
    stored: list[Job] = []
    # Preload rows once instead of one SELECT per posting.
    known = {(j.source, j.external_id): j for j in db.scalars(
        select(Job).where(Job.source.in_({r.source for r in raws}))).all()}
    for raw in raws:
        if not is_relevant_title(raw.title):
            continue
        hay = f"{raw.title} {raw.description}".lower()
        if kw and not any(k in hay for k in kw):
            continue
        if location and location.lower() not in raw.location.lower() and "remote" not in raw.location.lower():
            continue
        stored.append(upsert_job(db, raw, known))
    db.flush()

    existing_matches = {m.job_id: m for m in db.scalars(
        select(JobMatch).where(JobMatch.user_id == profile.user_id)).all()}
    matches = []
    for job in stored:
        if levels and job.level not in levels and job.level != "unknown":
            continue
        if work_modes and job.work_mode not in work_modes and job.work_mode != "unknown":
            continue
        m = compute_match(db, profile, job, existing_matches)
        if include_ineligible or m.eligibility != "ineligible":
            matches.append(m)
    db.commit()
    matches.sort(key=lambda m: m.score, reverse=True)
    cap = min(limit, settings.agent_max_jobs_per_search)
    return {
        "fetched": len(raws),
        "relevant": len(stored),
        "returned": min(cap, len(matches)),
        "errors": errors,
        "matches": matches[:cap],
    }


def refresh_matches(db: Session, profile: CandidateProfile) -> int:
    jobs = db.scalars(select(Job).where(Job.is_active.is_(True))).all()
    existing = {m.job_id: m for m in db.scalars(select(JobMatch).where(JobMatch.user_id == profile.user_id)).all()}
    for job in jobs:
        compute_match(db, profile, job, existing)
    db.commit()
    return len(jobs)
