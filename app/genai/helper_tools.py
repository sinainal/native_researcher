"""Prompt and tool factories for helper chat."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from app.schemas.helper import HelperArticle


def build_helper_corpus_prompt(
    articles: Sequence[HelperArticle],
    selected_ids: Sequence[int],
) -> str:
    catalog_lines = []
    for article in articles:
        mesh_preview = ", ".join(article.mesh_terms[:4]) if article.mesh_terms else "-"
        catalog_lines.append(
            f"[{article.id}] {article.title} | yil={article.year or '-'} | "
            f"type={article.article_type or '-'} | "
            f"cite={article.citation_count if article.citation_count is not None else '-'} | "
            f"mesh={mesh_preview}"
        )

    selected_text = (
        f"Secili makale ID'leri: {', '.join(str(item) for item in selected_ids)}"
        if selected_ids
        else "Secili makale yok."
    )
    return (
        "Mevcut cekili makale katalogu asagidadir. Kullanici sorularini sadece bu korpus uzerinden cevapla.\n"
        "Bir makale ya da makale grubu hakkinda detay sorulursa uygun aractan veri cek.\n"
        "Eger veri yalnizca abstract ve metadata seviyesindeyse bunu acikca belirt.\n"
        "Cevaplarini Turkce ver ve kullandigin makale ID'lerini en sonda `Kaynak ID` olarak yaz.\n\n"
        f"{selected_text}\n\n"
        "Makale katalogu:\n"
        + ("\n".join(catalog_lines) if catalog_lines else "Katalog bos.")
    )


def build_helper_tools(
    articles: Sequence[HelperArticle],
    used_article_ids: set[int],
) -> list[Callable[..., dict[str, Any]]]:
    article_index = {article.id: article for article in articles}

    def list_articles(query: str = "", article_type: str = "", limit: int = 10) -> dict[str, Any]:
        """List article summaries from the current in-memory corpus.

        Args:
            query: Free-text filter applied to title, article type, and MeSH terms.
            article_type: Exact article type filter such as Review or Clinical Trial.
            limit: Maximum number of results to return, between 1 and 25.

        Returns:
            A dictionary with lightweight article summaries for matching records.
        """

        query_lower = query.strip().lower()
        type_lower = article_type.strip().lower()
        ranked: list[HelperArticle] = []
        for article in articles:
            haystacks = [
                article.title,
                article.article_type or "",
                " ".join(article.mesh_terms),
            ]
            matches_query = not query_lower or any(query_lower in value.lower() for value in haystacks)
            matches_type = not type_lower or (article.article_type or "").lower() == type_lower
            if matches_query and matches_type:
                ranked.append(article)

        ranked = ranked[: max(1, min(limit, 25))]
        used_article_ids.update(article.id for article in ranked)
        return {
            "articles": [
                {
                    "id": article.id,
                    "title": article.title,
                    "year": article.year,
                    "article_type": article.article_type,
                    "citation_count": article.citation_count,
                    "mesh_terms": article.mesh_terms[:8],
                }
                for article in ranked
            ]
        }

    def get_articles(ids: list[int]) -> dict[str, Any]:
        """Return detailed article metadata for the requested IDs.

        Args:
            ids: Article IDs from the current corpus.

        Returns:
            A dictionary with detailed article metadata and abstracts.
        """

        resolved: list[dict[str, Any]] = []
        for article_id in ids:
            article = article_index.get(article_id)
            if article is None:
                continue
            used_article_ids.add(article_id)
            resolved.append(
                {
                    "id": article.id,
                    "title": article.title,
                    "year": article.year,
                    "journal": article.journal,
                    "article_type": article.article_type,
                    "citation_count": article.citation_count,
                    "pmid": article.pmid,
                    "doi": article.doi,
                    "mesh_terms": article.mesh_terms,
                    "abstract": article.abstract,
                }
            )
        return {"articles": resolved}

    return [list_articles, get_articles]
