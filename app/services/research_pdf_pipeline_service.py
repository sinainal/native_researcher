"""PDF/full-text stage helpers for research plan execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas.article import Article, ArticleReference
from app.schemas.pdf_extraction import PDFExtractionRequest, PDFExtractionResponse
from app.schemas.research_execution import ResearchPlanExecuteRequest, ResearchPlanExecuteResponse
from app.services.pdf_extraction_service import PDFExtractionService
from app.services.research_plan_payload_service import full_text_model_from_payload

ProgressCallback = Callable[[dict[str, object]], Awaitable[None]]


class ResearchPdfPipelineService:
    """Owns article selection and extraction request assembly for the PDF stage."""

    def __init__(self, *, extraction_service: PDFExtractionService) -> None:
        self.extraction_service = extraction_service

    def defer_pdf_screening(
        self,
        payload: ResearchPlanExecuteRequest,
        plan: dict[str, Any],
        response: ResearchPlanExecuteResponse,
    ) -> None:
        articles = pdf_screen_articles(response, payload.pdf_scope)
        questions = research_plan_questions(plan)
        response.run_trace.status = "awaiting_pdf_approval"
        response.run_trace.meta["run_status"] = "awaiting_pdf_approval"
        response.run_trace.meta["pdf_screening"] = {
            "enabled": True,
            "status": "awaiting_approval",
            "reason": "autoprocess_disabled",
            "article_count": len(articles),
            "question_count": len(questions),
            "pdf_scope": payload.pdf_scope,
            "full_text_model": full_text_model_from_payload(payload) or "",
        }
        _set_stage_status(response, "pdf_screening", "awaiting_approval")

    async def run_pdf_screening(
        self,
        payload: ResearchPlanExecuteRequest,
        plan: dict[str, Any],
        response: ResearchPlanExecuteResponse,
        *,
        progress: ProgressCallback | None = None,
    ) -> PDFExtractionResponse | None:
        if not payload.pdf_extractor_enabled:
            response.run_trace.meta["pdf_screening"] = {"enabled": False}
            response.run_trace.status = "completed"
            response.run_trace.meta["run_status"] = "completed"
            _set_stage_status(response, "pdf_screening", "disabled")
            return None

        articles = pdf_screen_articles(response, payload.pdf_scope)
        questions = research_plan_questions(plan)
        fields = research_plan_extraction_fields(plan)
        model = full_text_model_from_payload(payload)
        if not articles or not questions:
            response.run_trace.meta["pdf_screening"] = {
                "enabled": True,
                "status": "skipped",
                "reason": "no_articles_or_questions",
                "article_count": len(articles),
                "question_count": len(questions),
            }
            response.run_trace.status = "completed"
            response.run_trace.meta["run_status"] = "completed"
            _set_stage_status(response, "pdf_screening", "skipped")
            return None

        if progress is not None:
            await progress(
                {
                    "stage": "pdf_screening_start",
                    "message": f"Downloading and screening {len(articles)} full-text articles one by one.",
                    "article_count": len(articles),
                    "question_count": len(questions),
                    "pdf_scope": payload.pdf_scope,
                    "full_text_model": model or "",
                }
            )
        extraction_response = await self.extraction_service.extract(
            PDFExtractionRequest(
                articles=articles,
                questions=questions,
                extraction_fields=fields,
                model=model,
                api_key=payload.api_key,
                thinking_level=payload.thinking_level,
                max_articles=len(articles),
                downloader_mode="pdf_xml",
            )
        )
        response.run_trace.meta["pdf_screening"] = extraction_response.model_dump(mode="json")
        response.run_trace.status = "completed"
        response.run_trace.meta["run_status"] = "completed"
        _set_stage_status(response, "pdf_screening", "completed")
        if progress is not None:
            await progress(
                {
                    "stage": "pdf_screening_complete",
                    "message": (
                        f"PDF/full-text screening complete: {extraction_response.success_count}/"
                        f"{extraction_response.total} articles extracted."
                    ),
                    "total": extraction_response.total,
                    "success_count": extraction_response.success_count,
                    "failed_count": extraction_response.failed_count,
                }
            )
        return extraction_response


def research_plan_questions(plan: dict[str, Any]) -> list[str]:
    strategy = plan.get("extraction_strategy") if isinstance(plan.get("extraction_strategy"), dict) else {}
    raw_specs = plan.get("extraction_question_specs") or strategy.get("extraction_question_specs") or []
    questions = [
        str(item.get("question") or "").strip()
        for item in raw_specs
        if isinstance(item, dict) and str(item.get("question") or "").strip()
    ]
    if questions:
        return questions
    return [
        str(item).strip()
        for item in (plan.get("extraction_questions") or strategy.get("extraction_questions") or [])
        if str(item).strip()
    ]


def research_plan_extraction_fields(plan: dict[str, Any]) -> list[str]:
    strategy = plan.get("extraction_strategy") if isinstance(plan.get("extraction_strategy"), dict) else {}
    return [
        str(item).strip()
        for item in (plan.get("extraction_fields") or strategy.get("extraction_fields") or [])
        if str(item).strip()
    ]


def pdf_screen_articles(response: ResearchPlanExecuteResponse, scope: str) -> list[ArticleReference]:
    normalized_scope = scope if scope in {"selected", "selected_backup", "all"} else "selected_backup"
    if normalized_scope == "selected":
        articles = response.articles
    elif normalized_scope == "all":
        articles = response.candidate_articles or response.articles
    else:
        target_ids = set(response.run_trace.selected_candidate_ids) | set(response.run_trace.backup_candidate_ids)
        articles = [
            article
            for article in (response.candidate_articles or response.articles)
            if str((article.research_meta or {}).get("candidate_id") or "") in target_ids
        ]
        if not articles:
            articles = response.articles
    deduped: list[ArticleReference] = []
    seen: set[str] = set()
    for article in articles:
        key = article.pmc_id or article.pmid or article.doi or article.title
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(article_reference(article))
    return deduped


def article_reference(article: Article) -> ArticleReference:
    return ArticleReference(
        source_name=article.source_name,
        source_record_id=article.source_record_id,
        title=article.title,
        year=article.year,
        journal=article.journal,
        doi=article.doi,
        pmc_id=article.pmc_id,
        pmid=article.pmid,
        oa_pdf_url=article.oa_pdf_url,
        landing_page_url=article.landing_page_url,
    )


def _set_stage_status(response: ResearchPlanExecuteResponse, stage: str, status: str) -> None:
    statuses = response.run_trace.meta.get("stage_statuses")
    if not isinstance(statuses, dict):
        statuses = {}
        response.run_trace.meta["stage_statuses"] = statuses
    statuses[stage] = status
