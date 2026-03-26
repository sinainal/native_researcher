"""Basic application routes and web UI."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

router = APIRouter(tags=["health"])
WEB_DIR = Path(__file__).resolve().parents[2] / "web"


@router.get("/", include_in_schema=False)
async def root() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "landing.html").read_text(encoding="utf-8"))


@router.get("/landing", include_in_schema=False)
async def landing() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "landing.html").read_text(encoding="utf-8"))


@router.get("/workspace", include_in_schema=False)
async def workspace() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "native_researcher.html").read_text(encoding="utf-8"))


@router.get("/native_researcher", include_in_schema=False)
async def native_root() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "native_researcher.html").read_text(encoding="utf-8"))


@router.get("/researcher_2", include_in_schema=False)
async def legacy_root() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/app/bootstrap")
async def bootstrap() -> dict[str, str]:
    api_key_path = WEB_DIR.parents[2] / "api_key.txt"
    api_key = ""
    if api_key_path.exists():
        api_key = api_key_path.read_text(encoding="utf-8").strip()
    return {"api_key": api_key}
