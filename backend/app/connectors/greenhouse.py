"""Greenhouse job boards (boards-api.greenhouse.io, public, no auth).

API facts (verified against live boards):
* `GET /v1/boards/{board}/jobs?content=true&pay_transparency=true` returns the
  whole board in one response, `{"jobs": [...], "meta": {"total": N}}`. There
  is no pagination (page parameters are ignored); `meta.total` is checked so a
  truncated response is noticed.
* `content` is HTML with its entities escaped (`&lt;p&gt;`).
* `pay_input_ranges`: salary ranges in cents, possibly several (per country).
* Remote/hybrid is only expressed in the location text.
* `GET /v1/boards/{board}` returns the company name; unknown boards -> 404.
"""

from typing import Any

from app.connectors.base import BoardFetch, BoardInfo, Connector
from app.connectors.http import ConnectorError
from app.connectors.normalize import (
    clean_salary,
    clean_text,
    extract_requirements,
    format_money,
    html_to_text,
    infer_remote_type,
    normalize_employment_type,
    parse_datetime,
    parse_salary_text,
)
from app.schemas.job import NormalizedJob

API = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseConnector(Connector):
    source = "greenhouse"
    display_name = "Greenhouse"
    health_board = "greenhouse"

    def careers_url(self, board: str) -> str:
        return f"https://job-boards.greenhouse.io/{board}"

    async def board_info(self, board: str) -> BoardInfo:
        meta = await self.http.get_json(f"{API}/{board}")
        name = clean_text(meta.get("name")) if isinstance(meta, dict) else None
        return BoardInfo(board, name or board, self.careers_url(board))

    async def discover_jobs(self, board: str) -> BoardFetch:
        info = await self.board_info(board)
        data = await self.http.get_json(
            f"{API}/{board}/jobs", params={"content": "true", "pay_transparency": "true"}
        )
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ConnectorError("unexpected response shape (no 'jobs' list)")
        jobs = [j for j in data["jobs"] if isinstance(j, dict)]
        total = (data.get("meta") or {}).get("total")
        notes = []
        complete = True
        if isinstance(total, int) and total > len(jobs):
            notes.append(f"board reports {total} jobs but returned {len(jobs)}")
            complete = False
        return BoardFetch(info, jobs, pages=1, expected_total=total, notes=notes, complete=complete)

    def normalize_job(self, raw: dict[str, Any], *, board: BoardInfo) -> NormalizedJob:
        title = clean_text(raw.get("title")) or ""
        location = clean_text((raw.get("location") or {}).get("name"))
        content = raw.get("content") or ""

        lo = hi = None
        currency = None
        texts = []
        for r in raw.get("pay_input_ranges") or []:
            r_lo = r.get("min_cents") / 100 if r.get("min_cents") is not None else None
            r_hi = r.get("max_cents") / 100 if r.get("max_cents") is not None else None
            r_lo_i, r_hi_i = clean_salary(r_lo, r_hi)
            label = clean_text(r.get("title")) or "Pay range"
            cur = clean_text(r.get("currency_type"))
            texts.append(
                f"{label} {format_money(r_lo_i, cur)} - {format_money(r_hi_i, cur)}".strip()
            )
            if lo is None and hi is None and (r_lo_i or r_hi_i):
                lo, hi, currency = r_lo_i, r_hi_i, cur
        description = html_to_text(content, escaped=True)
        if lo is None and hi is None:
            parsed = parse_salary_text(description)
            lo, hi, currency = parsed.min, parsed.max, parsed.currency
            if parsed.text:
                texts.append(parsed.text)

        departments = [d.get("name") for d in raw.get("departments") or [] if d.get("name")]
        return NormalizedJob(
            source=self.source,
            source_job_id=str(raw["id"]),
            company_name=clean_text(raw.get("company_name")) or board.name,
            title=title,
            location=location,
            remote_type=infer_remote_type(None, location),
            employment_type=normalize_employment_type(None, title),
            salary_min=lo,
            salary_max=hi,
            salary_currency=currency if (lo or hi) else None,
            compensation_text="; ".join(texts) or None,
            description=description,
            requirements=extract_requirements(content, escaped=True),
            url=clean_text(raw.get("absolute_url"))
            or f"{self.careers_url(board.slug)}/jobs/{raw['id']}",
            apply_url=None,
            posted_at=parse_datetime(raw.get("first_published") or raw.get("updated_at")),
            raw={k: v for k, v in raw.items() if k != "content"} | {"departments": departments},
        )
