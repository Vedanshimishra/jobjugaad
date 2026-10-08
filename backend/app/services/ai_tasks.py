"""LLM-backed tasks. Each takes plain domain objects, returns validated Pydantic output,
and never invents candidate facts: prompts carry the profile as the only source of truth
and outputs are post-checked where fabrication would be harmful (tailored resumes)."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from app import llm
from app.models import CandidateProfile, Job, JobMatch
from app.services.matching import candidate_skills
from app.services.skills import extract_skills

MAX_JD_CHARS = 24000


def profile_context(p: CandidateProfile, include_contact: bool = False) -> str:
    data = {
        "name": p.full_name,
        "headline": p.headline,
        "summary": p.summary,
        "location": p.location,
        "graduation_year": p.graduation_year,
        "experience_months": p.experience_months,
        "education": p.education,
        "experience": p.experience,
        "projects": p.projects,
        "skills": p.skills,
        "certifications": p.certifications,
        "links": p.links,
        "preferences": {
            "roles": p.preferred_roles, "levels": p.preferred_levels, "locations": p.preferred_locations,
            "work_modes": p.work_modes, "target_companies": p.target_companies,
            "must_have_technologies": p.required_technologies, "avoid_technologies": p.avoid_technologies,
        },
    }
    if include_contact:
        data["email"] = p.email
    return json.dumps(data, ensure_ascii=False, indent=1)


def job_context(job: Job) -> str:
    desc = job.description
    if len(desc) > MAX_JD_CHARS:
        desc = desc[:MAX_JD_CHARS] + "\n[description truncated for length]"
    return (
        f"Company: {job.company}\nTitle: {job.title}\nLocation: {job.location} ({job.work_mode})\n"
        f"Level (detected): {job.level}\nURL: {job.url}\n\nDescription:\n{desc}"
    )


# ---------- match explanation ----------

class MatchExplanation(BaseModel):
    recommendation: Literal["strong_apply", "apply", "stretch", "skip"]
    summary: str = Field(description="2-3 sentence plain-English verdict addressed to the candidate")
    reasons_for: list[str]
    reasons_against: list[str]
    how_to_improve_odds: list[str]


def explain_match(profile: CandidateProfile, job: Job, match: JobMatch) -> MatchExplanation:
    system = (
        "You are a candid career coach for students and new grads in software engineering and AI/ML. "
        "Explain whether a job is a good match. Ground every claim in the candidate profile, the job description "
        "and the computed score breakdown; do not invent experience. Be specific and honest, including about hard "
        "eligibility blockers (sponsorship, seniority, graduation timing)."
    )
    content = (
        f"<candidate>\n{profile_context(profile)}\n</candidate>\n\n<job>\n{job_context(job)}\n</job>\n\n"
        f"<computed_match score='{match.score}' eligibility='{match.eligibility}'>\n"
        f"{json.dumps({'breakdown': match.breakdown, 'eligibility_reasons': match.eligibility_reasons}, indent=1)}\n"
        "</computed_match>\n\nExplain this match."
    )
    return llm.structured(system=system, content=content, output=MatchExplanation, effort="low")


# ---------- company research ----------

class NewsItem(BaseModel):
    headline: str
    date: str
    why_it_matters: str


class Source(BaseModel):
    title: str
    url: str


class CompanyResearchOut(BaseModel):
    overview: str
    products: list[str]
    tech_stack: list[str]
    engineering_culture: str
    recent_news: list[NewsItem]
    interview_process: str
    team_or_role_insights: str
    talking_points: list[str] = Field(description="Specific hooks the candidate can use in outreach and interviews")
    red_flags: list[str]
    sources: list[Source]
    confidence: Literal["high", "medium", "low"]


def research_company(company: str, job: Job | None) -> CompanyResearchOut:
    role = f"\nThe candidate is considering this role:\n{job_context(job)[:6000]}" if job else ""
    notes_system = (
        "You research companies for a job candidate. Use web search to find current, factual information: what the "
        "company does, products, engineering stack and culture, recent news (last 12 months), and the interview "
        "process for early-career engineering roles. Cite sources inline with URLs. Say clearly when information "
        "could not be verified."
    )
    blocks = llm.freeform(
        system=notes_system, content=f"Research {company}.{role}", tools=llm.web_search_tool(max_uses=6)
    )
    notes = "\n".join(b.text for b in blocks if b.type == "text")
    sources: list[Source] = []
    for b in blocks:
        # A success result is a list of hits; an error result is a single object.
        if b.type == "web_search_tool_result" and isinstance(b.content, list):
            sources += [Source(title=r.title or r.url, url=r.url) for r in b.content if getattr(r, "url", None)]
    content = (
        f"<research_notes>\n{notes}\n</research_notes>\n<known_sources>\n"
        f"{json.dumps([s.model_dump() for s in sources[:15]])}\n</known_sources>\n\n"
        f"Organize the research about {company} into the schema. Only include facts present in the notes."
    )
    out = llm.structured(
        system="You turn research notes into a structured company brief. Do not add facts not in the notes.",
        content=content, output=CompanyResearchOut, effort="low",
    )
    if not out.sources and sources:
        out.sources = sources[:10]
    return out


# ---------- resume tailoring ----------

class TailoredRole(BaseModel):
    company: str
    title: str
    dates: str
    bullets: list[str]


class TailoredProject(BaseModel):
    name: str
    bullets: list[str]


class TailoredResumeOut(BaseModel):
    headline: str
    summary: str
    skills: list[str] = Field(description="Candidate's existing skills, re-ordered by relevance to the job")
    experience: list[TailoredRole]
    projects: list[TailoredProject]
    change_log: list[str] = Field(description="What changed and why, one line each")
    keywords_covered: list[str]
    honest_gaps: list[str] = Field(description="Job requirements the candidate genuinely lacks - do not paper over")


TAILOR_SYSTEM = """You tailor resumes for specific jobs. Hard rules:
1. Truthfulness is non-negotiable. Use ONLY facts in the candidate profile. Never add employers, titles, dates,
   degrees, metrics, or technologies the candidate has not listed. You may rephrase, reorder, merge, emphasize,
   and drop content.
