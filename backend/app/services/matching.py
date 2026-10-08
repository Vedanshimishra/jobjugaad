"""Explainable job-match scoring (0-100).

score = sum(weight_i * component_i)  -> fit (0-100)
      - avoided-technology penalty
      * eligibility multiplier (ineligible 0.4, uncertain 0.85)

Every component reports its inputs so the UI and the agent can explain the number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models import CandidateProfile, Job
from app.services.eligibility import EligibilityResult, check_eligibility
from app.services.jd_parser import detect_countries
from app.services.skills import category, extract_skills, normalize_skill, normalize_skills

WEIGHTS = {"skills": 40, "role": 20, "level": 15, "location": 10, "preferences": 10, "compensation": 5}
SKILL_SMOOTHING = 1.5
ELIGIBILITY_MULTIPLIER = {"eligible": 1.0, "uncertain": 0.85, "ineligible": 0.4}

_PREFERRED_HEADER = re.compile(
    r"(preferred|nice[\s-]to[\s-]have|bonus|pluses|plus\s+if|desired|good\s+to\s+have)[^\n]{0,40}(qualifications|skills|points)?",
    re.I,
)
_STOP = {"the", "and", "of", "i", "ii", "iii", "role", "new", "grad", "intern", "internship", "sr", "jr", "senior", "junior"}
_GENERIC = {"engineer", "engineering", "developer", "scientist", "specialist", "associate"}


@dataclass
class MatchResult:
    score: float
    fit: float
    eligibility: EligibilityResult
    breakdown: dict
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


def candidate_skills(profile: CandidateProfile) -> set[str]:
    skills = set(normalize_skills(profile.skills or []))
    for item in [*(profile.experience or []), *(profile.projects or [])]:
        skills.update(normalize_skills(item.get("skills", []) or []))
        text = " ".join([item.get("title", ""), item.get("name", ""), item.get("description", ""), *item.get("bullets", [])])
        skills.update(extract_skills(text))
    return skills


def split_required_preferred(description: str) -> tuple[str, str]:
    m = _PREFERRED_HEADER.search(description or "")
    if not m:
        return description or "", ""
    return description[: m.start()], description[m.start():]


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z+#]+", s.lower()) if t not in _STOP and len(t) > 1}


def _role_score(profile: CandidateProfile, job: Job, job_skills: list[str]) -> tuple[float, str]:
    roles = profile.preferred_roles or []
    if not roles:
        return 0.7, "No preferred roles set."
    title_tokens = _tokens(job.title)
    best, best_role = 0.0, ""

    def w(t: str) -> float:  # generic job words count for little on their own
        return 0.25 if t in _GENERIC else 1.0

    for role in roles:
        rt = _tokens(role)
        if not rt:
            continue
        overlap = sum(w(t) for t in rt & title_tokens) / sum(w(t) for t in rt)
        if overlap > best:
            best, best_role = overlap, role
    # Domain affinity: an ML-heavy posting counts toward "AI/ML" style preferences.
    wants_ml = any(re.search(r"\b(ai|ml|machine learning|data scien)", r, re.I) for r in roles)
    ml_share = sum(1 for s in job_skills if category(s) == "ml") / max(1, len(job_skills))
    if wants_ml and ml_share >= 0.25:
        best = max(best, 0.75)
    generic_swe = re.search(r"\bsoftware\b|\bswe\b|\bdeveloper\b", job.title, re.I) and any(
        re.search(r"software|swe|backend|full[\s-]?stack|developer", r, re.I) for r in roles
    )
    if generic_swe:
        best = max(best, 0.6)
    detail = f"Best match '{best_role}'" if best_role else "Title doesn't match preferred roles"
    return min(best, 1.0), detail


def _level_score(profile: CandidateProfile, job: Job) -> tuple[float, str]:
    prefs = set(profile.preferred_levels or [])
    if job.level in prefs:
        return 1.0, f"{job.level} is a preferred level"
    # Unlabeled postings at large companies are usually experienced roles.
    return {"unknown": 0.3, "entry": 0.7, "new_grad": 0.7, "internship": 0.4, "mid": 0.2, "senior": 0.0}.get(
        job.level, 0.3
    ), f"Level '{job.level}' not in preferences"


def _location_score(profile: CandidateProfile, job: Job) -> tuple[float, str]:
    modes = set(profile.work_modes or [])
    mode_ok = job.work_mode == "unknown" or not modes or job.work_mode in modes
    if not mode_ok:
        return 0.1, f"Work mode '{job.work_mode}' not in your preferences"
    if job.work_mode == "remote":
        return 1.0, "Remote"
    prefs = [p.lower() for p in profile.preferred_locations or []]
    if not prefs:
        return 0.7, "No location preference set"
    loc = (job.location or "").lower()
    if any(p in loc for p in prefs if p not in ("remote", "anywhere")):
        return 1.0, f"In a preferred location ({job.location})"
    pref_countries = set().union(*(detect_countries(p) for p in prefs)) if prefs else set()
    if pref_countries & detect_countries(job.location):
        return 0.7, "Same country as a preferred location"
    return (0.4 if profile.willing_to_relocate else 0.15), f"Outside preferred locations ({job.location or 'unspecified'})"


def score_job(profile: CandidateProfile, job: Job) -> MatchResult:
    elig = check_eligibility(profile, job)
    cand = candidate_skills(profile)
    required_text, preferred_text = split_required_preferred(job.description)
    req_skills = extract_skills(f"{job.title}\n{required_text}")
    pref_skills = [s for s in extract_skills(preferred_text) if s not in req_skills]
    all_job_skills = req_skills + pref_skills

    # skills: required count 1.0, preferred 0.5
    total = len(req_skills) + 0.5 * len(pref_skills)
    if total == 0:
        # No recognizable technologies: likely a non-software or niche role. Don't reward it.
        skill_score, matched_req, missing_req, matched_pref = 0.3, [], [], []
    else:
        matched_req = [s for s in req_skills if s in cand]
        matched_pref = [s for s in pref_skills if s in cand]
        missing_req = [s for s in req_skills if s not in cand]
        # Smoothed toward a 0.4 prior so 1/1 matched skills isn't treated as a perfect fit.
        k = SKILL_SMOOTHING
        skill_score = (len(matched_req) + 0.5 * len(matched_pref) + 0.4 * k) / (total + k)

    role_score, role_detail = _role_score(profile, job, all_job_skills)
    level_score, level_detail = _level_score(profile, job)
    loc_score, loc_detail = _location_score(profile, job)

    # preferences: required technologies + target companies
    must = normalize_skills(profile.required_technologies or [])
    must_hit = [t for t in must if t in all_job_skills]
    pref_score = (len(must_hit) / len(must)) if must else 0.6
    target = any(c.lower() in job.company.lower() for c in profile.target_companies or [] if c)
    if target:
        pref_score = min(1.0, pref_score + 0.5)

    # compensation
    if profile.min_salary and job.salary_max:
        comp_score = 1.0 if job.salary_max >= profile.min_salary else 0.2
        comp_detail = f"Posted up to {job.salary_max:,} {job.salary_currency}"
    else:
        comp_score, comp_detail = 0.6, "Salary not posted or no minimum set"

    components = {
        "skills": (skill_score, f"{len(matched_req)}/{len(req_skills)} required, {len(matched_pref)}/{len(pref_skills)} preferred"),
        "role": (role_score, role_detail),
        "level": (level_score, level_detail),
        "location": (loc_score, loc_detail),
        "preferences": (pref_score, ("Target company. " if target else "") + (f"Has {len(must_hit)}/{len(must)} must-have techs" if must else "No must-have techs set")),
        "compensation": (comp_score, comp_detail),
    }
    fit = sum(WEIGHTS[k] * v for k, (v, _) in components.items())

    avoid = {normalize_skill(t) for t in profile.avoid_technologies or []}
    avoided = [s for s in req_skills if s in avoid]
    penalty = min(30, 15 * len(avoided))
    multiplier = ELIGIBILITY_MULTIPLIER[elig.verdict]
    score = round(max(0.0, fit - penalty) * multiplier, 1)

    breakdown = {
        "components": {
            k: {"score": round(v, 3), "weight": WEIGHTS[k], "points": round(WEIGHTS[k] * v, 1), "detail": d}
            for k, (v, d) in components.items()
        },
        "fit": round(fit, 1),
        "avoid_penalty": penalty,
        "avoided_technologies": avoided,
        "eligibility_multiplier": multiplier,
        "skills": {
            "required": req_skills, "preferred": pref_skills,
            "matched_required": matched_req, "missing_required": missing_req, "matched_preferred": matched_pref,
        },
        "target_company": target,
    }

    strengths, gaps = [], []
    if matched_req:
        strengths.append(f"Matches required skills: {', '.join(matched_req[:8])}")
    if target:
        strengths.append(f"{job.company} is on your target list")
    if level_score >= 1:
        strengths.append(level_detail)
    if loc_score >= 1:
        strengths.append(loc_detail)
    if missing_req:
        gaps.append(f"Missing required skills: {', '.join(missing_req[:8])}")
    if total == 0:
        gaps.append("No recognizable software/ML technologies in the posting; check the role is what you want")
    if avoided:
        gaps.append(f"Uses technologies you want to avoid: {', '.join(avoided)}")
    if loc_score < 0.5:
        gaps.append(loc_detail)
    gaps += [r.detail for r in elig.reasons if r.status == "fail"]

    return MatchResult(score=score, fit=round(fit, 1), eligibility=elig, breakdown=breakdown, strengths=strengths, gaps=gaps)
