"""Deterministic signal extraction from job titles/descriptions.

These heuristics run on every job (cheap, reproducible) and feed eligibility and
scoring. The LLM is only used on top for narrative explanations.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from functools import lru_cache

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/div)\s*/?>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "\n- ", text)
    text = _TAG.sub(" ", html.unescape(text))
    text = _WS.sub(" ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


# ---------- level ----------

_INTERN = re.compile(r"\b(intern|internship|co-?op|apprentice(ship)?)\b", re.I)
_NEW_GRAD = re.compile(
    r"\b(new[\s-]?grad(uate)?s?|university\s+grad(uate)?|early[\s-]career|recent\s+grad(uate)?s?|"
    r"graduate\s+(program|engineer|software)|campus\s+hire|class\s+of\s+20\d\d)\b",
    re.I,
)
_ENTRY = re.compile(r"\b(entry[\s-]level|junior|jr\.?|associate\s+(software|engineer|developer)|engineer\s+i\b|level\s+1|l1|sde\s*-?\s*i\b|swe\s*i\b)", re.I)
_SENIOR = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|head\s+of|architect|vp|distinguished|"
    r"engineer\s+(iii|iv|v)\b|sde\s*-?\s*(iii|3)|l[5-9]\b)",
    re.I,
)
_MID = re.compile(r"\b(engineer\s+ii\b|sde\s*-?\s*(ii|2)\b|mid[\s-]level|l4\b)", re.I)


def detect_level(title: str, description: str = "") -> str:
    """Return internship | new_grad | entry | mid | senior | unknown. Title wins over body."""
    t = title or ""
    if _INTERN.search(t):
        return "internship"
    if _SENIOR.search(t):
        return "senior"
    if _NEW_GRAD.search(t):
        return "new_grad"
    if _MID.search(t):
        return "mid"
    if _ENTRY.search(t):
        return "entry"
    body = (description or "")[:4000]
    if _NEW_GRAD.search(body):
        return "new_grad"
    if _ENTRY.search(body):
        return "entry"
    years = required_years(description)
    if years is not None:
        if years >= 5:
            return "senior"
        if years >= 3:
            return "mid"
        if years <= 1:
            return "entry"
    return "unknown"


# ---------- experience ----------

_YEARS = re.compile(
    r"(?P<min>\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(?P<max>\d{1,2})\s*)?\+?\s*years?"
    r"(?:\s+of)?(?:\s+\w+){0,4}?\s+(?:experience|exp\b|industry|professional|working)",
    re.I,
)


def required_years(description: str) -> float | None:
    """Smallest 'N years of experience' requirement found, ignoring absurd values."""
    if not description:
        return None
    vals = []
    for m in _YEARS.finditer(description):
        v = int(m.group("min"))
        if 0 <= v <= 20:
            # skip "preferred"/"bonus" style mentions within the same sentence
            sentence = description[max(0, m.start() - 80): m.end() + 40].lower()
            if any(w in sentence for w in ("preferred", "nice to have", "bonus", "a plus")):
                continue
            vals.append(v)
    return float(min(vals)) if vals else None


# ---------- work mode & location ----------

def detect_work_mode(location: str, description: str = "", hint: str = "") -> str:
    blob = f"{hint} {location}".lower()
    if "hybrid" in blob:
        return "hybrid"
    if "remote" in blob:
        return "remote"
    body = (description or "").lower()[:3000]
    if re.search(r"\bhybrid\b", body):
        return "hybrid"
    if re.search(r"\b(fully|100%)\s+remote\b|\bremote[- ]first\b", body):
        return "remote"
    if location:
        return "onsite"
    return "unknown"


_US_STATES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR "
    "PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()
_COUNTRY_KEYWORDS: dict[str, list[str]] = {
    "US": ["united states", "usa", "u.s.", "us-remote", "remote - us", "remote, us", "new york", "san francisco",
           "seattle", "austin", "boston", "chicago", "los angeles", "bay area", "palo alto", "mountain view",
           "sunnyvale", "menlo park", "denver", "atlanta", "washington, dc", "nyc", "sf"],
    "CA": ["canada", "toronto", "vancouver", "montreal", "waterloo", "ottawa"],
    "UK": ["united kingdom", "uk", "london", "england", "edinburgh", "manchester", "cambridge, uk"],
    "IN": ["india", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "delhi", "gurgaon", "gurugram",
           "noida", "chennai"],
    "DE": ["germany", "berlin", "munich"],
    "IE": ["ireland", "dublin"],
    "NL": ["netherlands", "amsterdam"],
    "FR": ["france", "paris"],
    "SG": ["singapore"],
    "AU": ["australia", "sydney", "melbourne"],
    "JP": ["japan", "tokyo"],
    "PL": ["poland", "warsaw"],
    "IL": ["israel", "tel aviv"],
}


def detect_countries(location: str) -> set[str]:
    loc = (location or "").lower()
    found: set[str] = set()
    for code, words in _COUNTRY_KEYWORDS.items():
        for w in words:
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", loc):
                found.add(code)
                break
    if re.search(r",\s*(" + "|".join(_US_STATES) + r")\b", location or ""):
        found.add("US")
    return found


# ---------- requirements ----------

@dataclass
class Requirements:
    no_sponsorship: bool = False
    citizenship_required: bool = False
    clearance_required: bool = False
    phd_required: bool = False
    masters_required: bool = False
    degree_required: bool = False
    enrolled_student_required: bool = False
    grad_years: list[int] = field(default_factory=list)


_NO_SPONSOR = re.compile(
    r"(not|unable to|cannot|can't|won't|will not|do not|does not)\s+(be\s+able\s+to\s+)?(offer|provide|support|sponsor)"
    r"[^.]{0,60}(sponsor|visa)|without\s+(the\s+)?(need\s+for\s+)?(current\s+or\s+future\s+)?(visa\s+)?sponsorship|"
    r"no\s+(visa\s+)?sponsorship",
    re.I,
)
_CITIZEN = re.compile(r"\b(u\.?s\.?\s+citizen(ship)?|citizenship\s+is\s+required|must\s+be\s+a\s+citizen)\b", re.I)
_CLEARANCE = re.compile(r"\b(security\s+clearance|ts/sci|secret\s+clearance|active\s+clearance)\b", re.I)
_PHD_REQ = re.compile(r"\bph\.?d\.?\b[^.]{0,40}\b(required|must)\b|\b(required|must\s+have)[^.]{0,40}\bph\.?d", re.I)
_MS_REQ = re.compile(r"\b(master'?s|m\.?s\.?)\b[^.]{0,40}\b(required|must)\b|\b(required|must\s+have)[^.]{0,30}\bmaster'?s", re.I)
_DEGREE = re.compile(r"\b(bachelor'?s|b\.?s\.?|degree)\b[^.]{0,60}\b(computer science|engineering|related|technical)", re.I)
_ENROLLED = re.compile(
    r"(currently\s+(enrolled|pursuing)|returning\s+to\s+(school|university|your\s+studies)|"
    r"at\s+least\s+one\s+(semester|quarter|term)\s+(remaining|left))",
    re.I,
)
_GRAD_KEYWORD = re.compile(r"graduat\w*|class\s+of|degree\s+(?:by|in)|expected\s+completion", re.I)
_YEAR = re.compile(r"\b(20[2-3]\d)\b")
_SENTENCE_END = re.compile(r"[.;\n]\s")


def _grad_years(d: str) -> list[int]:
    """Years in the same sentence after a graduation keyword ('graduating between Dec 2025 and June 2026')."""
    years: set[int] = set()
    for m in _GRAD_KEYWORD.finditer(d):
        tail = d[m.end(): m.end() + 100]
        end = _SENTENCE_END.search(tail)
        years.update(int(y) for y in _YEAR.findall(tail[: end.start()] if end else tail))
    return sorted(years)


@lru_cache(maxsize=4096)
def parse_requirements(description: str) -> Requirements:
    """Cached per description; treat the result as read-only."""
    d = description or ""
    req = Requirements(
        no_sponsorship=bool(_NO_SPONSOR.search(d)),
        citizenship_required=bool(_CITIZEN.search(d)),
        clearance_required=bool(_CLEARANCE.search(d)),
        phd_required=bool(_PHD_REQ.search(d)),
        masters_required=bool(_MS_REQ.search(d)),
        degree_required=bool(_DEGREE.search(d)),
        enrolled_student_required=bool(_ENROLLED.search(d)),
    )
    req.grad_years = _grad_years(d)
    return req


# ---------- salary ----------

_SALARY = re.compile(
    r"(?P<cur>[$€£₹])\s?(?P<lo>\d{2,3}(?:[,.]\d{3})*(?:\.\d+)?)\s*(?P<lok>[kK])?\s*(?:-|–|to)\s*[$€£₹]?\s?"
    r"(?P<hi>\d{2,3}(?:[,.]\d{3})*(?:\.\d+)?)\s*(?P<hik>[kK])?"
)
_CUR = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}


def parse_salary(description: str) -> tuple[int | None, int | None, str]:
    m = _SALARY.search(description or "")
    if not m:
        return None, None, ""

    def num(s: str, k: str | None) -> int:
        v = float(s.replace(",", ""))
        return int(v * 1000) if k else int(v)

    lo, hi = num(m.group("lo"), m.group("lok")), num(m.group("hi"), m.group("hik") or m.group("lok"))
    # Hourly intern rates ("$45 - $55/hr") are annualized at 2080h for comparison.
    tail = (description or "")[m.end(): m.end() + 12].lower()
    if hi < 500 and ("hour" in tail or "/hr" in tail or "hr" in tail):
        lo, hi = lo * 2080, hi * 2080
    if hi < 1000:  # not a salary
        return None, None, ""
    return lo, hi, _CUR[m.group("cur")]
