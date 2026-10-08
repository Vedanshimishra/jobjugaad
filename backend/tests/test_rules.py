from datetime import date

from app.services.eligibility import check_eligibility
from app.services.jd_parser import detect_level, parse_requirements, parse_salary, required_years
from app.services.matching import score_job
from app.services.resume_parser import experience_months
from app.services.skills import extract_skills, normalize_skill

from .conftest import make_job, make_profile


def test_skill_extraction_avoids_false_positives():
    found = extract_skills("Experience with Go, C++, PyTorch and REST APIs. We love Google and CI pipelines.")
    assert {"go", "c++", "pytorch", "rest apis"} <= set(found)
    assert "c" not in found
    assert "spring" not in extract_skills("Spring 2026 internship")
    assert normalize_skill("ReactJS") == "react"
    assert normalize_skill("k8s") == "kubernetes"


def test_level_detection():
    assert detect_level("Software Engineering Intern, Summer 2026") == "internship"
    assert detect_level("Senior Software Engineer") == "senior"
    assert detect_level("Software Engineer, New Grad") == "new_grad"
    assert detect_level("Software Engineer", "Requires 5+ years of experience building systems") == "senior"
    assert detect_level("Software Engineer II") == "mid"


def test_requirements_and_years():
    d = ("Must be authorized to work in the US without sponsorship. 3+ years of professional experience. "
         "Graduating between December 2025 and June 2026.")
    req = parse_requirements(d)
    assert req.no_sponsorship
    assert 2025 in req.grad_years and 2026 in req.grad_years
    assert required_years(d) == 3
    assert required_years("2+ years of experience preferred") is None


def test_salary_parsing():
    assert parse_salary("Pay range: $120,000 - $150,000 per year") == (120000, 150000, "USD")
    assert parse_salary("$140k-$180k") == (140000, 180000, "USD")
    lo, hi, _ = parse_salary("$45 - $55/hour")
    assert lo == 45 * 2080 and hi == 55 * 2080


def test_sponsorship_blocker_makes_ineligible(db):
    p = make_profile(db, work_authorization={"authorized_countries": [], "needs_sponsorship": True})
    j = make_job(db, description="Python role. We are unable to sponsor visas for this position.")
    res = check_eligibility(p, j)
    assert res.verdict == "ineligible"
    assert any(r.check == "sponsorship" and r.status == "fail" for r in res.reasons)


def test_senior_role_is_ineligible_and_new_grad_eligible(db):
    p = make_profile(db)
    senior = make_job(db, title="Staff Engineer", level="senior")
    ng = make_job(db)
    assert check_eligibility(p, senior).verdict == "ineligible"
    assert check_eligibility(p, ng).verdict == "eligible"


def test_internship_requires_enrollment(db):
    p = make_profile(db, graduation_year=2024)
    j = make_job(db, title="SWE Intern", level="internship",
                 description="Must be currently enrolled in a BS program and returning to school after the internship.")
    assert check_eligibility(p, j, today=date(2026, 1, 15)).verdict == "ineligible"


def test_match_score_rewards_skills_and_penalizes_avoided(db):
    p = make_profile(db)
    good = make_job(db, description="Python, PyTorch, SQL, Docker. Build ML models. 0-1 years of experience.")
    bad = make_job(db, title="Software Engineer, New Grad", description="Java, Spring Boot, Angular, PHP, Kotlin.")
    g, b = score_job(p, good), score_job(p, bad)
    assert g.score > b.score
    assert "python" in g.breakdown["skills"]["matched_required"]

    p.avoid_technologies = ["PHP"]
    b2 = score_job(p, bad)
    assert b2.breakdown["avoid_penalty"] == 15 and b2.score < b.score


def test_ineligible_jobs_are_discounted(db):
    p = make_profile(db, work_authorization={"authorized_countries": [], "needs_sponsorship": True})
    j = make_job(db, description="Python, PyTorch. No visa sponsorship available.")
    r = score_job(p, j)
    assert r.eligibility.verdict == "ineligible"
    assert r.score == round(r.fit * 0.4, 1)


def test_experience_months_counts_internships_at_half():
    exp = [
        {"start": "2024-06", "end": "2024-08", "is_internship": True},
        {"start": "2025-01", "end": "2025-12", "is_internship": False},
    ]
    assert experience_months(exp) == 12 + 3 // 2
