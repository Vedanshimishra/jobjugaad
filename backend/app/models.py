"""ORM models. Every user-owned row carries user_id so the app is multi-user ready."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")

    profile: Mapped["CandidateProfile"] = relationship(back_populates="user", uselist=False)


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    # Facts (usually extracted from the resume, editable by the user)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    links: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    headline: Mapped[str] = mapped_column(String(500), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    education: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    experience: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    projects: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    certifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    graduation_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experience_months: Mapped[int] = mapped_column(Integer, default=0)

    # Preferences (always user-supplied)
    preferred_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_levels: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["internship", "new_grad", "entry"])
    preferred_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    work_modes: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["remote", "hybrid", "onsite"])
    willing_to_relocate: Mapped[bool] = mapped_column(Boolean, default=False)
    min_salary: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(8), default="USD")
    target_companies: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_technologies: Mapped[list[str]] = mapped_column(JSON, default=list)
    avoid_technologies: Mapped[list[str]] = mapped_column(JSON, default=list)
    # e.g. {"authorized_countries": ["US"], "needs_sponsorship": true, "notes": "F-1 OPT"}
    work_authorization: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    user: Mapped[User] = relationship(back_populates="profile")


class Resume(TimestampMixin, Base):
    __tablename__ = "resumes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(1024))
    content_type: Mapped[str] = mapped_column(String(128), default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    parsed: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    parse_method: Mapped[str] = mapped_column(String(32), default="")  # "llm" | "heuristic"
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "external_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))  # greenhouse | lever | ashby | manual
    external_id: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    location: Mapped[str] = mapped_column(String(500), default="")
    work_mode: Mapped[str] = mapped_column(String(16), default="unknown")  # remote|hybrid|onsite|unknown
    url: Mapped[str] = mapped_column(String(2048), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    employment_type: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(32), default="unknown")
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(8), default="")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class JobMatch(Base):
    __tablename__ = "job_matches"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    eligibility: Mapped[str] = mapped_column(String(16))  # eligible | ineligible | uncertain
    eligibility_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    strengths: Mapped[list[str]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[str]] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    profile_version: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    job: Mapped[Job] = relationship()


APPLICATION_STATUSES = (
    "saved", "preparing", "applied", "assessment", "interviewing", "offer", "rejected", "withdrawn", "ghosted",
)


class Application(TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(32), default="saved")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_action: Mapped[str] = mapped_column(String(500), default="")
    next_action_due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    tailored_resume_id: Mapped[int | None] = mapped_column(ForeignKey("tailored_resumes.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    job: Mapped[Job] = relationship()
    events: Mapped[list["ApplicationEvent"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="ApplicationEvent.created_at"
    )


class ApplicationEvent(TimestampMixin, Base):
    __tablename__ = "application_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # status_change | note | message | research | tailor | prep
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    application: Mapped[Application] = relationship(back_populates="events")


class CompanyResearch(TimestampMixin, Base):
    __tablename__ = "company_research"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company: Mapped[str] = mapped_column(String(255), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class TailoredResume(TimestampMixin, Base):
    __tablename__ = "tailored_resumes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    markdown: Mapped[str] = mapped_column(Text, default="")
    change_log: Mapped[list[str]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)


class OutreachMessage(TimestampMixin, Base):
    __tablename__ = "outreach_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))  # recruiter | referral | hiring_manager | follow_up | thank_you
    channel: Mapped[str] = mapped_column(String(32), default="email")  # email | linkedin
    recipient_name: Mapped[str] = mapped_column(String(255), default="")
    recipient_role: Mapped[str] = mapped_column(String(255), default="")
    recipient_contact: Mapped[str] = mapped_column(String(255), default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    # draft -> pending_approval -> approved -> sent | rejected | failed
    status: Mapped[str] = mapped_column(String(32), default="draft")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActionRequest(TimestampMixin, Base):
    """A consequential external action proposed by the agent or UI, gated on human approval."""

    __tablename__ = "action_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(String(1000))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # pending -> approved -> executed | failed ; or pending -> rejected
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    agent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InterviewPrep(TimestampMixin, Base):
    __tablename__ = "interview_preps"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AgentRun(TimestampMixin, Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    goal: Mapped[str] = mapped_column(Text)
    # queued | running | completed | failed | stopped
    status: Mapped[str] = mapped_column(String(16), default="queued")
    final_answer: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Full API message history (append-only) so a run can be continued with follow-ups.
    transcript: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentStep.index"
    )


class AgentStep(TimestampMixin, Base):
    __tablename__ = "agent_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # message | tool_call | tool_result | final | error
    tool_name: Mapped[str] = mapped_column(String(64), default="")
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    run: Mapped[AgentRun] = relationship(back_populates="steps")


class Memory(TimestampMixin, Base):
    __tablename__ = "memories"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # preference | fact | interaction | feedback | outcome
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    importance: Mapped[int] = mapped_column(Integer, default=3)  # 1..5
    source: Mapped[str] = mapped_column(String(32), default="user")  # user | agent | system
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
