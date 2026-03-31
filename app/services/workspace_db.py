"""SQLite workspace database primitives."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class WorkspaceDatabase:
    """Small SQLite wrapper for local workspace state."""

    SCHEMA_VERSION = 3

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def fetchone(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        with self.transaction() as conn:
            conn.execute(sql, params)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._open_connection()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._open_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -20000")
        return conn

    def _ensure_schema(self) -> None:
        with self.transaction() as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version >= self.SCHEMA_VERSION:
                return

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    project_path TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_projects_updated_at
                    ON projects(updated_at DESC);

                CREATE TABLE IF NOT EXISTS project_state (
                    project_id TEXT PRIMARY KEY
                        REFERENCES projects(id) ON DELETE CASCADE,
                    active_query_id TEXT,
                    selected_ids_json TEXT NOT NULL DEFAULT '[]',
                    detail_article_id INTEGER,
                    sidebar_panel TEXT NOT NULL DEFAULT 'queries',
                    query_detail_id TEXT,
                    downloadability_cache_json TEXT NOT NULL DEFAULT '{}',
                    current_session_id TEXT,
                    assistant_sessions_json TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_queries (
                    project_id TEXT NOT NULL
                        REFERENCES projects(id) ON DELETE CASCADE,
                    query_id TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    search_payload_json TEXT NOT NULL,
                    meta_json TEXT,
                    articles_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (project_id, query_id)
                );

                CREATE INDEX IF NOT EXISTS idx_project_queries_order
                    ON project_queries(project_id, position, updated_at DESC);

                CREATE TABLE IF NOT EXISTS project_documents (
                    project_id TEXT NOT NULL
                        REFERENCES projects(id) ON DELETE CASCADE,
                    relative_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    modified_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, relative_path)
                );

                CREATE INDEX IF NOT EXISTS idx_project_documents_updated
                    ON project_documents(project_id, updated_at DESC);
                """
            )
            if version < 2:
                for statement in (
                    "ALTER TABLE project_state ADD COLUMN current_session_id TEXT",
                    "ALTER TABLE project_state ADD COLUMN assistant_sessions_json TEXT NOT NULL DEFAULT '[]'",
                ):
                    try:
                        conn.execute(statement)
                    except sqlite3.OperationalError:
                        pass
            if version < 3:
                for statement in (
                    "ALTER TABLE project_state ADD COLUMN downloadability_cache_json TEXT NOT NULL DEFAULT '{}'",
                ):
                    try:
                        conn.execute(statement)
                    except sqlite3.OperationalError:
                        pass
            conn.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
