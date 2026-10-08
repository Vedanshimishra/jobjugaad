"""Request bodies. Responses are produced by app/api/serializers.py."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["internship", "new_grad", "entry", "mid", "senior", "unknown"]
WorkMode = Literal["remote", "hybrid", "onsite"]


class WorkAuthorization(BaseModel):
    authorized_countries: list[str] = Field(default_factory=list, description="ISO-ish codes, e.g. ['US','IN']")
    citizenship: list[str] = Field(default_factory=list)
    needs_sponsorship: bool | None = None
    has_clearance: bool = False
    notes: str = ""


class ProfileUpdate(BaseModel):
    # facts
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: dict[str, str] | None = None
    headline: str | None = None
    summary: str | None = None
    skills: list[str] | None = None
    education: list[dict] | None = None
    experience: list[dict] | None = None
    projects: list[dict] | None = None
    graduation_year: int | None = Field(None, ge=1990, le=2040)
    # preferences
    preferred_roles: list[str] | None = None
    preferred_levels: list[Level] | None = None
    preferred_locations: list[str] | None = None
    work_modes: list[WorkMode] | None = None
    willing_to_relocate: bool | None = None
    min_salary: int | None = Field(None, ge=0)
    salary_currency: str | None = None
    target_companies: list[str] | None = None
    required_technologies: list[str] | None = None
    avoid_technologies: list[str] | None = None
    work_authorization: WorkAuthorization | None = None


class DiscoverRequest(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    levels: list[Level] = Field(default_factory=list)
    work_modes: list[WorkMode] = Field(default_factory=list)
    location: str | None = None
    include_ineligible: bool = False
    limit: int = Field(30, ge=1, le=100)


class ManualJob(BaseModel):
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=20)
    location: str = ""
    url: str = ""


class ResearchRequest(BaseModel):
    refresh: bool = False


class PrepRequest(BaseModel):
    days: int = Field(7, ge=1, le=60)


class OutreachCreate(BaseModel):
    job_id: int | None = None
    kind: Literal["recruiter", "referral", "hiring_manager", "follow_up", "thank_you"]
    channel: Literal["email", "linkedin", "linkedin_note"] = "email"
    recipient_name: str = ""
    recipient_role: str = ""
    recipient_contact: str = ""
    context: str = ""


class OutreachEdit(BaseModel):
    subject: str | None = None
    body: str | None = None
    recipient_name: str | None = None
    recipient_role: str | None = None
    recipient_contact: str | None = None


class ApprovalRequestBody(BaseModel):
    reason: str = "Requested from the UI"


class Decision(BaseModel):
    approve: bool
    note: str = ""
    edits: OutreachEdit | None = None


class ApplicationUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None
    priority: int | None = Field(None, ge=0, le=3)
    next_action: str | None = None
    next_action_due: datetime | None = None


class MemoryCreate(BaseModel):
    content: str = Field(min_length=3)
    kind: Literal["preference", "fact", "interaction", "feedback", "outcome"] = "preference"
    importance: int = Field(3, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)


class AgentGoal(BaseModel):
    goal: str = Field(min_length=3, max_length=4000)


class AgentFollowUp(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
