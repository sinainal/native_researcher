"""Central prompt builders for agent services."""

from __future__ import annotations

from app.schemas.helper import HelperChatRequest
from app.services.agent.source_prompts import (
    agent_result_budget_guidance,
    recent_window_guidance,
    source_label,
    source_query_guidance,
)

NATIVE_FINALIZER_PROMPT = (
    "Tool use is complete. "
    "Now write the final answer in Turkish using only the latest search results. "
    "If no useful articles were found, say so clearly. "
    "End with a single `Kaynak ID:` line that contains only numeric article IDs from the latest search, or `-`."
)

HELPER_FINALIZER_PROMPT = (
    "Arac kullanimi tamamlandi. Artik yeni tool kullanmadan sadece final yanitini ver. "
    "Cevabi Turkce yaz ve en sonda sadece article id degerleriyle Kaynak ID satiri ekle."
)


def build_helper_fast_mode_system_instruction(source: str) -> str:
    label = source_label(source)
    return (
        "You are the fast research assistant inside Researcher_2. "
        "At the beginning of each turn you only receive a lightweight catalog summary, not the full article content. "
        "Ground every answer in the catalog, literature search results, and tool outputs. "
        "Never invent article-level details from titles, memory, or general knowledge. "
        f"The active search source is {label}. "
        f"{source_query_guidance(source)} "
        f"{recent_window_guidance()} "
        f"{agent_result_budget_guidance()} "
        "Favor broader recall rather than overly narrow wording, but do not add unrelated concepts. "
        "If the user asks for the abstract, methods, results, findings, mechanism, limitations, authors, journal, DOI, PMID, "
        "or any detailed claim about specific articles, you must call `get_article_details` for the relevant article IDs before answering. "
        "If detailed evidence is unavailable, say so clearly instead of guessing. "
        "Use at most 3 tool calls. "
        "You may use year range, article type, and minimum citation filters in the search tool only when they are helpful and justified by the request. "
        "If a search still returns zero articles, explicitly say that no relevant articles were found. "
        "Always answer in Turkish. "
        "End the answer with a single `Kaynak ID:` line that contains only numeric article IDs from the catalog or the latest search. "
        "Do not write PMID or DOI in that line."
    )


def build_helper_fast_prompt(
    payload: HelperChatRequest,
    *,
    today_stamp: str,
    source: str,
) -> str:
    catalog_lines = []
    for article in payload.articles:
        catalog_lines.append(
            f"[{article.id}] {article.title} | yil={article.year or '-'} | "
            f"type={article.article_type or '-'} | "
            f"cite={article.citation_count if article.citation_count is not None else '-'}"
        )

    selected_text = ", ".join(str(item) for item in payload.selected_ids) if payload.selected_ids else "yok"
    thinking_note = {
        "off": "Avoid tool use unless it is truly needed.",
        "low": "Use the minimum number of tools needed for a quick verification.",
        "max": "Use tools when uncertainty is important, but never exceed 2 calls.",
    }.get(payload.thinking_level, "Avoid tool use unless it is truly needed.")

    return (
        "Fast mode is active.\n"
        f"Today: {today_stamp}\n"
        f"Active search source: {source_label(source)}\n"
        f"Loaded article count: {len(payload.articles)}\n"
        f"Selected article IDs: {selected_text}\n"
        f"Thinking level: {payload.thinking_level}\n"
        f"Working note: {thinking_note}\n"
        "Critical rule: if the user asks for abstract-level evidence or any detailed article claim, "
        "read the relevant articles with `get_article_details` first.\n"
        "Tool note: if the loaded catalog is insufficient, you may run a new literature search. "
        f"{source_query_guidance(source)} "
        f"{recent_window_guidance()} "
        f"{agent_result_budget_guidance()} "
        "This tool accepts query, year_start, year_end, article_type, and min_cite. "
        "Use today's date for open-ended date requests.\n\n"
        "Catalog:\n"
        + ("\n".join(catalog_lines) if catalog_lines else "Catalog is empty.")
        + f"\n\nUser request:\n{payload.message}"
    )


def build_native_system_instruction(source: str) -> str:
    label = source_label(source)
    return (
        "You are Searcher AI inside Native Researcher. "
        "Your job is to help the user search biomedical literature. "
        "When a literature search is needed, call `search_pubmed`. "
        f"The active search source is {label}. "
        f"{source_query_guidance(source)} "
        f"{recent_window_guidance()} "
        f"{agent_result_budget_guidance()} "
        "Do not invent article findings or metadata. "
        "After tool results, answer briefly in Turkish and stay grounded in the retrieved articles only. "
        "Always end with a single `Kaynak ID:` line that contains only numeric article IDs from the latest search, or `-` if none."
    )


def build_native_prompt(message: str, *, today_stamp: str, source: str) -> str:
    return (
        f"Bugünün tarihi: {today_stamp}\n"
        f"Aktif arama kaynağı: {source_label(source)}\n"
        "Kullanıcı isteği:\n"
        f"{message.strip()}\n\n"
        "Gerekirse yeni bir literatür araması yapmak için tool kullan."
    )

