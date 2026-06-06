"""Small HTTP client used by the Native Researcher MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class NativeResearcherClientConfig:
    base_url: str = "http://127.0.0.1:8000"
    timeout: float = 120.0


class NativeResearcherClient:
    """Synchronous wrapper around the local Native Researcher FastAPI app."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = NativeResearcherClientConfig(base_url=base_url.rstrip("/"), timeout=timeout)
        self._client = httpx.Client(
            base_url=self.config.base_url,
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def health(self) -> dict[str, Any]:
        return self._get_json("/health")

    def bootstrap(self) -> dict[str, Any]:
        return self._get_json("/app/bootstrap")

    def list_projects(self) -> dict[str, Any]:
        return self._get_json("/app/projects")

    def create_project(self, *, name: str, description: str = "") -> dict[str, Any]:
        return self._post_json("/app/projects", {"name": name, "description": description})

    def get_project(self, project_id: str) -> dict[str, Any]:
        return self._get_json(f"/app/projects/{project_id}")

    def get_project_state(self, project_id: str) -> dict[str, Any]:
        return self._get_json(f"/app/projects/{project_id}/state")

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/pubmed/search", payload)

    def assistant_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/assistant/chat", payload)

    def execute_research_plan(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json(f"/app/projects/{project_id}/research-plan/execute", payload)

    def resolve_pdf(self, article: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/pdf/resolve", article)

    def download_pdfs(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/pdf/download", payload)

    def extract_pdf_answers(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/pdf/extract", payload)

    def _get_json(self, path: str) -> dict[str, Any]:
        response = self._client.get(path)
        return self._response_json(response)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(path, json=payload)
        return self._response_json(response)

    @staticmethod
    def _response_json(response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                payload = exc.response.json()
                detail = str(payload.get("detail") or payload)
            except Exception:
                detail = exc.response.text[:500]
            raise RuntimeError(f"Native Researcher HTTP {exc.response.status_code}: {detail}") from exc
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Native Researcher returned a non-object JSON response.")
        return payload
