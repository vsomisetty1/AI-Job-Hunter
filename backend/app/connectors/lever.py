"""Lever job boards (api.lever.co, public postings API, no auth).

API facts (verified against live boards):
* `GET /v0/postings/{board}?mode=json&skip=N&limit=M` returns a JSON list and
  supports real pagination; we page until a short page.
* Boards hosted in Lever's EU region live at api.eu.lever.co; a board that is
  404 in the US region is retried in the EU region.
* Structured fields: `workplaceType`, `categories.commitment` (employment
  type, free text), `categories.location` / `allLocations`, `salaryRange`
  (optional), `lists` (titled sections such as "Who You Are"), `createdAt`
  (epoch ms). Salary is often only in `additionalPlain` text.
* The API does not return the company name; it defaults to the board slug.
"""

from typing import Any

from app.connectors.base import BoardFetch, BoardInfo, Connector, slug_to_name
from app.connectors.http import BoardNotFoundError, ConnectorError
from app.connectors.normalize import (
    clean_salary,
    clean_text,
    format_money,
    html_to_text,
    infer_remote_type,
    join_locations,
    normalize_employment_type,
    parse_datetime,
    parse_salary_text,
    requirements_from_sections,
)
from app.schemas.job import NormalizedJob

REGIONS = ("https://api.lever.co", "https://api.eu.lever.co")
PAGE_SIZE = 100
MAX_PAGES = 100  # 10,000 postings: far beyond any real board


class LeverConnector(Connector):
    source = "lever"
    display_name = "Lever"
    health_board = "lever"

    def careers_url(self, board: str) -> str:
        return f"https://jobs.lever.co/{board}"

    async def board_info(self, board: str) -> BoardInfo:
        for base in REGIONS:
            try:
                await self._page(base, board, 0, limit=1)
                return BoardInfo(board, slug_to_name(board), self.careers_url(board))
            except BoardNotFoundError:
                continue
        raise BoardNotFoundError("board not found in any Lever region", status=404)

    async def _page(
        self, base: str, board: str, skip: int, limit: int | None = None
    ) -> list[dict[str, Any]]:
        data = await self.http.get_json(
            f"{base}/v0/postings/{board}",
            params={"mode": "json", "skip": skip, "limit": limit or PAGE_SIZE},
        )
        if not isinstance(data, list):
            raise ConnectorError("unexpected response shape (expected a list)")
        return [j for j in data if isinstance(j, dict)]

    async def discover_jobs(self, board: str) -> BoardFetch:
        base = None
        first: list[dict[str, Any]] = []
        for candidate in REGIONS:
            try:
                first = await self._page(candidate, board, 0)
                base = candidate
                break
            except BoardNotFoundError:
                continue
        if base is None:
            raise BoardNotFoundError("board not found in any Lever region", status=404)

        jobs, page, pages = list(first), first, 1
        seen = {j.get("id") for j in jobs}
        while len(page) == PAGE_SIZE and pages < MAX_PAGES:
            page = await self._page(base, board, len(jobs))
            pages += 1
            new = [j for j in page if j.get("id") not in seen]
            if not new:  # API ignored `skip`: stop instead of looping forever
                break
            seen |= {j.get("id") for j in new}
            jobs += new
        notes = [f"region {base}"] if base != REGIONS[0] else []
        complete = pages < MAX_PAGES
        if not complete:
            notes.append("stopped at the page limit")
        info = BoardInfo(board, slug_to_name(board), self.careers_url(board))
        return BoardFetch(info, jobs, pages=pages, notes=notes, complete=complete)

    def normalize_job(self, raw: dict[str, Any], *, board: BoardInfo) -> NormalizedJob:
        cats = raw.get("categories") or {}
        title = clean_text(raw.get("text")) or ""
        location = join_locations(cats.get("location"), *(cats.get("allLocations") or []))

        description = "\n\n".join(
            t for t in (
                html_to_text(raw.get("description") or raw.get("descriptionBody")),
                *(
                    f"{s.get('text', '')}\n\n{html_to_text(s.get('content'))}"
                    for s in raw.get("lists") or []
                ),
                html_to_text(raw.get("additional")),
            ) if t.strip()
        )  # fmt: skip
        sections = [(s.get("text") or "", s.get("content") or "") for s in raw.get("lists") or []]

        lo = hi = None
        currency = None
        comp_text = None
        sr = raw.get("salaryRange") or {}
        if sr and "year" in str(sr.get("interval", "year")).lower():
            lo, hi = clean_salary(sr.get("min"), sr.get("max"))
            currency = clean_text(sr.get("currency"))
            comp_text = f"{format_money(lo, currency)} - {format_money(hi, currency)} per year"
        elif sr:
            comp_text = (
                f"{sr.get('min')} - {sr.get('max')} {sr.get('currency', '')} ({sr.get('interval')})"
            )
        if lo is None and hi is None:
            parsed = parse_salary_text(raw.get("additionalPlain") or description)
            lo, hi, currency = parsed.min, parsed.max, parsed.currency
            comp_text = comp_text or parsed.text

        posting_id = str(raw["id"])
        return NormalizedJob(
            source=self.source,
            source_job_id=posting_id,
            company_name=board.name,
            title=title,
            location=location,
            remote_type=infer_remote_type(raw.get("workplaceType"), location),
            employment_type=normalize_employment_type(cats.get("commitment"), title),
            salary_min=lo,
            salary_max=hi,
            salary_currency=currency if (lo or hi) else None,
            compensation_text=comp_text,
            description=description,
            requirements=requirements_from_sections(sections),
            url=clean_text(raw.get("hostedUrl")) or f"{self.careers_url(board.slug)}/{posting_id}",
            apply_url=clean_text(raw.get("applyUrl")),
            posted_at=parse_datetime(raw.get("createdAt")),
            raw={k: v for k, v in raw.items()
                 if k not in {"description", "descriptionBody", "additional", "lists",
                              "descriptionPlain", "descriptionBodyPlain", "additionalPlain"}},
        )  # fmt: skip
