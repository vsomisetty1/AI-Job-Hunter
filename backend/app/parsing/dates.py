"""Date and date-range parsing for resumes.

Handles: "Jan 2020", "January 2020", "Jan. 2020", "Sept 2019", "01/2020",
"1/2020", "2020-01", "2020", "Summer 2019", "Present"/"Current"/"Now", with
range separators "-", en/em dash, "to", "until", "through".
Output dates are "YYYY-MM" (or "YYYY" when no month is known).
"""

import re
from dataclasses import dataclass
from datetime import date

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}  # fmt: skip
_SEASONS = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 12}
_PRESENT = r"(?:present|current|now|today|ongoing|date)"

_MONTH_NAME = r"(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_SEASON = r"(?:" + "|".join(_SEASONS) + r")"
_YEAR = r"(?:19[5-9]\d|20\d\d)"

# One date point (named groups resolved in _point()).
_POINT = (
    rf"(?:(?P<{{p}}mname>{_MONTH_NAME})\s*,?\s*(?P<{{p}}y1>{_YEAR})"
    rf"|(?P<{{p}}season>{_SEASON})\s+(?P<{{p}}y2>{_YEAR})"
    rf"|(?P<{{p}}mnum>0?[1-9]|1[0-2])\s*[/.-]\s*(?P<{{p}}y3>{_YEAR})"
    rf"|(?P<{{p}}y4>{_YEAR})\s*[/.-]\s*(?P<{{p}}mnum2>0[1-9]|1[0-2])(?!\d)"
    rf"|(?P<{{p}}y5>{_YEAR}))"
)
_SEP = r"\s*(?:-|–|—|‒|~|to|until|through|thru)\s*"

RANGE_RE = re.compile(
    _POINT.format(p="s_") + _SEP + rf"(?:(?P<present>{_PRESENT})|" + _POINT.format(p="e_") + ")",
    re.IGNORECASE,
)
SINGLE_RE = re.compile(_POINT.format(p="s_"), re.IGNORECASE)


@dataclass(frozen=True)
class DateRange:
    start: str | None
    end: str | None
    is_current: bool
    span: tuple[int, int]  # character span in the source text


def _point(m: re.Match[str], p: str) -> str | None:
    g = m.groupdict()
    if g.get(f"{p}mname"):
        month = _MONTHS[g[f"{p}mname"].lower().rstrip(".")]
        return f"{g[f'{p}y1']}-{month:02d}"
    if g.get(f"{p}season"):
        return f"{g[f'{p}y2']}-{_SEASONS[g[f'{p}season'].lower()]:02d}"
    if g.get(f"{p}mnum"):
        return f"{g[f'{p}y3']}-{int(g[f'{p}mnum']):02d}"
    if g.get(f"{p}mnum2"):
        return f"{g[f'{p}y4']}-{int(g[f'{p}mnum2']):02d}"
    if g.get(f"{p}y5"):
        return g[f"{p}y5"]
    return None


def find_date_range(text: str) -> DateRange | None:
    """First date range in `text`, else a single date (treated as an end date)."""
    m = RANGE_RE.search(text)
    if m:
        start = _point(m, "s_")
        if m.group("present"):
            return DateRange(start, None, True, m.span())
        end = _point(m, "e_")
        if start and end and sort_key(end) < sort_key(start):
            start, end = end, start
        return DateRange(start, end, False, m.span())
    m = SINGLE_RE.search(text)
    if m:
        return DateRange(None, _point(m, "s_"), False, m.span())
    return None


def find_year(text: str) -> str | None:
    m = SINGLE_RE.search(text)
    return _point(m, "s_") if m else None


def sort_key(d: str) -> tuple[int, int]:
    year, _, month = d.partition("-")
    return int(year), int(month) if month else 0


def to_month_index(d: str | None, *, is_end: bool, today: date | None = None) -> int | None:
    """Months since year 0. A bare year counts as January (start) or December (end)."""
    if d is None:
        return None
    year, month = sort_key(d)
    if month == 0:
        month = 12 if is_end else 1
    idx = year * 12 + (month - 1)
    if today is not None:
        idx = min(idx, today.year * 12 + today.month - 1)
    return idx


def total_months(
    ranges: list[tuple[str | None, str | None, bool]], today: date | None = None
) -> int:
    """Months covered by the union of (start, end, is_current) ranges.

    Overlapping jobs are not double counted. Ranges without a start are ignored.
    """
    today = today or date.today()
    now = today.year * 12 + today.month - 1
    intervals = []
    for start, end, current in ranges:
        s = to_month_index(start, is_end=False)
        e = now if current or end is None else to_month_index(end, is_end=True, today=today)
        if s is None or e is None or e < s:
            continue
        intervals.append((s, e))
    intervals.sort()
    merged: list[list[int]] = []
    for s, e in intervals:
        if merged and s <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return sum(e - s + 1 for s, e in merged)
