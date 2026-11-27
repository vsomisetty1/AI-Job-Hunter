"""Ashby job boards (api.ashbyhq.com posting API, public, no auth).

API facts (verified against live boards):
* `GET /posting-api/job-board/{board}?includeCompensation=true` returns the
  whole board in one response, `{"jobs": [...], "apiVersion": ...}`; there is
  no pagination. Postings with `isListed: false` are hidden on the board and
  are skipped.
* Structured fields: `workplaceType` (OnSite/Hybrid/Remote), `isRemote`,
  `employmentType` (FullTime/PartTime/Intern/Contract/Temporary), `location`
  + `secondaryLocations`, `publishedAt`, and `compensation.summaryComponents`
  (salary min/max/currency/interval).
* The API does not return the company name; it defaults to the board slug.
"""

from typing import Any

from app.connectors.base import BoardFetch, BoardInfo, Connector, slug_to_name
from app.connectors.http import ConnectorError
from app.connectors.normalize import (
    clean_salary,
    clean_text,
    extract_requirements,
    html_to_text,
    infer_remote_type,
    join_locations,
    normalize_employment_type,
    parse_datetime,
)
from app.schemas.job import NormalizedJob

API = "https://api.ashbyhq.com/posting-api/job-board"


class AshbyConnector(Connector):
    source = "ashby"
    display_name = "Ashby"
    health_board = "ashby"

    def careers_url(self, board: str) -> str:
        return f"https://jobs.ashbyhq.com/{board}"

    async def discover_jobs(self, board: str) -> BoardFetch:
        data = await self.http.get_json(f"{API}/{board}", params={"includeCompensation": "true"})
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ConnectorError("unexpected response shape (no 'jobs' list)")
        jobs = [j for j in data["jobs"] if isinstance(j, dict)]
        listed = [j for j in jobs if j.get("isListed", True) is not False]
        notes = (
            [f"{len(jobs) - len(listed)} unlisted postings ignored"]
            if len(listed) < len(jobs)
            else []
        )
        info = BoardInfo(board, slug_to_name(board), self.careers_url(board))
        return BoardFetch(info, listed, pages=1, notes=notes)

    def normalize_job(self, raw: dict[str, Any], *, board: BoardInfo) -> NormalizedJob:
        title = clean_text(raw.get("title")) or ""
        location = join_locations(
            raw.get("location"), *(s.get("location") for s in raw.get("secondaryLocations") or [])
        )
        comp = raw.get("compensation") or {}
        salary = next(
            (c for c in comp.get("summaryComponents") or []
             if c.get("compensationType") == "Salary" and "YEAR" in str(c.get("interval", ""))),
            None,
        )  # fmt: skip
        lo = hi = None
        currency = None
        if salary:
            lo, hi = clean_salary(salary.get("minValue"), salary.get("maxValue"))
            currency = clean_text(salary.get("currencyCode"))
        html = raw.get("descriptionHtml") or ""
        posting_id = str(raw["id"])
        return NormalizedJob(
            source=self.source,
            source_job_id=posting_id,
            company_name=board.name,
            title=title,
            location=location,
            remote_type=infer_remote_type(
                raw.get("workplaceType"), location, is_remote=raw.get("isRemote")
            ),
            employment_type=normalize_employment_type(raw.get("employmentType"), title),
            salary_min=lo,
            salary_max=hi,
            salary_currency=currency if (lo or hi) else None,
            compensation_text=clean_text(comp.get("compensationTierSummary")),
            description=html_to_text(html) or (raw.get("descriptionPlain") or "").strip(),
            requirements=extract_requirements(html),
            url=clean_text(raw.get("jobUrl")) or f"{self.careers_url(board.slug)}/{posting_id}",
            apply_url=clean_text(raw.get("applyUrl")),
            posted_at=parse_datetime(raw.get("publishedAt")),
            raw={k: v for k, v in raw.items() if k not in {"descriptionHtml", "descriptionPlain"}},
        )
