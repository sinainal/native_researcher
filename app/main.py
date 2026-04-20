"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes.app_settings import router as app_settings_router
from app.api.routes.app_events import router as app_events_router
from app.api.routes.health import router as health_router
from app.api.routes.helper import router as helper_router
from app.api.routes.llm import router as llm_router
from app.api.routes.native import router as native_router
from app.api.routes.pdfs import router as pdf_router
from app.api.routes.projects import router as projects_router
from app.api.routes.pubmed import router as pubmed_router
from app.clients.ncbi import NcbiClient
from app.core.config import Settings, get_settings
from app.services.app_event_log_service import AppEventLogService
from app.services.agent.helper_ai_service import HelperAIService
from app.services.agent.native_researcher_service import NativeResearcherService
from app.services.batch_llm_service import BatchLLMService
from app.services.helper_log_service import HelperLogService
from app.services.journal_metrics_service import JournalMetricsService
from app.services.pdf_service import PDFService
from app.services.project_service import ProjectService
from app.services.pubmed_service import PubMedService
from app.services.workspace_db import WorkspaceDatabase
from app.utils.cache import TTLCache

WEB_DIR = Path(__file__).resolve().parent / "web"


def create_app(
    *,
    settings: Settings | None = None,
    pubmed_service: PubMedService | None = None,
    pdf_service: PDFService | None = None,
    helper_service: HelperAIService | None = None,
    batch_llm_service: BatchLLMService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    injected_pubmed_service = pubmed_service
    injected_pdf_service = pdf_service
    injected_helper_service = helper_service
    injected_batch_llm_service = batch_llm_service
    all_services_injected = (
        injected_pubmed_service is not None
        and injected_pdf_service is not None
        and injected_helper_service is not None
        and injected_batch_llm_service is not None
    )

    def _install_shared_state(
        app: FastAPI,
        *,
        app_event_log_service: AppEventLogService,
        project_service: ProjectService,
        journal_metrics_service: JournalMetricsService,
        pubmed_service: PubMedService,
        pdf_service: PDFService,
        helper_service: HelperAIService,
        batch_llm_service: BatchLLMService,
    ) -> None:
        app.state.settings = resolved_settings
        app.state.pubmed_service = pubmed_service
        app.state.pdf_service = pdf_service
        app.state.helper_service = helper_service
        app.state.batch_llm_service = batch_llm_service
        app.state.app_event_log_service = app_event_log_service
        app.state.project_service = project_service
        app.state.journal_metrics_service = journal_metrics_service
        app.state.native_helper_service = NativeResearcherService(
            thread_cache=TTLCache(
                ttl_seconds=resolved_settings.helper_cache_ttl_seconds,
                max_entries=resolved_settings.helper_cache_max_entries,
            ),
            pubmed_service=pubmed_service,
            log_service=HelperLogService(resolved_settings.helper_log_path),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if all_services_injected:
            _install_shared_state(
                app,
                app_event_log_service=AppEventLogService(resolved_settings.app_event_log_path),
                project_service=ProjectService(resolved_settings.workspace_root),
                journal_metrics_service=JournalMetricsService(
                    WorkspaceDatabase(resolved_settings.workspace_root / ".native_researcher.db"),
                    resolved_settings,
                ),
                pubmed_service=injected_pubmed_service,
                pdf_service=injected_pdf_service,
                helper_service=injected_helper_service,
                batch_llm_service=injected_batch_llm_service,
            )
            yield
            return

        timeout = httpx.Timeout(resolved_settings.http_timeout_seconds)
        ncbi_client = None
        shared_client = None
        search_client = None
        if injected_pubmed_service is None:
            ncbi_client = httpx.AsyncClient(
                base_url=resolved_settings.ncbi_base_url,
                timeout=timeout,
                headers={"User-Agent": resolved_settings.request_user_agent},
                follow_redirects=True,
            )
            search_client = httpx.AsyncClient(
                timeout=timeout,
                headers={"User-Agent": resolved_settings.request_user_agent},
                follow_redirects=True,
            )
        if injected_pdf_service is None:
            shared_client = httpx.AsyncClient(
                timeout=timeout,
                headers={"User-Agent": resolved_settings.request_user_agent},
                follow_redirects=True,
            )
        app_event_log_service = AppEventLogService(resolved_settings.app_event_log_path)
        project_service = ProjectService(resolved_settings.workspace_root)
        journal_metrics_service = JournalMetricsService(
            WorkspaceDatabase(resolved_settings.workspace_root / ".native_researcher.db"),
            resolved_settings,
            http_client=search_client,
        )
        await journal_metrics_service.ensure_bootstrap()
        pubmed_service = injected_pubmed_service or PubMedService(
            client=NcbiClient(ncbi_client, resolved_settings),  # type: ignore[arg-type]
            cache=TTLCache(
                ttl_seconds=resolved_settings.search_cache_ttl_seconds,
                max_entries=resolved_settings.search_cache_max_entries,
            ),
            http_client=search_client,
            settings=resolved_settings,
            journal_metrics_service=journal_metrics_service,
        )
        pdf_service = injected_pdf_service or PDFService(
            http_client=shared_client,  # type: ignore[arg-type]
            settings=resolved_settings,
            candidate_cache=TTLCache(
                ttl_seconds=resolved_settings.pdf_cache_ttl_seconds,
                max_entries=resolved_settings.pdf_cache_max_entries,
            ),
            event_log_service=app_event_log_service,
        )
        helper_service = injected_helper_service or HelperAIService(
            thread_cache=TTLCache(
                ttl_seconds=resolved_settings.helper_cache_ttl_seconds,
                max_entries=resolved_settings.helper_cache_max_entries,
            ),
            pubmed_service=pubmed_service,
            log_service=HelperLogService(resolved_settings.helper_log_path),
        )
        batch_llm_service = injected_batch_llm_service or BatchLLMService()
        _install_shared_state(
            app,
            app_event_log_service=app_event_log_service,
            project_service=project_service,
            journal_metrics_service=journal_metrics_service,
            pubmed_service=pubmed_service,
            pdf_service=pdf_service,
            helper_service=helper_service,
            batch_llm_service=batch_llm_service,
        )
        try:
            yield
        finally:
            warmup_task = getattr(app.state, "ollama_warmup_task", None)
            if warmup_task is not None and not warmup_task.done():
                warmup_task.cancel()
            if ncbi_client is not None:
                await ncbi_client.aclose()
            if search_client is not None:
                await search_client.aclose()
            if shared_client is not None:
                await shared_client.aclose()
            ollama_process = getattr(app.state, "ollama_process", None)
            if ollama_process is not None:
                poll = getattr(ollama_process, "poll", None)
                running = callable(poll) and poll() is None
                if running:
                    try:
                        ollama_process.terminate()
                        await asyncio.to_thread(ollama_process.wait, 10)
                    except Exception:
                        try:
                            ollama_process.kill()
                        except Exception:
                            pass
                app.state.ollama_process = None

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.version,
        debug=resolved_settings.debug,
        lifespan=None if all_services_injected else lifespan,
    )

    if all_services_injected:
        _install_shared_state(
            app,
            app_event_log_service=AppEventLogService(resolved_settings.app_event_log_path),
            project_service=ProjectService(resolved_settings.workspace_root),
            journal_metrics_service=JournalMetricsService(
                WorkspaceDatabase(resolved_settings.workspace_root / ".native_researcher.db"),
                resolved_settings,
            ),
            pubmed_service=injected_pubmed_service,
            pdf_service=injected_pdf_service,
            helper_service=injected_helper_service,
            batch_llm_service=injected_batch_llm_service,
        )
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    app.include_router(app_settings_router)
    app.include_router(app_events_router)
    app.include_router(health_router)
    app.include_router(helper_router)
    app.include_router(llm_router)
    app.include_router(native_router)
    app.include_router(pubmed_router)
    app.include_router(pdf_router)
    app.include_router(projects_router)
    return app


app = create_app()
