"""Workspace project service."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.schemas.project import (
    ProjectCreateRequest,
    ProjectDownloadItem,
    ProjectSummary,
    ProjectUpdateRequest,
)
from app.schemas.project_state import ProjectStatePayload
from app.services.workspace_db import WorkspaceDatabase


class ProjectService:
    _DOWNLOAD_SOURCE_SUFFIXES = (
        "article_oa_pdf",
        "pmc_direct_pdf",
        "pmc_oa_package",
        "europe_pmc_repo_pdf",
        "europe_pmc_render_pdf",
        "crossref_pdf",
        "doi_landing_pdf",
        "article_landing_pdf",
        "landing_page_probe",
        "ncbi_linkout_pdf",
        "pmc_efetch_xml",
        "europe_pmc_repo_xml",
        "europe_pmc_xml",
        "crossref_xml",
    )

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self.projects_root = workspace_root / "projects"
        self.database = WorkspaceDatabase(workspace_root / ".native_researcher.db")
        self.projects_root.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> list[ProjectSummary]:
        self._sync_workspace_from_disk()
        rows = self.database.fetchall(
            """
            SELECT id, name, description, created_at, updated_at, project_path
            FROM projects
            ORDER BY updated_at DESC
            """
        )
        projects = [self._project_summary_from_row(row) for row in rows]
        projects.sort(key=lambda item: item.updated_at, reverse=True)
        return projects

    def create_project(self, payload: ProjectCreateRequest) -> ProjectSummary:
        self._sync_workspace_from_disk()
        resolved_name = payload.name.strip() or self._next_default_project_name()
        project_id = self._unique_project_id(resolved_name)
        project_dir = self.projects_root / project_id
        self._ensure_project_layout(project_dir)

        timestamp = self._utc_now()
        metadata = {
            "id": project_id,
            "name": resolved_name,
            "description": payload.description.strip(),
            "created_at": timestamp,
            "updated_at": timestamp,
            "project_path": str(project_dir),
        }
        self._write_metadata_file(project_dir, metadata)
        self._write_state_file(project_dir, ProjectStatePayload())
        self._upsert_project_record(metadata)
        self._save_state_to_db(project_id, ProjectStatePayload(), timestamp)
        return self._project_summary(project_dir, metadata)

    def get_project(self, project_id: str) -> ProjectSummary | None:
        self._sync_workspace_from_disk()
        return self._load_project_summary(project_id)

    def get_project_state(self, project_id: str) -> ProjectStatePayload | None:
        self._sync_workspace_from_disk()
        if self._fetch_project_row(project_id) is None:
            return None
        return self._read_state_from_db(project_id)

    def save_project_state(self, project_id: str, payload: ProjectStatePayload) -> ProjectStatePayload | None:
        self._sync_workspace_from_disk()
        row = self._fetch_project_row(project_id)
        if row is None:
            return None

        timestamp = self._utc_now()
        self._save_state_to_db(project_id, payload, timestamp)

        project_dir = Path(row["project_path"])
        self._ensure_project_layout(project_dir)
        metadata = self._read_metadata_file(project_dir) or {
            "id": project_id,
            "name": row["name"],
            "description": row["description"],
            "created_at": row["created_at"],
            "project_path": row["project_path"],
        }
        metadata["updated_at"] = timestamp
        metadata["project_path"] = str(project_dir)
        self._write_metadata_file(project_dir, metadata)
        self._write_state_file(project_dir, payload)
        self._upsert_project_record(metadata)
        return self._read_state_from_db(project_id)

    def list_project_downloads(self, project_id: str) -> list[ProjectDownloadItem] | None:
        self._sync_workspace_from_disk()
        row = self._fetch_project_row(project_id)
        if row is None:
            return None
        return self._sync_project_download_index(project_id, Path(row["project_path"]))

    def update_project(self, project_id: str, payload: ProjectUpdateRequest) -> ProjectSummary | None:
        self._sync_workspace_from_disk()
        row = self._fetch_project_row(project_id)
        if row is None:
            return None

        next_name = payload.name.strip()
        if not next_name:
            return None

        metadata = {
            "id": project_id,
            "name": next_name,
            "description": row["description"],
            "created_at": row["created_at"],
            "updated_at": self._utc_now(),
            "project_path": row["project_path"],
        }
        self._upsert_project_record(metadata)
        project_dir = Path(row["project_path"])
        self._ensure_project_layout(project_dir)
        self._write_metadata_file(project_dir, metadata)
        return self._project_summary(project_dir, metadata)

    def delete_project(self, project_id: str) -> ProjectSummary | None:
        self._sync_workspace_from_disk()
        row = self._fetch_project_row(project_id)
        if row is None:
            return None

        project_dir = Path(str(row["project_path"])).resolve()
        projects_root = self.projects_root.resolve()
        try:
            project_dir.relative_to(projects_root)
        except ValueError:
            return None

        summary = self._project_summary_from_row(row)
        if project_dir.exists():
            shutil.rmtree(project_dir)
        self.database.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return summary

    def touch_project(self, project_id: str) -> ProjectSummary | None:
        self._sync_workspace_from_disk()
        row = self._fetch_project_row(project_id)
        if row is None:
            return None

        metadata = {
            "id": project_id,
            "name": row["name"],
            "description": row["description"],
            "created_at": row["created_at"],
            "updated_at": self._utc_now(),
            "project_path": row["project_path"],
        }
        self._upsert_project_record(metadata)
        project_dir = Path(row["project_path"])
        self._ensure_project_layout(project_dir)
        self._write_metadata_file(project_dir, metadata)
        return self._project_summary(project_dir, metadata)

    def _sync_workspace_from_disk(self) -> None:
        self.projects_root.mkdir(parents=True, exist_ok=True)
        for directory in sorted(self.projects_root.iterdir()):
            if not directory.is_dir():
                continue

            metadata = self._read_metadata_file(directory)
            if metadata is None:
                continue

            metadata.setdefault("id", directory.name)
            metadata.setdefault("name", directory.name)
            metadata.setdefault("description", "")
            metadata.setdefault("created_at", self._utc_now())
            metadata.setdefault("updated_at", metadata["created_at"])
            metadata["project_path"] = str(directory)
            self._ensure_project_layout(directory)

            row = self._fetch_project_row(str(metadata["id"]))
            if row is None or self._is_newer(str(metadata["updated_at"]), str(row["updated_at"])):
                self._upsert_project_record(metadata)
                state = self._read_state_file(directory)
                self._save_state_to_db(str(metadata["id"]), state, str(metadata["updated_at"]))
                continue

            if self._database_has_no_state(str(metadata["id"])):
                state = self._read_state_file(directory)
                self._save_state_to_db(str(metadata["id"]), state, str(metadata["updated_at"]))

    def _load_project_summary(self, project_id: str) -> ProjectSummary | None:
        row = self._fetch_project_row(project_id)
        if row is None:
            return None
        return self._project_summary_from_row(row)

    def _project_summary_from_row(self, row: Any) -> ProjectSummary:
        directory = Path(str(row["project_path"]))
        self._ensure_project_layout(directory)
        return self._project_summary(
            directory,
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "project_path": row["project_path"],
            },
        )

    def _fetch_project_row(self, project_id: str) -> Any | None:
        return self.database.fetchone(
            """
            SELECT id, name, description, created_at, updated_at, project_path
            FROM projects
            WHERE id = ?
            """,
            (project_id,),
        )

    def _database_has_no_state(self, project_id: str) -> bool:
        row = self.database.fetchone(
            "SELECT project_id FROM project_state WHERE project_id = ?",
            (project_id,),
        )
        return row is None

    def _read_state_from_db(self, project_id: str) -> ProjectStatePayload:
        state_row = self.database.fetchone(
            """
            SELECT
                active_query_id,
                selected_ids_json,
                detail_article_id,
                sidebar_panel,
                query_detail_id,
                downloadability_cache_json,
                current_session_id,
                assistant_sessions_json
            FROM project_state
            WHERE project_id = ?
            """,
            (project_id,),
        )
        if state_row is None:
            return ProjectStatePayload()

        query_rows = self.database.fetchall(
            """
            SELECT query_id, title, created_at, updated_at, search_payload_json, meta_json, articles_json
            FROM project_queries
            WHERE project_id = ?
            ORDER BY position ASC, updated_at DESC
            """,
            (project_id,),
        )
        payload: dict[str, Any] = {
            "active_query_id": state_row["active_query_id"],
            "selected_ids": self._loads_json(state_row["selected_ids_json"], default=[]),
            "detail_article_id": state_row["detail_article_id"],
            "sidebar_panel": state_row["sidebar_panel"] or "queries",
            "query_detail_id": state_row["query_detail_id"],
            "downloadability_cache": self._loads_json(state_row["downloadability_cache_json"], default={}),
            "current_session_id": state_row["current_session_id"],
            "assistant_sessions": self._loads_json(state_row["assistant_sessions_json"], default=[]),
            "query_history": [],
        }
        for row in query_rows:
            payload["query_history"].append(
                {
                    "id": row["query_id"],
                    "title": row["title"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "search_payload": self._loads_json(row["search_payload_json"], default={}),
                    "meta": self._loads_json(row["meta_json"], default=None),
                    "articles": self._loads_json(row["articles_json"], default=[]),
                }
            )
        try:
            return ProjectStatePayload.model_validate(payload)
        except Exception:
            return ProjectStatePayload()

    def _save_state_to_db(self, project_id: str, payload: ProjectStatePayload, timestamp: str) -> None:
        with self.database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO project_state (
                    project_id, active_query_id, selected_ids_json, detail_article_id,
                    sidebar_panel, query_detail_id, downloadability_cache_json, current_session_id,
                    assistant_sessions_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    active_query_id = excluded.active_query_id,
                    selected_ids_json = excluded.selected_ids_json,
                    detail_article_id = excluded.detail_article_id,
                    sidebar_panel = excluded.sidebar_panel,
                    query_detail_id = excluded.query_detail_id,
                    downloadability_cache_json = excluded.downloadability_cache_json,
                    current_session_id = excluded.current_session_id,
                    assistant_sessions_json = excluded.assistant_sessions_json,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    payload.active_query_id,
                    json.dumps(payload.selected_ids, ensure_ascii=True),
                    payload.detail_article_id,
                    payload.sidebar_panel,
                    payload.query_detail_id,
                    json.dumps(payload.downloadability_cache, ensure_ascii=True),
                    payload.current_session_id,
                    json.dumps(payload.assistant_sessions, ensure_ascii=True),
                    timestamp,
                ),
            )
            conn.execute("DELETE FROM project_queries WHERE project_id = ?", (project_id,))
            for position, query in enumerate(payload.query_history):
                conn.execute(
                    """
                    INSERT INTO project_queries (
                        project_id, query_id, position, title, created_at, updated_at,
                        search_payload_json, meta_json, articles_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        query.id,
                        position,
                        query.title,
                        query.created_at,
                        query.updated_at,
                        json.dumps(query.search_payload.model_dump(mode="json"), ensure_ascii=True),
                        (
                            json.dumps(query.meta.model_dump(mode="json"), ensure_ascii=True)
                            if query.meta is not None
                            else None
                        ),
                        json.dumps(
                            [article.model_dump(mode="json") for article in query.articles],
                            ensure_ascii=True,
                        ),
                    ),
                )

    def _upsert_project_record(self, metadata: dict[str, Any]) -> None:
        project_dir = Path(str(metadata["project_path"]))
        self._ensure_project_layout(project_dir)
        self.database.execute(
            """
            INSERT INTO projects (id, name, description, created_at, updated_at, project_path)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                project_path = excluded.project_path
            """,
            (
                str(metadata["id"]),
                str(metadata["name"]),
                str(metadata.get("description") or ""),
                str(metadata["created_at"]),
                str(metadata["updated_at"]),
                str(project_dir),
            ),
        )

    def _sync_project_download_index(self, project_id: str, project_dir: Path) -> list[ProjectDownloadItem]:
        self._ensure_project_layout(project_dir)
        download_dir = project_dir / "pdfs"
        download_dir.mkdir(parents=True, exist_ok=True)

        entries = sorted(
            (
                item
                for item in download_dir.rglob("*")
                if item.is_file() and item.suffix.lower() in {".pdf", ".xml"}
            ),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        indexed: list[tuple[str, str, int, str]] = []
        for entry in entries:
            stat = entry.stat()
            indexed.append(
                (
                    entry.relative_to(project_dir).as_posix(),
                    entry.name,
                    stat.st_size,
                    datetime.fromtimestamp(stat.st_mtime, UTC).replace(microsecond=0).isoformat(),
                )
            )

        with self.database.transaction() as conn:
            existing_rows = conn.execute(
                """
                SELECT relative_path, created_at
                FROM project_documents
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchall()
            existing = {str(row["relative_path"]): str(row["created_at"]) for row in existing_rows}
            current_paths = {relative_path for relative_path, _, _, _ in indexed}
            for missing in set(existing) - current_paths:
                conn.execute(
                    """
                    DELETE FROM project_documents
                    WHERE project_id = ? AND relative_path = ?
                    """,
                    (project_id, missing),
                )

            for relative_path, file_name, size_bytes, modified_at in indexed:
                created_at = existing.get(relative_path, modified_at)
                conn.execute(
                    """
                    INSERT INTO project_documents (
                        project_id, relative_path, file_name, size_bytes,
                        modified_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id, relative_path) DO UPDATE SET
                        file_name = excluded.file_name,
                        size_bytes = excluded.size_bytes,
                        modified_at = excluded.modified_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        project_id,
                        relative_path,
                        file_name,
                        size_bytes,
                        modified_at,
                        created_at,
                        modified_at,
                    ),
                )

            rows = conn.execute(
                """
                SELECT file_name, relative_path, size_bytes, modified_at
                FROM project_documents
                WHERE project_id = ?
                ORDER BY modified_at DESC, file_name ASC
                """,
                (project_id,),
            ).fetchall()

        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            relative_path = Path(str(row["relative_path"]))
            group_key = self._download_group_key(relative_path)
            grouped.setdefault(group_key, []).append(
                {
                    "relative_path": str(row["relative_path"]),
                    "file_name": str(row["file_name"]),
                    "size_bytes": int(row["size_bytes"]),
                    "modified_at": str(row["modified_at"]),
                    "artifact_type": self._artifact_type_from_path(relative_path),
                }
            )

        items: list[ProjectDownloadItem] = []
        for group_rows in grouped.values():
            group_rows.sort(key=lambda item: (item["modified_at"], item["file_name"]), reverse=True)
            preferred = next((item for item in group_rows if item["artifact_type"] == "pdf"), group_rows[0])
            artifact_types: list[str] = []
            if any(item["artifact_type"] == "pdf" for item in group_rows):
                artifact_types.append("pdf")
            if any(item["artifact_type"] == "xml" for item in group_rows):
                artifact_types.append("xml")
            items.append(
                ProjectDownloadItem(
                    name=preferred["file_name"],
                    path=str(project_dir / preferred["relative_path"]),
                    size_bytes=sum(item["size_bytes"] for item in group_rows),
                    modified_at=group_rows[0]["modified_at"],
                    artifact_types=artifact_types,
                )
            )

        items.sort(key=lambda item: (item.modified_at, item.name), reverse=True)
        return items

    @classmethod
    def _download_group_key(cls, relative_path: Path) -> tuple[str, str]:
        stem = relative_path.stem
        for suffix in sorted(cls._DOWNLOAD_SOURCE_SUFFIXES, key=len, reverse=True):
            marker = f"_{suffix}"
            if stem.endswith(marker):
                stem = stem[: -len(marker)]
                break
        return relative_path.parent.as_posix(), stem.lower()

    @staticmethod
    def _artifact_type_from_path(relative_path: Path) -> str:
        suffix = relative_path.suffix.lower()
        if suffix == ".pdf":
            return "pdf"
        if suffix == ".xml":
            return "xml"
        return "file"

    def _unique_project_id(self, name: str) -> str:
        base = self._slugify(name) or "project"
        candidate = base
        suffix = 2
        while self._fetch_project_row(candidate) is not None or (self.projects_root / candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def _next_default_project_name(self) -> str:
        pattern = re.compile(r"^project\s+(\d+)$", re.IGNORECASE)
        highest = 0
        for project in self.list_projects():
            match = pattern.match(project.name.strip())
            if match:
                highest = max(highest, int(match.group(1)))
        return f"Project {highest + 1}"

    def _project_summary(self, directory: Path, payload: dict[str, Any]) -> ProjectSummary:
        self._ensure_project_layout(directory)
        return ProjectSummary(
            id=str(payload.get("id") or directory.name),
            name=str(payload.get("name") or directory.name),
            description=str(payload.get("description") or ""),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            pdf_count=self._count_files(directory / "pdfs", ".pdf"),
            note_count=self._count_files(directory / "notes", ".md"),
            project_path=str(directory),
        )

    @staticmethod
    def _read_metadata_file(directory: Path) -> dict[str, Any] | None:
        metadata_path = directory / "project.json"
        if not directory.exists() or not directory.is_dir() or not metadata_path.exists():
            return None
        try:
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _read_state_file(directory: Path) -> ProjectStatePayload:
        state_path = directory / "state.json"
        if not state_path.exists():
            return ProjectStatePayload()
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ProjectStatePayload()
        try:
            return ProjectStatePayload.model_validate(payload)
        except Exception:
            return ProjectStatePayload()

    @staticmethod
    def _write_metadata_file(directory: Path, payload: dict[str, Any]) -> None:
        (directory / "project.json").write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _write_state_file(directory: Path, payload: ProjectStatePayload) -> None:
        (directory / "state.json").write_text(payload.model_dump_json(indent=2), encoding="utf-8")

    @staticmethod
    def _ensure_project_layout(project_dir: Path) -> None:
        for relative in ("pdfs", "derived", "indexes", "exports", "notes"):
            (project_dir / relative).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _loads_json(raw: str | None, *, default: Any) -> Any:
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _is_newer(candidate: str, current: str) -> bool:
        candidate_dt = ProjectService._parse_timestamp(candidate)
        current_dt = ProjectService._parse_timestamp(current)
        if candidate_dt is None:
            return False
        if current_dt is None:
            return True
        return candidate_dt >= current_dt

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
        return normalized[:80]

    @staticmethod
    def _count_files(directory: Path, suffix: str) -> int:
        if not directory.exists():
            return 0
        return sum(1 for item in directory.rglob(f"*{suffix}") if item.is_file() and item.suffix.lower() == suffix)
