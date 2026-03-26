"""Workspace project service."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.project import ProjectCreateRequest, ProjectSummary


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
            metadata_path = directory / "project.json"
            if not metadata_path.exists():
                continue
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            projects.append(
                ProjectSummary(
                    id=str(payload.get("id") or directory.name),
                    name=str(payload.get("name") or directory.name),
                    description=str(payload.get("description") or ""),
                    created_at=str(payload.get("created_at") or ""),
                    updated_at=str(payload.get("updated_at") or ""),
                    pdf_count=self._count_files(directory / "pdfs", ".pdf"),
                    note_count=self._count_files(directory / "notes", ".md"),
                    project_path=str(directory),
                )
            )
        projects.sort(key=lambda item: item.updated_at, reverse=True)
        return projects

    def create_project(self, payload: ProjectCreateRequest) -> ProjectSummary:
        self.projects_root.mkdir(parents=True, exist_ok=True)
        project_id = self._unique_project_id(payload.name)
        project_dir = self.projects_root / project_id
        for relative in ("pdfs", "derived", "indexes", "exports", "notes"):
            (project_dir / relative).mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
        metadata = {
            "id": project_id,
            "name": payload.name.strip(),
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

    def _unique_project_id(self, name: str) -> str:
        base = self._slugify(name) or "project"
        candidate = base
        suffix = 2
        while (self.projects_root / candidate).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
        return normalized[:80]

    @staticmethod
    def _count_files(directory: Path, suffix: str) -> int:
        if not directory.exists():
            return 0
        return sum(1 for item in directory.iterdir() if item.is_file() and item.suffix.lower() == suffix)

