"""PubMed endpoints."""

from fastapi import APIRouter, HTTPException, Request

from app.schemas.pubmed import (
    PubMedCitationRequest,
    PubMedCitationResponse,
    PubMedSearchRequest,
    PubMedSearchResponse,
)
from app.services.pubmed_service import PubMedService

router = APIRouter(prefix="/pubmed", tags=["pubmed"])


def get_pubmed_service(request: Request) -> PubMedService:
    return request.app.state.pubmed_service


@router.post("/search", response_model=PubMedSearchResponse)
async def search_pubmed(
    payload: PubMedSearchRequest,
    request: Request,
) -> PubMedSearchResponse:
    service = get_pubmed_service(request)
    try:
        return await service.search(payload)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/citations", response_model=PubMedCitationResponse)
async def enrich_pubmed_citations(
    payload: PubMedCitationRequest,
    request: Request,
) -> PubMedCitationResponse:
    service = get_pubmed_service(request)
    try:
        return await service.enrich_citations(payload)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
