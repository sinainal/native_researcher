"""PubMed service tests."""

from __future__ import annotations

import asyncio

import httpx

from app.clients.ncbi import NcbiClient, build_pubmed_query
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
        <ArticleTitle>Article One</ArticleTitle>
        <Journal>
          <JournalIssue>
            <PubDate><Year>2024</Year><Month>Jan</Month></PubDate>
          </JournalIssue>
        </Journal>
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
        <ArticleTitle>Article Two</ArticleTitle>
        <Journal>
          <JournalIssue>
            <PubDate><Year>2023</Year></PubDate>
          </JournalIssue>
        </Journal>
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
                assert "free full text[sb]" in request.url.params["term"]
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
            payload = PubMedSearchRequest(
                query="ndm inhibitor",
                max_results=2,
                preferred_source="pubmed",
            )
            first = await service.search(payload)
            second = await service.search(payload)

        assert first.meta.cache_hit is False
        assert second.meta.cache_hit is True
        assert first.meta.oa_only is True
        assert len(first.articles) == 2
        assert first.articles[0].pmc_id == "PMC11"
        assert first.articles[1].doi == "10.1000/two"
        assert sum(path.endswith("/esearch.fcgi") for path in calls) == 1
        assert sum(path.endswith("/esummary.fcgi") for path in calls) == 0
        assert sum(path.endswith("/efetch.fcgi") for path in calls) == 1
        assert sum(path.endswith("/elink.fcgi") for path in calls) == 1

    asyncio.run(runner())


def test_build_pubmed_query_applies_oa_filter_only_once() -> None:
    assert build_pubmed_query("serotonin receptor", None, None, oa_only=True) == (
        "(serotonin receptor) AND free full text[sb]"
    )
    assert build_pubmed_query("serotonin receptor AND free full text[sb]", None, None, oa_only=True) == (
        "serotonin receptor AND free full text[sb]"
    )
    assert build_pubmed_query("serotonin receptor", 2020, 2024, oa_only=True) == (
        '(serotonin receptor) AND free full text[sb] AND ("2020/01/01"[Date - Publication] : '
        '"2024/12/31"[Date - Publication])'
    )


def test_pubmed_service_prefers_openalex_when_available() -> None:
    async def runner() -> None:
        settings = Settings(
            pubmed_requests_per_second=0,
            openalex_requests_per_second=0,
            europe_pmc_requests_per_second=0,
            download_root=Settings().download_root,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "api.openalex.org/works" in url:
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "id": "https://openalex.org/W1",
                                "display_name": "OpenAlex Article One",
                                "publication_year": 2025,
                                "publication_date": "2025-01-02",
                                "doi": "https://doi.org/10.1000/openalex-one",
                                "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/10101/"},
                                "primary_location": {
                                    "landing_page_url": "https://example.org/one",
                                    "source": {
                                        "display_name": "Nature Communications",
                                    },
                                },
                                "authorships": [
                                    {"author": {"display_name": "Jane Doe"}},
                                ],
                                "cited_by_count": 55,
                                "type": "journal-article",
                                "primary_topic": {
                                    "display_name": "Computational Drug Discovery Methods",
                                },
                                "topics": [
                                    {"display_name": "Computational Drug Discovery Methods"},
                                    {"display_name": "Virtual Screening"},
                                    {"display_name": "Protein-Ligand Docking"},
                                ],
                                "related_works": [
                                    "https://openalex.org/W123",
                                    "https://openalex.org/W456",
                                ],
                                "referenced_works_count": 12,
                            },
                            {
                                "id": "https://openalex.org/W2",
                                "display_name": "OpenAlex Article Two",
                                "publication_year": 2024,
                                "publication_date": "2024-03-01",
                                "doi": "10.1000/openalex-two",
                                "ids": {},
                                "primary_location": {
                                    "landing_page_url": "https://example.org/two",
                                    "source": {"display_name": "Frontiers in Pharmacology"},
                                },
                                "authorships": [],
                                "cited_by_count": 8,
                                "type": "journal-article",
                                "referenced_works_count": 3,
                            },
                        ]
                    },
                )
            raise AssertionError(f"Unexpected URL: {url}")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        ) as ncbi_client, httpx.AsyncClient(transport=transport) as search_client:
            service = PubMedService(
                client=NcbiClient(ncbi_client, settings),
                cache=TTLCache(ttl_seconds=60, max_entries=8),
                http_client=search_client,
                settings=settings,
            )
            payload = PubMedSearchRequest(query="molecular docking", max_results=2)
            result = await service.search(payload)

        assert result.meta.primary_source == "openalex"
        assert result.meta.sources_used == ["openalex"]
        assert result.meta.fallback_used is False
        assert len(result.articles) == 2
        assert result.articles[0].title == "OpenAlex Article One"
        assert result.articles[0].citation_count == 55
        assert result.articles[0].pmid == "10101"
        assert result.articles[0].doi == "10.1000/openalex-one"
        assert result.articles[0].mesh_terms == ["Computational Drug Discovery Methods"]
        assert result.articles[0].keywords == ["Virtual Screening", "Protein-Ligand Docking"]
        assert result.articles[0].related_articles == ["W123", "W456"]

    asyncio.run(runner())


