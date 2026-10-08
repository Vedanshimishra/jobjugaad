from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

import httpx

from app.config import get_settings


@dataclass
class RawJob:
    source: str
    external_id: str
    company: str
    title: str
    location: str = ""
    url: str = ""
    description: str = ""  # plain text
    employment_type: str = ""
    work_mode_hint: str = ""
    posted_at: datetime | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = ""
    extra: dict = field(default_factory=dict)


class JobSource(Protocol):
    name: str

    def fetch(self, board: str) -> list[RawJob]: ...


def http_client() -> httpx.Client:
    return httpx.Client(
        timeout=get_settings().http_timeout_s,
        headers={"User-Agent": "JobJugaad/0.1 (job-search assistant)"},
        follow_redirects=True,
    )


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
