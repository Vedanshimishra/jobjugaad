"""Connectors for public ATS job-board APIs (no auth, no scraping)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.jd_parser import html_to_text
from app.services.job_sources.base import RawJob, http_client, parse_iso


class GreenhouseSource:
    name = "greenhouse"

    def fetch(self, board: str) -> list[RawJob]:
        with http_client() as c:
            r = c.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", params={"content": "true"})
            r.raise_for_status()
            data = r.json()
        out = []
        for j in data.get("jobs", []):
            out.append(
                RawJob(
                    source=self.name,
                    external_id=f"{board}:{j['id']}",
                    company=j.get("company_name") or board.replace("-", " ").title(),
                    title=j.get("title", ""),
                    location=(j.get("location") or {}).get("name", ""),
                    url=j.get("absolute_url", ""),
                    description=html_to_text(j.get("content", "")),
                    posted_at=parse_iso(j.get("first_published") or j.get("updated_at")),
                    extra={"departments": [d.get("name") for d in j.get("departments", [])]},
                )
            )
        return out


class LeverSource:
    name = "lever"

    def fetch(self, board: str) -> list[RawJob]:
        with http_client() as c:
            r = c.get(f"https://api.lever.co/v0/postings/{board}", params={"mode": "json"})
            r.raise_for_status()
            data = r.json()
        out = []
        for j in data:
            cats = j.get("categories") or {}
            lists = "\n\n".join(
                f"{li.get('text', '')}\n{html_to_text(li.get('content', ''))}" for li in j.get("lists", [])
            )
            desc = "\n\n".join(filter(None, [j.get("descriptionPlain", ""), lists, j.get("additionalPlain", "")]))
            sal = j.get("salaryRange") or {}
            created = j.get("createdAt")
            out.append(
                RawJob(
                    source=self.name,
                    external_id=f"{board}:{j['id']}",
                    company=board.replace("-", " ").title(),
                    title=j.get("text", ""),
                    location=cats.get("location", "") or ", ".join(cats.get("allLocations", []) or []),
                    url=j.get("hostedUrl", ""),
                    description=desc,
                    employment_type=cats.get("commitment", ""),
                    work_mode_hint=j.get("workplaceType", ""),
                    posted_at=datetime.fromtimestamp(created / 1000, UTC) if created else None,
                    salary_min=sal.get("min"),
                    salary_max=sal.get("max"),
                    salary_currency=sal.get("currency", "") or "",
                )
            )
        return out


class AshbySource:
    name = "ashby"

    def fetch(self, board: str) -> list[RawJob]:
        with http_client() as c:
            r = c.get(
                f"https://api.ashbyhq.com/posting-api/job-board/{board}", params={"includeCompensation": "true"}
            )
            r.raise_for_status()
            data = r.json()
        out = []
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            hint = j.get("workplaceType") or ("remote" if j.get("isRemote") else "")
            out.append(
                RawJob(
                    source=self.name,
                    external_id=f"{board}:{j['id']}",
                    company=board.replace("-", " ").title(),
                    title=j.get("title", ""),
                    location=j.get("location", ""),
                    url=j.get("jobUrl", "") or j.get("applyUrl", ""),
                    description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
                    employment_type=j.get("employmentType", ""),
                    work_mode_hint=str(hint),
                    posted_at=parse_iso(j.get("publishedAt")),
                    extra={"compensation": (j.get("compensation") or {}).get("compensationTierSummary", "")},
                )
            )
        return out


SOURCES = {s.name: s for s in (GreenhouseSource(), LeverSource(), AshbySource())}
