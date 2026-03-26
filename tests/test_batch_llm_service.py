"""Batch analyzer service tests."""

from __future__ import annotations

import asyncio
from typing import Any

from app.schemas.llm import LLMArticle, LLMProcessRequest
from app.services.batch_llm_service import BatchLLMService


class StubBatchLLMService(BatchLLMService):
    async def _run_batch_with_retries(  # type: ignore[override]
        self,
        *,
        api_key: str,
        model_name: str,
        prompt: str,
        system_instruction: str,
        batch,
        retry_count: int,
        schema_template: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], int]:
        del api_key, model_name, prompt, system_instruction, retry_count
        results: list[dict[str, Any]] = []
        for article in batch.articles:
            high_value = article.id in {2, 5, 11, 17, 23}
            results.append(
                self._normalize_result_item(
                    article.id,
                    {
                        "id": article.id,
                        "in_scope": high_value,
                        "relevance_score": 92 if high_value else 24,
                        "confidence": "high" if high_value else "low",
                        "answers_question": high_value,
                        "population_match": high_value,
                        "intervention_match": high_value,
                        "outcome_match": high_value,
                        "evidence_summary": "Strong abstract support." if high_value else "Weak signal.",
                        "short_reason": "Directly addresses the question." if high_value else "Peripheral.",
                        "matched_terms": ["depression", "ssri", "neurogenesis"] if high_value else [],
                    },
                    schema_template,
                )
            )
        return results, 1


def build_articles(count: int) -> list[LLMArticle]:
    return [
        LLMArticle(
            id=index,
            title=f"Article {index}",
            abstract=f"Abstract text for article {index}. " * 20,
            year="2024",
            journal="Test Journal",
            pmid=str(10_000 + index),
        )
        for index in range(1, count + 1)
    ]


def test_prepare_article_does_not_trim_abstract() -> None:
    service = BatchLLMService()
    long_abstract = "A" * 9000
    prepared = service._prepare_article(
        {
            "id": 1,
            "title": "Long abstract study",
            "abstract": long_abstract,
            "pmid": "123",
        }
    )
    assert prepared.payload["abstract"] == long_abstract
    assert "[abstract trimmed]" not in prepared.payload["abstract"]


def test_screen_for_question_batches_and_shortlists() -> None:
    async def runner() -> None:
        service = StubBatchLLMService()
        payload = LLMProcessRequest(
            api_key="test_api_key_1234567890",
            model="gemini 3.1 flash lite",
            analysis_mode="screen_for_question",
            question="In adults with major depression, does hippocampal neurogenesis recover after SSRI treatment?",
            articles=build_articles(50),
            llm_batch=25,
            top_k=5,
        )

        response = await service.process(payload)

        assert response.analysis_mode == "screen_for_question"
        assert response.batch_count == 2
        assert response.processed_count == 50
        assert response.merged_count == 50
        assert response.top_article_ids == [2, 5, 11, 17, 23]
        assert response.aggregate_summary["top_candidates_count"] == 5
        assert response.aggregate_summary["answers_question_count"] == 5
        assert response.aggregate_summary["in_scope_count"] == 5

    asyncio.run(runner())
