"""PDF endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.schemas.article import ArticleReference
from app.schemas.pdf import (
    PDFAvailabilityRequest,
    PDFAvailabilityResponse,
    PDFDownloadRequest,
    PDFDownloadResponse,
    PDFResolveResponse,
    PDFTestRequest,
    PDFTestResponse,
)
from app.schemas.pubmed import PubMedSearchRequest
from app.services.pdf_service import PDFService
from app.services.pubmed_service import PubMedService

router = APIRouter(prefix="/pdf", tags=["pdf"])
PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = Path(__file__).resolve().parents[4]


def get_pdf_service(request: Request) -> PDFService:
    return request.app.state.pdf_service


def get_pubmed_service(request: Request) -> PubMedService:
    return request.app.state.pubmed_service


@router.post("/resolve", response_model=PDFResolveResponse)
async def resolve_pdf_candidates(
    article: ArticleReference,
    request: Request,
) -> PDFResolveResponse:
    service = get_pdf_service(request)
    try:
        return await service.resolve(article, mode="balanced")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/availability/fast", response_model=PDFAvailabilityResponse)
async def verify_fast_availability(
    payload: PDFAvailabilityRequest,
    request: Request,
) -> PDFAvailabilityResponse:
    service = get_pdf_service(request)
    try:
        return await service.quick_availability(payload.articles[:24])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/download", response_model=PDFDownloadResponse)
async def download_pdfs(
    payload: PDFDownloadRequest,
    request: Request,
) -> PDFDownloadResponse:
    service = get_pdf_service(request)
    try:
        return await service.download_articles(payload)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/test", response_model=PDFTestResponse)
async def test_pdf_pipeline(
    payload: PDFTestRequest,
    request: Request,
) -> PDFTestResponse:
    pubmed_service = get_pubmed_service(request)
    pdf_service = get_pdf_service(request)
    try:
        search = await pubmed_service.search(
            PubMedSearchRequest(
                query=payload.query,
                year_start=payload.year_start,
                year_end=payload.year_end,
                max_results=payload.max_results,
                batch_size=payload.batch_size,
                use_cache=True,
            )
        )
        articles = [
            ArticleReference(
                title=article.title,
                year=article.year,
                doi=article.doi,
                pmc_id=article.pmc_id,
                pmid=article.pmid,
            )
            for article in search.articles
        ]
        diagnostics = await pdf_service.diagnose_articles(
            articles,
            download_dir=payload.download_dir,
            save_files=payload.save_files,
            mode=payload.mode,
            use_browser_fallback=payload.use_browser_fallback,
        )
        success_count = sum(1 for item in diagnostics if item.success)
        reason_counts: dict[str, int] = {}
        for item in diagnostics:
            reason_counts[item.reason] = reason_counts.get(item.reason, 0) + 1
        total = len(diagnostics)
        return PDFTestResponse(
            query=payload.query,
            pubmed_meta=search.meta,
            total=total,
            success_count=success_count,
            failed_count=total - success_count,
            success_rate=round((success_count / total) * 100, 2) if total else 0.0,
            reason_counts=reason_counts,
            results=diagnostics,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/file", response_model=None)
async def open_downloaded_file(path: str):
    try:
        resolved = Path(path).expanduser().resolve()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid file path.") from exc

    allowed_roots = (PROJECT_ROOT, WORKSPACE_ROOT, Path("/tmp"))
    if not any(root == resolved or root in resolved.parents for root in allowed_roots):
        raise HTTPException(status_code=403, detail="File path is outside allowed roots.")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(resolved)
