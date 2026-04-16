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
        assert result.articles[0].source_name == "openalex"
        assert result.articles[0].source_record_id == "W1"
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


def test_pubmed_service_supports_europe_pmc_search() -> None:
    async def runner() -> None:
        settings = Settings(
            pubmed_requests_per_second=0,
            openalex_requests_per_second=0,
            europe_pmc_requests_per_second=0,
            download_root=Settings().download_root,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(
                    200,
                    json={
                        "resultList": {
                            "result": [
                                {
                                    "pmid": "777",
                                    "pmcid": "PMC777",
                                    "doi": "10.1000/epmc",
                                    "title": "Europe PMC Article",
                                    "journalTitle": "EPMC Journal",
                                    "pubYear": "2024",
                                    "abstractText": "Abstract",
                                    "authorString": "Jane Doe, John Roe",
                                    "citedByCount": 12,
                                    "fullTextUrlList": {
                                        "fullTextUrl": [
                                            {"url": "https://example.org/epmc.pdf", "documentStyle": "pdf"}
                                        ]
                                    },
                                }
                            ]
                        }
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
            result = await service.search(
                PubMedSearchRequest(query="docking", max_results=1, preferred_source="europe_pmc")
            )

        assert result.meta.primary_source == "europe_pmc"
        assert result.articles[0].source_name == "europe_pmc"
        assert result.articles[0].pmc_id == "PMC777"
        assert result.articles[0].oa_pdf_url == "https://example.org/epmc.pdf"

    asyncio.run(runner())


def test_pubmed_service_supports_pmc_search() -> None:
    async def runner() -> None:
        settings = Settings(
            pubmed_requests_per_second=0,
            openalex_requests_per_second=0,
            europe_pmc_requests_per_second=0,
            download_root=Settings().download_root,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/esearch.fcgi"):
                assert request.url.params["db"] == "pmc"
                return httpx.Response(200, json={"esearchresult": {"idlist": ["12345"]}})
            if request.url.path.endswith("/efetch.fcgi"):
                return httpx.Response(
                    200,
                    text=(
                        "<?xml version='1.0'?><pmc-articleset>"
                        "<article>"
                        "<front><journal-meta><journal-title-group><journal-title>PMC Journal</journal-title></journal-title-group></journal-meta>"
                        "<article-meta>"
                        "<article-id pub-id-type='pmc'>PMC12345</article-id>"
                        "<article-id pub-id-type='doi'>10.1000/pmc</article-id>"
                        "<article-title>PMC Search Article</article-title>"
                        "<pub-date><year>2023</year></pub-date>"
                        "<abstract><p>PMC abstract.</p></abstract>"
                        "</article-meta></front>"
                        "</article>"
                        "</pmc-articleset>"
                    ),
                )
            raise AssertionError(f"Unexpected path: {request.url.path}")

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
                PubMedSearchRequest(query="docking", max_results=1, preferred_source="pmc")
            )

        assert result.meta.primary_source == "pmc"
        assert result.articles[0].source_name == "pmc"
        assert result.articles[0].source_record_id == "PMC12345"
        assert result.articles[0].pmc_id == "PMC12345"
        assert result.articles[0].doi == "10.1000/pmc"

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
        assert result.articles[0].source_name == "pubmed"
        assert result.articles[0].source_record_id == "11"

    asyncio.run(runner())


def test_pubmed_service_supports_core_search() -> None:
    async def runner() -> None:
        settings = Settings(
            pubmed_requests_per_second=0,
            openalex_requests_per_second=0,
            europe_pmc_requests_per_second=0,
            core_requests_per_second=0,
            core_api_key="core-test",
            download_root=Settings().download_root,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if "api.core.ac.uk/v3/search/works" in str(request.url):
                assert request.headers["Authorization"] == "core-test"
                query = str(request.url.params.get("q") or "")
                assert "yearPublished:" in query
                assert "fullText:true" in query
                return httpx.Response(
                    200,
                    json={
                        "totalHits": 1,
                        "results": [
                            {
                                "id": 445566,
                                "doi": "https://doi.org/10.1000/core-native",
                                "title": "CORE Native Article",
                                "abstract": "Repository abstract.",
                                "yearPublished": 2024,
                                "publishedDate": "2024-03-04",
                                "authors": [{"name": "Jane Doe"}],
                                "pubmedId": 998877,
                                "downloadUrl": "https://core.ac.uk/download/pdf/445566.pdf",
                                "sourceFulltextUrls": ["https://repository.example.org/items/445566"],
                                "links": [
                                    {"type": "display", "url": "https://core.ac.uk/works/445566"},
                                    {"type": "reader", "url": "https://core.ac.uk/reader/445566"},
                                ],
                                "journals": [{"title": "Repository Journal", "identifiers": ["1234-5678"]}],
                                "documentType": ["research-article"],
                                "citationCount": 19,
                                "topics": [{"name": "Docking"}],
                            }
                        ],
                    },
                )
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
                PubMedSearchRequest(query="docking", max_results=1, preferred_source="core", year_start=2022, year_end=2026)
            )

        assert result.meta.primary_source == "core"
        assert result.meta.request_count == 1
        assert result.articles[0].source_name == "core"
        assert result.articles[0].source_record_id == "445566"
        assert result.articles[0].journal == "Repository Journal"
        assert result.articles[0].pmid == "998877"
        assert result.articles[0].oa_pdf_url == "https://core.ac.uk/download/pdf/445566.pdf"
        assert result.articles[0].landing_page_url == "https://core.ac.uk/works/445566"
        assert result.articles[0].article_type == "research-article"
        assert result.articles[0].issns == ["1234-5678"]

    asyncio.run(runner())


def test_pubmed_service_uses_core_year_query_to_fill_recent_results() -> None:
    async def runner() -> None:
        settings = Settings(
            pubmed_requests_per_second=0,
            openalex_requests_per_second=0,
            europe_pmc_requests_per_second=0,
            core_requests_per_second=0,
            core_api_key="core-test",
            download_root=Settings().download_root,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if "api.core.ac.uk/v3/search/works" not in str(request.url):
                raise AssertionError(f"Unexpected URL: {request.url}")
            query = str(request.url.params.get("q") or "")
            assert "yearPublished:2024" in query
            assert "yearPublished:2023" in query
            assert "yearPublished:2022" in query
            assert "fullText:true" in query
            return httpx.Response(
                200,
                json={
                    "totalHits": 120,
                    "results": [
                        {
                            "id": 2,
                            "title": "Recent docking paper",
                            "yearPublished": 2024,
                            "publishedDate": "2024-01-01",
                            "downloadUrl": "https://core.ac.uk/download/recent.pdf",
                        }
                    ],
                },
            )

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
                    query="docking",
                    max_results=1,
                    year_start=2022,
                    year_end=2026,
                    preferred_source="core",
                )
            )

        assert result.meta.primary_source == "core"
        assert result.meta.request_count == 1
        assert len(result.articles) == 1
        assert result.articles[0].title == "Recent docking paper"
        assert result.articles[0].year == "2024"

    asyncio.run(runner())


def test_pubmed_service_supports_arxiv_search() -> None:
    async def runner() -> None:
        settings = Settings(
            pubmed_requests_per_second=0,
            openalex_requests_per_second=0,
            europe_pmc_requests_per_second=0,
            arxiv_requests_per_second=0,
            download_root=Settings().download_root,
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if "export.arxiv.org/api/query" in str(request.url):
                return httpx.Response(
                    200,
                    text=(
                        "<?xml version='1.0' encoding='UTF-8'?>"
                        "<feed xmlns='http://www.w3.org/2005/Atom' "
                        "xmlns:opensearch='http://a9.com/-/spec/opensearch/1.1/' "
                        "xmlns:arxiv='http://arxiv.org/schemas/atom'>"
                        "<opensearch:totalResults>1</opensearch:totalResults>"
                        "<entry>"
                        "<id>https://arxiv.org/abs/2401.12345v1</id>"
                        "<updated>2024-01-03T00:00:00Z</updated>"
                        "<published>2024-01-02T00:00:00Z</published>"
                        "<title>  arXiv Native   Article </title>"
                        "<summary>  Preprint abstract. </summary>"
                        "<author><name>Jane Doe</name></author>"
                        "<link href='https://arxiv.org/abs/2401.12345v1' rel='alternate' type='text/html'/>"
                        "<link href='https://arxiv.org/pdf/2401.12345v1' rel='related' type='application/pdf'/>"
                        "<arxiv:doi>10.1000/arxiv-native</arxiv:doi>"
                        "<arxiv:journal_ref>Journal Ref</arxiv:journal_ref>"
                        "<category term='cs.LG'/>"
                        "<category term='q-bio.BM'/>"
                        "<arxiv:primary_category term='cs.LG'/>"
                        "</entry>"
                        "</feed>"
                    ),
                )
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
                PubMedSearchRequest(query="docking", max_results=1, preferred_source="arxiv")
            )

        assert result.meta.primary_source == "arxiv"
        assert result.articles[0].source_name == "arxiv"
        assert result.articles[0].source_record_id == "2401.12345v1"
        assert result.articles[0].oa_pdf_url == "https://arxiv.org/pdf/2401.12345v1"
        assert result.articles[0].landing_page_url == "https://arxiv.org/abs/2401.12345v1"
        assert result.articles[0].mesh_terms == ["cs.LG"]
        assert result.articles[0].keywords == ["cs.LG", "q-bio.BM"]
        assert result.articles[0].article_type == "preprint"

    asyncio.run(runner())


def test_pubmed_service_paginates_arxiv_until_recent_hits_fill_requested_count() -> None:
    async def runner() -> None:
        settings = Settings(
            pubmed_requests_per_second=0,
            openalex_requests_per_second=0,
            europe_pmc_requests_per_second=0,
            arxiv_requests_per_second=0,
            download_root=Settings().download_root,
        )

        def page(total: int, entries: list[tuple[str, str]]) -> str:
            rendered_entries = "".join(
                (
                    "<entry>"
                    f"<id>https://arxiv.org/abs/{record_id}</id>"
                    "<updated>2024-01-03T00:00:00Z</updated>"
                    f"<published>{published}</published>"
                    f"<title>{record_id}</title>"
                    "<summary>Abstract.</summary>"
                    f"<link href='https://arxiv.org/abs/{record_id}' rel='alternate' type='text/html'/>"
                    f"<link href='https://arxiv.org/pdf/{record_id}' rel='related' type='application/pdf'/>"
                    "</entry>"
                )
                for record_id, published in entries
            )
            return (
                "<?xml version='1.0' encoding='UTF-8'?>"
                "<feed xmlns='http://www.w3.org/2005/Atom' "
                "xmlns:opensearch='http://a9.com/-/spec/opensearch/1.1/' "
                "xmlns:arxiv='http://arxiv.org/schemas/atom'>"
                f"<opensearch:totalResults>{total}</opensearch:totalResults>"
                f"{rendered_entries}"
                "</feed>"
            )

        def handler(request: httpx.Request) -> httpx.Response:
            if "export.arxiv.org/api/query" not in str(request.url):
                raise AssertionError(f"Unexpected URL: {request.url}")
            assert request.url.params.get("sortBy") == "submittedDate"
            start = int(request.url.params.get("start", "0"))
            if start == 0:
                return httpx.Response(
                    200,
                    text=page(
                        50,
                        [(f"old-{index}v1", "2016-01-02T00:00:00Z") for index in range(25)],
                    ),
                )
            if start == 25:
                return httpx.Response(
                    200,
                    text=page(
                        50,
                        [("recent-1v1", "2024-01-02T00:00:00Z"), ("recent-2v1", "2023-01-02T00:00:00Z")]
                        + [(f"recent-pad-{index}v1", "2022-01-02T00:00:00Z") for index in range(23)],
                    ),
                )
            return httpx.Response(200, text=page(50, []))

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
                    query="graph neural networks",
                    max_results=2,
                    year_start=2022,
                    year_end=2026,
                    preferred_source="arxiv",
                )
            )

        assert result.meta.primary_source == "arxiv"
        assert result.meta.request_count == 2
        assert len(result.articles) == 2
        assert [article.source_record_id for article in result.articles] == ["recent-1v1", "recent-2v1"]

    asyncio.run(runner())
