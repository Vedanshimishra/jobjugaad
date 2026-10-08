"""Rule-based eligibility: hard constraints that make a candidate unable to apply.

Each check yields a reason with status pass | fail | unknown. The overall verdict:
  any fail     -> ineligible
  any unknown  -> uncertain   (needs the user's judgment or more info)
  otherwise    -> eligible
Eligibility is deliberately separate from fit: a 95% skill match you can't legally
take is not a good match.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date

from app.models import CandidateProfile, Job
from app.services.jd_parser import detect_countries, parse_requirements, required_years

LEVEL_ORDER = {"internship": 0, "new_grad": 1, "entry": 1, "mid": 2, "senior": 3}


@dataclass
class Reason:
    check: str
    status: str  # pass | fail | unknown
    detail: str


@dataclass
class EligibilityResult:
    verdict: str
    reasons: list[Reason]

    def as_dicts(self) -> list[dict]:
        return [asdict(r) for r in self.reasons]


def _degree_levels(profile: CandidateProfile) -> set[str]:
    out = set()
    for e in profile.education or []:
        deg = f"{e.get('degree', '')}".lower()
        if "ph" in deg and "d" in deg:
            out.add("phd")
        elif deg.startswith(("m", "master")) or "master" in deg or "m.s" in deg or "mtech" in deg:
            out.add("masters")
        elif deg:
            out.add("bachelors")
    return out


def check_eligibility(profile: CandidateProfile, job: Job, today: date | None = None) -> EligibilityResult:
    today = today or date.today()
    reasons: list[Reason] = []
    desc = job.description or ""
    req = parse_requirements(desc)
    years_exp = (profile.experience_months or 0) / 12
    auth = profile.work_authorization or {}
    needs_sponsorship = auth.get("needs_sponsorship")
    authorized = {c.upper() for c in auth.get("authorized_countries", [])}
    is_citizen_of = {c.upper() for c in auth.get("citizenship", [])}

    # 1. Seniority
    if job.level == "senior":
        reasons.append(Reason("seniority", "fail", f"Role is senior-level ('{job.title}'); targets 0-2 YOE profiles poorly."))
    elif job.level == "mid":
        status = "unknown" if years_exp >= 1.5 else "fail"
        reasons.append(Reason("seniority", status, "Mid-level role (typically 2-4 years experience)."))
    elif job.level == "internship":
        reasons.append(Reason("seniority", "pass", "Internship role."))
    elif job.level in ("new_grad", "entry"):
        reasons.append(Reason("seniority", "pass", f"{job.level.replace('_', ' ').title()} role."))
    else:
        reasons.append(Reason("seniority", "unknown", "Could not determine seniority level from the posting."))

    # 2. Years of experience
    req_years = required_years(desc)
    if req_years is not None:
        if req_years <= years_exp + 0.25:
            reasons.append(Reason("experience", "pass", f"Requires {req_years:g}+ yrs; you have ~{years_exp:.1f}."))
        elif req_years <= years_exp + 1:
            reasons.append(Reason("experience", "unknown", f"Requires {req_years:g}+ yrs; you have ~{years_exp:.1f} (stretch)."))
        else:
            reasons.append(Reason("experience", "fail", f"Requires {req_years:g}+ yrs; you have ~{years_exp:.1f}."))

    # 3. Graduation timing
    gy = profile.graduation_year
    if job.level == "internship" and req.enrolled_student_required:
        if gy is None:
            reasons.append(Reason("enrollment", "unknown", "Requires current enrollment; graduation year not set."))
        elif gy < today.year or (gy == today.year and today.month > 6):
            reasons.append(Reason("enrollment", "fail", f"Requires current enrollment; you graduate(d) in {gy}."))
        else:
            reasons.append(Reason("enrollment", "pass", f"Requires current enrollment; you graduate in {gy}."))
    # Cohort year in the title: "Intern (2027)", "Summer 2027", "New Grad 2026".
    title_years = [int(y) for y in re.findall(r"\b(20[2-3]\d)\b", job.title or "")]
    if title_years and gy is not None:
        y = max(title_years)
        if job.level == "internship":
            if gy < y:
                reasons.append(Reason("cohort", "fail", f"{y} internship; you graduate in {gy} and won't be a student then."))
            elif gy == y:
                reasons.append(Reason("cohort", "unknown", f"{y} internship and you graduate in {gy}; depends on your graduation month."))
            else:
                reasons.append(Reason("cohort", "pass", f"{y} internship; you're still a student then (graduating {gy})."))
        elif job.level == "new_grad":
            ok = y - 1 <= gy <= y
            reasons.append(Reason("cohort", "pass" if ok else "fail", f"Targets the {y} new-grad cohort; you graduate in {gy}."))
    if req.grad_years:
        if gy is None:
            reasons.append(Reason("graduation_year", "unknown", f"Posting targets graduates of {req.grad_years}; set your graduation year."))
        elif gy in req.grad_years or (min(req.grad_years) <= gy <= max(req.grad_years)):
            reasons.append(Reason("graduation_year", "pass", f"Targets {req.grad_years}; you graduate in {gy}."))
        else:
            reasons.append(Reason("graduation_year", "fail", f"Targets graduates of {req.grad_years}; you graduate in {gy}."))

    # 4. Work authorization
    job_countries = detect_countries(job.location)
    remote_anywhere = job.work_mode == "remote" and not job_countries
    if job_countries and authorized:
        if job_countries & authorized:
            reasons.append(Reason("work_authorization", "pass", f"Authorized to work in {', '.join(sorted(job_countries & authorized))}."))
        elif needs_sponsorship and req.no_sponsorship:
            reasons.append(Reason("work_authorization", "fail", "Job location requires authorization you don't have and the posting says no sponsorship."))
        else:
            reasons.append(Reason("work_authorization", "unknown", f"Job is in {', '.join(sorted(job_countries))}; you'd likely need a visa/sponsorship."))
    elif not authorized and not remote_anywhere:
        reasons.append(Reason("work_authorization", "unknown", "Set your work authorization to evaluate location eligibility."))

    if req.no_sponsorship:
        if needs_sponsorship is True:
            reasons.append(Reason("sponsorship", "fail", "Posting states no visa sponsorship; you indicated you need sponsorship."))
        elif needs_sponsorship is None:
            reasons.append(Reason("sponsorship", "unknown", "Posting states no visa sponsorship; your sponsorship needs are not set."))
        else:
            reasons.append(Reason("sponsorship", "pass", "No sponsorship offered; you don't need it."))

    if req.citizenship_required:
        if "US" in is_citizen_of:
            reasons.append(Reason("citizenship", "pass", "US citizenship required; you are a US citizen."))
        elif is_citizen_of:
            reasons.append(Reason("citizenship", "fail", "US citizenship required."))
        else:
            reasons.append(Reason("citizenship", "unknown", "US citizenship required; citizenship not specified in profile."))
    if req.clearance_required:
        has = bool(auth.get("has_clearance"))
        reasons.append(Reason("clearance", "pass" if has else "unknown", "Security clearance required."))

    # 5. Degree
    degrees = _degree_levels(profile)
    phd_role = req.phd_required or bool(re.search(r"\bph\.?d\b", job.title or "", re.I))
    if phd_role and "phd" not in degrees:
        reasons.append(Reason("degree", "fail", "PhD role / PhD required."))
    elif req.masters_required and not degrees & {"masters", "phd"}:
        in_progress = gy is not None and gy >= today.year
        reasons.append(Reason("degree", "unknown" if in_progress else "fail", "Master's degree required."))
    elif req.degree_required and not degrees:
        reasons.append(Reason("degree", "unknown", "Degree required; no education on profile."))

    if any(r.status == "fail" for r in reasons):
        verdict = "ineligible"
    elif any(r.status == "unknown" for r in reasons):
        verdict = "uncertain"
    else:
        verdict = "eligible"
    return EligibilityResult(verdict, reasons)
