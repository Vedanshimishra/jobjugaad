from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api import serializers as ser
from app.api.deps import current_profile, current_user
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import CandidateProfile, Resume, User
from app.schemas import ProfileUpdate
from app.services import jobs as job_svc
from app.services.resume_parser import SUPPORTED, apply_to_profile, experience_months, parse_resume
from app.services.skills import normalize_skills

router = APIRouter(tags=["profile"])
settings = get_settings()
MAX_UPLOAD = 10 * 1024 * 1024


def _refresh_matches_bg(user_id: int) -> None:
    db = SessionLocal()
    try:
        p = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user_id))
        if p:
            job_svc.refresh_matches(db, p)
    finally:
        db.close()


@router.get("/profile")
def get_profile(profile: CandidateProfile = Depends(current_profile)):
    return ser.profile(profile)


@router.put("/profile")
def update_profile(body: ProfileUpdate, bg: BackgroundTasks, profile: CandidateProfile = Depends(current_profile),
                   db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    if "skills" in data and data["skills"] is not None:
        data["skills"] = normalize_skills(data["skills"])
    if "work_authorization" in data and data["work_authorization"] is not None:
        wa = data["work_authorization"]
        wa["authorized_countries"] = [c.strip().upper() for c in wa.get("authorized_countries", []) if c.strip()]
        wa["citizenship"] = [c.strip().upper() for c in wa.get("citizenship", []) if c.strip()]
    for k, v in data.items():
        setattr(profile, k, v)
    if "experience" in data:
        profile.experience_months = experience_months(profile.experience or [])
    profile.version += 1
    db.commit()
    bg.add_task(_refresh_matches_bg, profile.user_id)
    return ser.profile(profile)


@router.post("/resumes")
async def upload_resume(file: UploadFile, bg: BackgroundTasks, user: User = Depends(current_user),
                        profile: CandidateProfile = Depends(current_profile), db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use one of {sorted(SUPPORTED)}.")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 10 MB).")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{user.id}_{uuid.uuid4().hex}{ext}"
    path.write_bytes(data)

    from starlette.concurrency import run_in_threadpool  # parsing may call the LLM; keep the event loop free

    try:
        text, parsed, method = await run_in_threadpool(parse_resume, path)
    except ValueError as e:
        path.unlink(missing_ok=True)
        raise HTTPException(422, str(e)) from e

    db.execute(update(Resume).where(Resume.user_id == user.id).values(is_primary=False))
    r = Resume(user_id=user.id, filename=(file.filename or path.name)[:255], stored_path=str(path),
               content_type=file.content_type or "", raw_text=text, parsed=parsed.model_dump(), parse_method=method,
               is_primary=True)
    db.add(r)
    apply_to_profile(profile, parsed)
    db.commit()
    bg.add_task(_refresh_matches_bg, user.id)
    return {"resume": ser.resume(r, full=True), "profile": ser.profile(profile),
            "warning": None if method == "llm" else
            "AI parsing was unavailable, so only basic fields were extracted. Please review and complete your profile."}


@router.get("/resumes")
def list_resumes(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at.desc())).all()
    return [ser.resume(r) for r in rows]


@router.get("/resumes/{resume_id}")
def get_resume(resume_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(Resume, resume_id)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "Resume not found")
    return ser.resume(r, full=True)
