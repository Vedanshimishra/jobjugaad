"""Long-term memory: preferences, facts, feedback and interaction history.

Retrieval is lexical (token overlap) weighted by importance and recency. It is
transparent, needs no embedding service, and is easy to swap for a vector store.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Memory

_STOP = set("a an the and or of to in for on with at by is are was were be i me my you it this that from as".split())


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#.]+", s.lower()) if t not in _STOP and len(t) > 1}


def remember(
    db: Session, user_id: int, content: str, *, kind: str = "fact", tags: list[str] | None = None,
    importance: int = 3, source: str = "user", job_id: int | None = None, commit: bool = True,
) -> Memory:
    content = content.strip()
    # De-duplicate exact repeats; bump importance instead.
    existing = db.scalar(select(Memory).where(Memory.user_id == user_id, Memory.content == content))
    if existing:
        existing.importance = max(existing.importance, importance)
        mem = existing
    else:
        mem = Memory(user_id=user_id, content=content, kind=kind, tags=tags or [], importance=max(1, min(5, importance)),
                     source=source, job_id=job_id)
        db.add(mem)
    if commit:
        db.commit()
    return mem


def recall(db: Session, user_id: int, query: str = "", *, kinds: list[str] | None = None, job_id: int | None = None,
           limit: int = 10) -> list[Memory]:
    stmt = select(Memory).where(Memory.user_id == user_id)
    if kinds:
        stmt = stmt.where(Memory.kind.in_(kinds))
    mems = db.scalars(stmt.order_by(Memory.created_at.desc()).limit(500)).all()
    q = _tokens(query)
    now = datetime.now(UTC)

    def score(m: Memory) -> float:
        created = m.created_at if m.created_at.tzinfo else m.created_at.replace(tzinfo=UTC)
        age_days = max(0.0, (now - created).total_seconds() / 86400)
        recency = math.exp(-age_days / 45)
        overlap = len(q & (_tokens(m.content) | {t.lower() for t in m.tags})) / len(q) if q else 0.0
        same_job = 1.0 if job_id and m.job_id == job_id else 0.0
        return 2.0 * overlap + 0.3 * m.importance + recency + 1.5 * same_job

    if q:  # with a query, keep only relevant memories plus always-important ones
        mems = [m for m in mems if q & (_tokens(m.content) | {t.lower() for t in m.tags}) or m.importance >= 4
                or (job_id and m.job_id == job_id)]
    return sorted(mems, key=score, reverse=True)[:limit]


def core_memories(db: Session, user_id: int, limit: int = 12) -> list[Memory]:
    """High-importance preferences/feedback always loaded into the agent's context."""
    return db.scalars(
        select(Memory)
        .where(Memory.user_id == user_id, Memory.kind.in_(["preference", "feedback"]), Memory.importance >= 4)
        .order_by(Memory.importance.desc(), Memory.created_at.desc())
        .limit(limit)
    ).all()
