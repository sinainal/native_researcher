"""Research plan execution routes."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from app.schemas.article import Article, ArticleReference
from app.schemas.pdf_extraction import PDFExtractionRequest, PDFExtractionResponse
from app.schemas.project_state import ProjectQueryRecord, ProjectSearchPayload
from app.schemas.research_execution import ResearchPlanExecuteRequest, ResearchPlanExecuteResponse
from app.services.pdf_extraction_service import PDFExtractionService
from app.services.project_service import ProjectService
from app.services.research_execution_service import ResearchExecutionService

router = APIRouter(prefix="/app/projects", tags=["research-execution"])


def get_research_execution_service(request: Request) -> ResearchExecutionService:
    return request.app.state.research_execution_service


def get_project_service(request: Request) -> ProjectService:
    return request.app.state.project_service


def get_pdf_extraction_service(request: Request) -> PDFExtractionService:
    return PDFExtractionService(
        pdf_service=request.app.state.pdf_service,
        settings=getattr(request.app.state, "settings", None),
    )


def _persist_research_execution(project_service: ProjectService, project_id: str, response: ResearchPlanExecuteResponse) -> None:
    current_state = project_service.get_project_state(project_id)
    if current_state is None:
        return
    current_state.research_runs.insert(0, response.run_trace.model_dump(mode="json"))
    current_state.research_runs = current_state.research_runs[:20]
    full_articles = response.candidate_articles or response.articles
    if full_articles:
        timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
        query_id = f"research_{response.run_trace.id}"
        query_title = response.run_trace.topic or response.run_trace.objective or "Research plan execution"
        current_state.query_history = [
            item for item in current_state.query_history if item.id != query_id
        ]
        current_state.query_history.insert(
            0,
            ProjectQueryRecord(
                id=query_id,
                title=f"{query_title} · Agent Query",
                created_at=timestamp,
                updated_at=timestamp,
                search_payload=ProjectSearchPayload(
                    query=query_title,
                    year_start=response.run_trace.meta.get("year_start"),
                    year_end=response.run_trace.meta.get("year_end"),
                    max_results=max(1, min(5000, len(full_articles))),
                    batch_size=None,
                    min_cite=None,
                    article_type=None,
                    use_cache=True,
                    preferred_source="pubmed",
                ),
                meta=response.meta.model_copy(
                    update={
                        "fetched_results": len(full_articles),
                        "batch_size_used": len(full_articles),
                        "primary_source": "research_plan_candidates",
                    }
                ),
                articles=full_articles,
            ),
        )
        current_state.query_history = current_state.query_history[:30]
    project_service.save_project_state(project_id, current_state)


def _execution_plan_from_payload(payload: ResearchPlanExecuteRequest) -> dict:
    plan = dict(payload.plan)
    if not payload.criteria_enabled:
        plan["criteria_mode"] = "disabled"
        plan["screening_criteria"] = []
        plan["exclusion_criteria"] = []
    plan["full_text_settings"] = {
        "pdf_extractor_enabled": bool(payload.pdf_extractor_enabled),
        "pdf_scope": payload.pdf_scope,
        "full_text_model": _full_text_model_from_payload(payload) or "",
    }
    return plan


def _full_text_model_from_payload(payload: ResearchPlanExecuteRequest) -> str | None:
    if payload.full_text_model is not None:
        return payload.full_text_model
    return payload.screening_model


def _research_plan_questions(plan: dict) -> list[str]:
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


def _research_plan_extraction_fields(plan: dict) -> list[str]:
    strategy = plan.get("extraction_strategy") if isinstance(plan.get("extraction_strategy"), dict) else {}
    return [
        str(item).strip()
        for item in (plan.get("extraction_fields") or strategy.get("extraction_fields") or [])
        if str(item).strip()
    ]


def _article_reference(article: Article) -> ArticleReference:
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


def _pdf_screen_articles(response: ResearchPlanExecuteResponse, scope: str) -> list[ArticleReference]:
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
        deduped.append(_article_reference(article))
    return deduped


async def _run_pdf_screening(
    request: Request,
    payload: ResearchPlanExecuteRequest,
    plan: dict,
    response: ResearchPlanExecuteResponse,
    *,
    progress=None,
) -> PDFExtractionResponse | None:
    if not payload.pdf_extractor_enabled:
        response.run_trace.meta["pdf_screening"] = {"enabled": False}
        return None

    articles = _pdf_screen_articles(response, payload.pdf_scope)
    questions = _research_plan_questions(plan)
    fields = _research_plan_extraction_fields(plan)
    model = _full_text_model_from_payload(payload)
    if not articles or not questions:
        response.run_trace.meta["pdf_screening"] = {
            "enabled": True,
            "status": "skipped",
            "reason": "no_articles_or_questions",
            "article_count": len(articles),
            "question_count": len(questions),
        }
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
    extraction_response = await get_pdf_extraction_service(request).extract(
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


@router.post("/{project_id}/research-plan/execute", response_model=ResearchPlanExecuteResponse)
async def execute_research_plan(
    project_id: str,
    payload: ResearchPlanExecuteRequest,
    request: Request,
) -> ResearchPlanExecuteResponse:
    project_service = get_project_service(request)
    state = project_service.get_project_state(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    execution_service = get_research_execution_service(request)
    try:
        plan = _execution_plan_from_payload(payload)
        response = await execution_service.execute_plan_with_screening(
            plan,
            screening_model=payload.screening_model,
            api_key=payload.api_key,
            thinking_level=payload.thinking_level,
        )
        await _run_pdf_screening(request, payload, plan, response)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _persist_research_execution(project_service, project_id, response)
    request.app.state.app_event_log_service.log(
        "info",
        "research_plan_executed",
        response.run_trace.topic or "Research plan executed",
        context={
            "project_id": project_id,
            "run_id": response.run_trace.id,
            "candidate_count": response.run_trace.meta.get("candidate_count"),
            "selected_count": response.run_trace.meta.get("selected_count"),
        },
    )
    return response


@router.post("/{project_id}/research-plan/execute/stream")
async def execute_research_plan_stream(
    project_id: str,
    payload: ResearchPlanExecuteRequest,
    request: Request,
) -> StreamingResponse:
    project_service = get_project_service(request)
    state = project_service.get_project_state(project_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    execution_service = get_research_execution_service(request)

    async def event_stream():
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

        async def progress(event: dict[str, object]) -> None:
            await queue.put({"type": "trace", **event})

        async def run_execution() -> None:
            try:
                plan = _execution_plan_from_payload(payload)
                response = await execution_service.execute_plan_with_screening(
                    plan,
                    screening_model=payload.screening_model,
                    api_key=payload.api_key,
                    thinking_level=payload.thinking_level,
                    progress=progress,
                )
                await _run_pdf_screening(request, payload, plan, response, progress=progress)
                _persist_research_execution(project_service, project_id, response)
                request.app.state.app_event_log_service.log(
                    "info",
                    "research_plan_executed",
                    response.run_trace.topic or "Research plan executed",
                    context={
                        "project_id": project_id,
                        "run_id": response.run_trace.id,
                        "candidate_count": response.run_trace.meta.get("candidate_count"),
                        "selected_count": response.run_trace.meta.get("selected_count"),
                    },
                )
                await queue.put({"type": "final", "response": response.model_dump(mode="json")})
            except Exception as exc:
                await queue.put({"type": "error", "message": str(exc)})
            finally:
                await queue.put({"type": "done"})

        task = asyncio.create_task(run_execution())
        try:
            while True:
                event = await queue.get()
                if event.get("type") == "done":
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
