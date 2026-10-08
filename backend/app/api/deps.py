"""Request dependencies.

Auth seam: JobJugaad currently runs as a single-user local app, so every request
resolves to the default local user. All data access is already scoped by user_id;
swapping this function for real authentication (session/JWT/OAuth) is the only
change needed to go multi-user.
"""

from __future__ import annotations

import os

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.db import get_db
from app.models import CandidateProfile, User

DEFAULT_EMAIL = os.environ.get("JOBJUGAAD_DEFAULT_USER_EMAIL", "local-user@jobjugaad.local")


def ensure_default_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == DEFAULT_EMAIL))
    if user is None:
        user = User(email=DEFAULT_EMAIL, display_name="")
        db.add(user)
        db.flush()
        db.add(CandidateProfile(user_id=user.id))
        db.commit()
    return user


def current_user(db: Session = Depends(get_db)) -> User:
    return ensure_default_user(db)


def current_profile(user: User = Depends(current_user), db: Session = Depends(get_db)) -> CandidateProfile:
    p = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id))
    if p is None:
        p = CandidateProfile(user_id=user.id)
        db.add(p)
        db.commit()
    return p


def llm_errors(e: Exception) -> HTTPException:
    if isinstance(e, llm.LLMUnavailable):
        return HTTPException(503, f"AI features unavailable: {e}")
    return HTTPException(502, f"AI task failed: {e}")
