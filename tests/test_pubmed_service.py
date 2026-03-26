"""PubMed service tests."""

from __future__ import annotations

import asyncio

import httpx

from app.clients.ncbi import NcbiClient
from app.core.config import Settings
from app.schemas.pubmed import PubMedSearchRequest
from app.services.pubmed_service import PubMedService
from app.utils.cache import TTLCache


PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>11</PMID>
      <Article>
        <Abstract>
          <AbstractText>Abstract one.</AbstractText>
        </Abstract>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1000/one</ArticleId>
        <ArticleId IdType="pmc">PMC11</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>22</PMID>
      <Article>
        <Abstract>
          <AbstractText Label="RESULTS">Abstract two.</AbstractText>
        </Abstract>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.1000/two</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


def test_pubmed_service_uses_cache_and_history() -> None:
    async def runner() -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path.endswith("/esearch.fcgi"):
                assert request.url.params["usehistory"] == "y"
                return httpx.Response(
                    200,
                    json={
                        "esearchresult": {
                            "count": "2",
                            "querykey": "1",
                            "webenv": "abc",
                        }
                    },
                )
            if request.url.path.endswith("/esummary.fcgi"):
                return httpx.Response(
                    200,
                    json={
                        "result": {
                            "uids": ["11", "22"],
                            "11": {"uid": "11", "title": "Article One", "pubdate": "2024 Jan"},
                            "22": {"uid": "22", "title": "Article Two", "pubdate": "2023"},
                        }
                    },
                )
            if request.url.path.endswith("/efetch.fcgi"):
                return httpx.Response(200, text=PUBMED_XML)
            if request.url.path.endswith("/elink.fcgi"):
                return httpx.Response(200, text="<?xml version='1.0'?><eLinkResult></eLinkResult>")
            raise AssertionError(f"Unexpected path: {request.url.path}")

        settings = Settings(pubmed_requests_per_second=0, download_root=Settings().download_root)
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        ) as client:
            service = PubMedService(
                client=NcbiClient(client, settings),
                cache=TTLCache(ttl_seconds=60, max_entries=8),
            )
            payload = PubMedSearchRequest(query="ndm inhibitor", max_results=2)
            first = await service.search(payload)
            second = await service.search(payload)

        assert first.meta.cache_hit is False
        assert second.meta.cache_hit is True
        assert len(first.articles) == 2
        assert first.articles[0].pmc_id == "PMC11"
        assert first.articles[1].doi == "10.1000/two"
        assert sum(path.endswith("/esearch.fcgi") for path in calls) == 1
        assert sum(path.endswith("/esummary.fcgi") for path in calls) == 1
        assert sum(path.endswith("/efetch.fcgi") for path in calls) == 1
        assert sum(path.endswith("/elink.fcgi") for path in calls) == 1

    asyncio.run(runner())
