"""Shared search policy for agent-driven discovery."""

from __future__ import annotations

from datetime import date

DEFAULT_RECENT_YEAR_SPAN = 5
AGENT_SEARCH_MAX_RESULTS = 100


def default_recent_year_window(today: date | None = None) -> tuple[int, int]:
    current = today or date.today()
    year_end = current.year
    year_start = year_end - (DEFAULT_RECENT_YEAR_SPAN - 1)
    return year_start, year_end


def apply_default_year_window(
    year_start: int | None,
    year_end: int | None,
    *,
    today: date | None = None,
) -> tuple[int | None, int | None]:
    if year_start is None and year_end is None:
        return default_recent_year_window(today=today)
    return year_start, year_end


def normalize_agent_max_results(value: int | None) -> int:
    if value is None:
        return AGENT_SEARCH_MAX_RESULTS
    return max(1, min(AGENT_SEARCH_MAX_RESULTS, int(value)))