2. Mirror the job's vocabulary where the candidate genuinely has the experience (e.g. 'REST APIs' vs 'web services').
3. Lead bullets with impact; keep numbers exactly as given; keep each bullet under ~30 words.
4. Order experience/projects and skills by relevance to the job. Keep to roughly one page of content.
5. List requirements the candidate lacks in honest_gaps instead of implying them."""


def tailor_resume(profile: CandidateProfile, job: Job, match: JobMatch | None) -> tuple[TailoredResumeOut, list[str]]:
    skills_info = json.dumps((match.breakdown or {}).get("skills", {})) if match else "{}"
    content = (
        f"<candidate>\n{profile_context(profile)}\n</candidate>\n\n<job>\n{job_context(job)}\n</job>\n\n"
        f"<skill_analysis>{skills_info}</skill_analysis>\n\nTailor the resume for this job."
    )
    out = llm.structured(system=TAILOR_SYSTEM, content=content, output=TailoredResumeOut, effort="high")
    return out, fabrication_warnings(profile, out)


def fabrication_warnings(profile: CandidateProfile, out: TailoredResumeOut) -> list[str]:
    """Flag technologies, employers or numbers in the tailored resume that are absent from the profile."""
    warnings: list[str] = []
    have = candidate_skills(profile)
    text = " ".join(
        [out.summary, out.headline, *out.skills, *(b for r in out.experience for b in r.bullets),
         *(b for p in out.projects for b in p.bullets)]
    )
    new_skills = [s for s in extract_skills(text) if s not in have]
    if new_skills:
        warnings.append(f"Mentions technologies not on your profile: {', '.join(new_skills)}. Verify or remove.")
    known_companies = {(e.get("company") or "").lower() for e in profile.experience or []}
    for role in out.experience:
        if role.company.lower() not in known_companies:
            warnings.append(f"Experience entry '{role.company}' is not on your profile.")
    source_text = json.dumps(profile.experience) + json.dumps(profile.projects) + (profile.summary or "")
    for num in set(re.findall(r"\b\d+(?:\.\d+)?%|\b\d{2,}[kKmMxX+]?\b", text)):
        if num not in source_text:
            warnings.append(f"Number '{num}' does not appear in your original resume. Verify it.")
    return warnings


def tailored_markdown(profile: CandidateProfile, out: TailoredResumeOut) -> str:
    lines = [f"# {profile.full_name or 'Your Name'}"]
    contact = " · ".join(filter(None, [profile.email, profile.phone, profile.location, *profile.links.values()]))
    if contact:
        lines.append(contact)
    lines += ["", f"**{out.headline}**", "", out.summary, "", "## Skills", ", ".join(out.skills), "", "## Experience"]
    for r in out.experience:
        lines += [f"### {r.title} — {r.company}  ", f"*{r.dates}*", *[f"- {b}" for b in r.bullets], ""]
    if out.projects:
        lines.append("## Projects")
        for p in out.projects:
            lines += [f"### {p.name}", *[f"- {b}" for b in p.bullets], ""]
    if profile.education:
        lines.append("## Education")
        for e in profile.education:
            lines.append(f"- **{e.get('school', '')}** — {e.get('degree', '')} {e.get('field', '')} ({e.get('end', '')})")
    return "\n".join(lines).strip() + "\n"


# ---------- outreach ----------

class OutreachOut(BaseModel):
    subject: str
    body: str
    personalization_used: list[str] = Field(description="Which specific facts made this message personal")


OUTREACH_GUIDE = {
    "recruiter": "A concise note to a recruiter expressing interest and asking to be considered.",
    "referral": "A respectful referral request to an employee (often an alum or someone with shared background). "
                "Make it easy to say yes: include the job link and a 2-line pitch they can forward.",
    "hiring_manager": "A note to the hiring manager connecting the candidate's work to the team's problems.",
    "follow_up": "A polite follow-up on an application or prior message; brief, adds one new piece of value.",
    "thank_you": "A post-interview thank-you that references something specific from the conversation.",
}


def generate_outreach(
    profile: CandidateProfile,
    job: Job | None,
    *,
    kind: str,
    channel: str,
    recipient_name: str = "",
    recipient_role: str = "",
    context: str = "",
    talking_points: list[str] | None = None,
) -> OutreachOut:
    limit = "under 300 characters (LinkedIn connection note)" if channel == "linkedin_note" else (
        "under 120 words" if channel == "linkedin" else "under 170 words")
    system = (
        "You write outreach messages for early-career software/AI candidates. Messages must be genuine, specific, "
        f"and short ({limit}). No flattery clichés, no 'I hope this finds you well', no exaggeration. Use only facts "
        "from the candidate profile. Sign with the candidate's first name. Leave [placeholders] for anything you "
        "don't know rather than guessing (e.g. how they know the recipient)."
    )
    content = (
        f"<candidate>\n{profile_context(profile)}\n</candidate>\n"
        + (f"<job>\n{job_context(job)[:8000]}\n</job>\n" if job else "")
        + f"<message_type>{kind}: {OUTREACH_GUIDE.get(kind, kind)}</message_type>\n<channel>{channel}</channel>\n"
        f"<recipient name='{recipient_name}' role='{recipient_role}'/>\n"
        + (f"<extra_context>{context}</extra_context>\n" if context else "")
        + (f"<company_talking_points>{json.dumps(talking_points)}</company_talking_points>\n" if talking_points else "")
        + "Write the message. For non-email channels, set subject to an empty string."
    )
    return llm.structured(system=system, content=content, output=OutreachOut, effort="medium")


# ---------- interview prep ----------

class Topic(BaseModel):
    topic: str
    why: str
    how_to_prepare: str


class Question(BaseModel):
    question: str
    what_they_assess: str
    answer_guidance: str = Field(description="Tailored hint referencing the candidate's real experience where possible")


class StudyDay(BaseModel):
    day: int
    focus: str
    tasks: list[str]


class InterviewPrepOut(BaseModel):
    role_summary: str
    likely_process: list[str]
    technical_topics: list[Topic]
    coding_questions: list[Question]
    system_design_or_ml_questions: list[Question]
    behavioral_questions: list[Question]
    resume_deep_dive: list[Question] = Field(description="Questions interviewers will ask about the candidate's own projects")
    questions_to_ask_them: list[str]
    study_plan: list[StudyDay]


def interview_prep(profile: CandidateProfile, job: Job, research: dict | None, days: int = 7) -> InterviewPrepOut:
    system = (
        "You are an interview coach for new-grad and intern software / AI-ML roles. Build a focused, realistic prep "
        "plan from the job description, the candidate's background and any company research. Prioritize what this "
        "specific role will test; reference the candidate's actual projects for behavioral and deep-dive answers."
    )
    content = (
        f"<candidate>\n{profile_context(profile)}\n</candidate>\n\n<job>\n{job_context(job)}\n</job>\n"
        + (f"<company_research>\n{json.dumps(research)[:8000]}\n</company_research>\n" if research else "")
        + f"\nCreate an interview prep plan with a {days}-day study plan."
    )
    return llm.structured(system=system, content=content, output=InterviewPrepOut, effort="medium")