def test_pubmed_service_returns_openalex_only_when_preferred() -> None:
    async def runner() -> None:
        settings = Settings(
            pubmed_requests_per_second=0,
            openalex_requests_per_second=0,
            europe_pmc_requests_per_second=0,
            download_root=Settings().download_root,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "api.openalex.org/works" in url:
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "id": "https://openalex.org/W1",
                                "display_name": "Shared Article",
                                "publication_year": 2025,
                                "publication_date": "2025-01-02",
                                "doi": "10.1000/shared",
                                "ids": {},
                                "primary_location": {
                                    "landing_page_url": "https://example.org/shared",
                                    "source": {"display_name": "Test Journal"},
                                },
                                "authorships": [],
                                "cited_by_count": 10,
                                "type": "journal-article",
                                "referenced_works_count": 4,
                            }
                        ]
                    },
                )
            if request.url.path.endswith("/esearch.fcgi"):
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
            if request.url.path.endswith("/efetch.fcgi"):
                return httpx.Response(200, text=PUBMED_XML)
            if request.url.path.endswith("/elink.fcgi"):
                return httpx.Response(200, text="<?xml version='1.0'?><eLinkResult></eLinkResult>")
            raise AssertionError(f"Unexpected URL: {url}")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        ) as ncbi_client, httpx.AsyncClient(transport=transport) as search_client:
            service = PubMedService(
                client=NcbiClient(ncbi_client, settings),
                cache=TTLCache(ttl_seconds=60, max_entries=8),
                http_client=search_client,
                settings=settings,
            )
            payload = PubMedSearchRequest(query="ndm inhibitor", max_results=2)
            result = await service.search(payload)

        assert result.meta.primary_source == "openalex"
        assert result.meta.fallback_used is False
        assert result.meta.sources_used == ["openalex"]
        assert len(result.articles) == 1
        assert any(article.doi == "10.1000/shared" for article in result.articles)

    asyncio.run(runner())


def test_pubmed_service_returns_empty_when_openalex_returns_nothing() -> None:
    async def runner() -> None:
        settings = Settings(
            pubmed_requests_per_second=0,
            openalex_requests_per_second=0,
            europe_pmc_requests_per_second=0,
            download_root=Settings().download_root,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "api.openalex.org/works" in url:
                return httpx.Response(200, json={"results": []})
            if request.url.path.endswith("/esearch.fcgi"):
                return httpx.Response(
                    200,
                    json={"esearchresult": {"count": "2", "querykey": "1", "webenv": "abc"}},
                )
            if request.url.path.endswith("/efetch.fcgi"):
                return httpx.Response(200, text=PUBMED_XML)
            if request.url.path.endswith("/elink.fcgi"):
                return httpx.Response(200, text="<?xml version='1.0'?><eLinkResult></eLinkResult>")
            raise AssertionError(f"Unexpected URL: {url}")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        ) as ncbi_client, httpx.AsyncClient(transport=transport) as search_client:
            service = PubMedService(
                client=NcbiClient(ncbi_client, settings),
                cache=TTLCache(ttl_seconds=60, max_entries=8),
                http_client=search_client,
                settings=settings,
            )
            result = await service.search(PubMedSearchRequest(query="ndm inhibitor", max_results=2))

        assert result.meta.primary_source == "openalex"
        assert result.meta.sources_used == ["openalex"]
        assert result.meta.fallback_used is False
        assert len(result.articles) == 0

    asyncio.run(runner())


def test_pubmed_service_respects_preferred_pubmed_source() -> None:
    async def runner() -> None:
        settings = Settings(
            pubmed_requests_per_second=0,
            openalex_requests_per_second=0,
            europe_pmc_requests_per_second=0,
            download_root=Settings().download_root,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if "api.openalex.org/works" in str(request.url):
                raise AssertionError("OpenAlex should not be called when PubMed already satisfies the request.")
            if request.url.path.endswith("/esearch.fcgi"):
                return httpx.Response(
                    200,
                    json={"esearchresult": {"count": "2", "querykey": "1", "webenv": "abc"}},
                )
            if request.url.path.endswith("/efetch.fcgi"):
                return httpx.Response(200, text=PUBMED_XML)
            if request.url.path.endswith("/elink.fcgi"):
                return httpx.Response(200, text="<?xml version='1.0'?><eLinkResult></eLinkResult>")
            raise AssertionError(f"Unexpected URL: {request.url}")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        ) as ncbi_client, httpx.AsyncClient(transport=transport) as search_client:
            service = PubMedService(
                client=NcbiClient(ncbi_client, settings),
                cache=TTLCache(ttl_seconds=60, max_entries=8),
                http_client=search_client,
                settings=settings,
            )
            result = await service.search(
                PubMedSearchRequest(
                    query="ndm inhibitor",
                    max_results=2,
                    preferred_source="pubmed",
                )
            )

        assert result.meta.primary_source == "pubmed"
        assert result.meta.sources_used == ["pubmed"]
        assert result.meta.fallback_used is False
        assert len(result.articles) == 2

    asyncio.run(runner())
