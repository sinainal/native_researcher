"""Source-aware prompt helpers for literature search agents."""

from __future__ import annotations

from app.services.agent.search_policy import AGENT_SEARCH_MAX_RESULTS, DEFAULT_RECENT_YEAR_SPAN


def source_label(source: str) -> str:
    if source == "pubmed":
        return "PubMed"
    if source == "europe_pmc":
        return "Europe PMC"
    return "OpenAlex"


def source_query_guidance(source: str) -> str:
    if source == "pubmed":
        return (
            "Write one executable PubMed Boolean query with broad biomedical recall. "
            "MeSH and Title/Abstract syntax are allowed when useful."
        )
    if source == "europe_pmc":
        return (
            "Write one concise Europe PMC friendly literature query string. "
            "Do not use PubMed field syntax."
        )
    return (
        "Write one concise OpenAlex friendly literature query string. "
        "Do not use PubMed field syntax."
    )


def source_tool_description(source: str) -> tuple[str, str]:
    label = source_label(source)
    if source == "pubmed":
        return (
            (
                f"Runs a new {label} search. Use this when the loaded catalog is insufficient or empty. "
                "Pass one executable broad PubMed query with Boolean logic. "
                "Results can later be read in detail with `get_article_details` using `source=last_search`."
            ),
            "Executable broad PubMed query string with Boolean logic, not a plain topic sentence.",
        )
    if source == "europe_pmc":
        return (
            (
                f"Runs a new {label} search. Use this when the loaded catalog is insufficient or empty. "
                "Pass one concise Europe PMC friendly literature query string with the main concepts only. "
                "Results can later be read in detail with `get_article_details` using `source=last_search`."
            ),
            "Concise Europe PMC friendly literature query string, not PubMed field syntax.",
        )
    return (
        (
            f"Runs a new {label} search. Use this when the loaded catalog is insufficient or empty. "
            "Pass one concise OpenAlex friendly literature query string with the core concepts only. "
            "Results can later be read in detail with `get_article_details` using `source=last_search`."
        ),
        "Concise OpenAlex friendly literature query string, not PubMed field syntax.",
    )


def recent_window_guidance() -> str:
    return (
        f"If no year range is provided, searches default to the most recent {DEFAULT_RECENT_YEAR_SPAN} years. "
        "Use year_start and year_end only when the user explicitly asks or when broader historical coverage is needed."
    )


def agent_result_budget_guidance() -> str:
    return (
        f"Keep search result budgets compact. Agent-driven search calls should request at most {AGENT_SEARCH_MAX_RESULTS} results."
    )
