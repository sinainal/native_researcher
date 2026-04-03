"""Journal metrics bootstrap tests."""

from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path

import httpx
import pandas as pd

from app.core.config import Settings
from app.schemas.article import Article
from app.services.journal_metrics_service import JournalMetricsService
from app.services.workspace_db import WorkspaceDatabase


def test_journal_metrics_bootstrap_and_lookup() -> None:
    async def runner() -> None:
        dataframe = pd.DataFrame(
            [
                {
                    "Rank": 1,
                    "Sourceid": 123,
                    "Title": "Nature Communications",
                    "Type": "journal",
                    "Issn": "20411723, 20411731",
                    "SJR": 5.123,
                    "SJR Best Quartile": "Q1",
                    "Total Docs. (2023)": 1000,
                    "Categories": "Multidisciplinary (Q1)",
                    "Areas": "Multidisciplinary",
                },
                {
                    "Rank": 2,
                    "Sourceid": 456,
                    "Title": "Example Journal",
                    "Type": "journal",
                    "Issn": "11112222",
                    "SJR": 0.45,
                    "SJR Best Quartile": "Q3",
                    "Total Docs. (2023)": 100,
                    "Categories": "Example Category (Q3)",
                    "Areas": "Medicine",
                },
            ]
        )
        buffer = io.BytesIO()
        dataframe.to_excel(buffer, index=False)
        payload = buffer.getvalue()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=payload,
                headers={
                    "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                },
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir)
            db = WorkspaceDatabase(workspace_root / ".native_researcher.db")
            settings = Settings(
                download_root=Settings().download_root,
                workspace_root=workspace_root,
                journal_metrics_bootstrap_url="https://example.test/scimago.xlsx",
            )
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                service = JournalMetricsService(db, settings, http_client=client)
                await service.ensure_bootstrap()

            article = Article(
                id=1,
                pmid="1",
                title="Demo",
                journal="Nature Communications",
                issn_l="20411723",
                issns=["20411731"],
            )
            service.enrich_articles([article])

            assert article.journal_quartile == "Q1"
            assert article.journal_metric_year == 2023
            assert article.journal_sjr == 5.123
            assert article.journal_metrics_source == "scimago_sjr_2023_zenodo"

    asyncio.run(runner())
