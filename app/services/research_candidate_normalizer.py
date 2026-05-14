"""Normalize and deduplicate research execution candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.schemas.article import Article
from app.schemas.research_execution import ResearchCandidateMatch, ResearchCandidateTrace


_SOURCE_LABELS = {
    "pubmed": "pubmed",
    "pmc": "pmc",
    "europe pmc": "europe_pmc",
    "europe_pmc": "europe_pmc",
    "openalex": "openalex",
    "core": "core",
    "arxiv": "arxiv",
}


@dataclass
class NormalizedResearchCandidate:
    candidate_id: str
    article: Article
    matches: list[ResearchCandidateMatch] = field(default_factory=list)
    source_names: set[str] = field(default_factory=set)


def normalize_database_source(value: str | None) -> str:
    normalized = (value or "").strip().lower().replace("-", " ")
    return _SOURCE_LABELS.get(normalized, normalized.replace(" ", "_") or "pubmed")


def normalize_source_label(value: str | None) -> str:
    source = normalize_database_source(value)
    return {
        "pubmed": "PubMed",
        "pmc": "PMC",
        "europe_pmc": "Europe PMC",
        "openalex": "OpenAlex",
        "core": "CORE",
        "arxiv": "arXiv",
    }.get(source, value or source)


def candidate_dedupe_key(article: Article) -> str:
    doi = _clean_identifier(article.doi)
    if doi:
        return f"doi:{doi.lower()}"
    pmc_id = _clean_identifier(article.pmc_id)
    if pmc_id:
        return f"pmc:{pmc_id.upper()}"
    pmid = _clean_identifier(article.pmid)
    if pmid:
        return f"pmid:{pmid}"
    source_id = _clean_identifier(article.source_record_id)
    source = _clean_identifier(article.source_name)
    if source and source_id:
        return f"source:{source.lower()}:{source_id.lower()}"
    title = _normalize_title(article.title)
    year = (article.year or "").strip()
    return f"title:{title}:{year}"


def normalize_research_candidates(
    query_results: list[tuple[dict[str, Any], list[Article]]],
) -> list[NormalizedResearchCandidate]:
    by_key: dict[str, NormalizedResearchCandidate] = {}
    ordered_keys: list[str] = []
    for query, articles in query_results:
        source = normalize_database_source(str(query.get("database") or query.get("source") or ""))
        database = str(query.get("database") or normalize_source_label(source))
        for article in articles:
            key = candidate_dedupe_key(article)
            current = by_key.get(key)
            if current is None:
                current = NormalizedResearchCandidate(
                    candidate_id=f"cand_{len(ordered_keys) + 1}",
                    article=article.model_copy(deep=True),
                )
                by_key[key] = current
                ordered_keys.append(key)
            current.source_names.add(source or article.source_name or database)
            match = ResearchCandidateMatch(
                database=database,
                source=source,
                branch_id=str(query.get("branch_id") or ""),
                branch_label=str(query.get("branch_label") or ""),
                category_id=str(query.get("category_id") or ""),
                category_label=str(query.get("category_label") or ""),
                query=str(query.get("query") or ""),
                raw_query=str(query.get("raw_query") or query.get("branch_query") or ""),
                extracted_query=str(query.get("extracted_query") or query.get("query") or ""),
            )
            if match not in current.matches:
                current.matches.append(match)
            _merge_article_metadata(current.article, article)

    normalized = [by_key[key] for key in ordered_keys]
    for index, candidate in enumerate(normalized, start=1):
        candidate.article.id = index
    return normalized


def candidate_trace(candidate: NormalizedResearchCandidate) -> ResearchCandidateTrace:
    return ResearchCandidateTrace(
        candidate_id=candidate.candidate_id,
        article_id=candidate.article.id,
        title=candidate.article.title,
        year=candidate.article.year,
        doi=candidate.article.doi,
        pmid=candidate.article.pmid or None,
        pmc_id=candidate.article.pmc_id,
        source_names=sorted(candidate.source_names),
        matches=candidate.matches,
    )


def _clean_identifier(value: str | None) -> str:
    return (value or "").strip()


def _normalize_title(value: str | None) -> str:
    text = (value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _merge_article_metadata(target: Article, source: Article) -> None:
    for field_name in (
        "doi",
        "pmc_id",
        "pmid",
        "oa_pdf_url",
        "landing_page_url",
        "journal",
        "publication_date",
        "article_type",
        "year",
    ):
        if not getattr(target, field_name, None) and getattr(source, field_name, None):
            setattr(target, field_name, getattr(source, field_name))
    if source.citation_count is not None and (
        target.citation_count is None or source.citation_count > target.citation_count
    ):
        target.citation_count = source.citation_count
    for field_name in ("authors", "keywords", "mesh_terms", "article_types", "related_articles", "issns"):
        merged = list(getattr(target, field_name, []) or [])
        for item in getattr(source, field_name, []) or []:
            if item not in merged:
                merged.append(item)
        setattr(target, field_name, merged)
