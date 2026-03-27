"""Workspace project service."""

from __future__ import annotations

import json
import re
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


class ProjectService:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self.projects_root = workspace_root / "projects"

    def list_projects(self) -> list[ProjectSummary]:
        self.projects_root.mkdir(parents=True, exist_ok=True)
        projects: list[ProjectSummary] = []
        for directory in sorted(self.projects_root.iterdir()):
            if not directory.is_dir():
                continue
            payload = self._read_metadata(directory)
            if payload is None:
                continue
            projects.append(self._project_summary(directory, payload))
        projects.sort(key=lambda item: item.updated_at, reverse=True)
        return projects

    def create_project(self, payload: ProjectCreateRequest) -> ProjectSummary:
        self.projects_root.mkdir(parents=True, exist_ok=True)
        resolved_name = payload.name.strip() or self._next_default_project_name()
        project_id = self._unique_project_id(resolved_name)
        project_dir = self.projects_root / project_id
        for relative in ("pdfs", "derived", "indexes", "exports", "notes"):
            (project_dir / relative).mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
        metadata = {
            "id": project_id,
            "name": resolved_name,
            "description": payload.description.strip(),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        (project_dir / "project.json").write_text(
            json.dumps(metadata, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        return ProjectSummary(
            id=project_id,
            name=metadata["name"],
            description=metadata["description"],
            created_at=timestamp,
            updated_at=timestamp,
            pdf_count=0,
            note_count=0,
            project_path=str(project_dir),
        )

    def get_project(self, project_id: str) -> ProjectSummary | None:
        directory = self.projects_root / project_id
        payload = self._read_metadata(directory)
        if payload is None:
            return None
        return self._project_summary(directory, payload)

    def get_project_state(self, project_id: str) -> ProjectStatePayload | None:
        directory = self.projects_root / project_id
        payload = self._read_metadata(directory)
        if payload is None:
            return None
        return self._read_state(directory)

    def save_project_state(self, project_id: str, payload: ProjectStatePayload) -> ProjectStatePayload | None:
        directory = self.projects_root / project_id
        metadata = self._read_metadata(directory)
        if metadata is None:
            return None
        state_path = directory / "state.json"
        state_path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        metadata["updated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
        (directory / "project.json").write_text(
            json.dumps(metadata, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        return self._read_state(directory)

    def list_project_downloads(self, project_id: str) -> list[ProjectDownloadItem] | None:
        directory = self.projects_root / project_id
        payload = self._read_metadata(directory)
        if payload is None:
            return None
        download_dir = directory / "pdfs"
        download_dir.mkdir(parents=True, exist_ok=True)
        items: list[ProjectDownloadItem] = []
        entries = sorted(
            (item for item in download_dir.rglob("*.pdf") if item.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for entry in entries:
            stat = entry.stat()
            items.append(
                ProjectDownloadItem(
                    name=entry.name,
                    path=str(entry),
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, UTC).replace(microsecond=0).isoformat(),
                )
            )
        return items

    def update_project(self, project_id: str, payload: ProjectUpdateRequest) -> ProjectSummary | None:
        directory = self.projects_root / project_id
        current = self._read_metadata(directory)
        if current is None:
            return None

        next_name = payload.name.strip()
        if not next_name:
            return None

        current["name"] = next_name
        current["updated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
        (directory / "project.json").write_text(
            json.dumps(current, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        return self._project_summary(directory, current)

    def touch_project(self, project_id: str) -> ProjectSummary | None:
        directory = self.projects_root / project_id
        current = self._read_metadata(directory)
        if current is None:
            return None
        current["updated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
        (directory / "project.json").write_text(
            json.dumps(current, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        return self._project_summary(directory, current)

    @staticmethod
    def _read_state(directory: Path) -> ProjectStatePayload:
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

    def _unique_project_id(self, name: str) -> str:
        base = self._slugify(name) or "project"
        candidate = base
        suffix = 2
        while (self.projects_root / candidate).exists():
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
    def _read_metadata(directory: Path) -> dict[str, Any] | None:
        metadata_path = directory / "project.json"
        if not directory.exists() or not directory.is_dir() or not metadata_path.exists():
            return None
        try:
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
        return normalized[:80]

    @staticmethod
    def _count_files(directory: Path, suffix: str) -> int:
        if not directory.exists():
            return 0
        return sum(1 for item in directory.rglob(f"*{suffix}") if item.is_file() and item.suffix.lower() == suffix)
