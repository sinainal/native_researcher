# OA Retrieval Research

Date: 2026-03-21

## Goal

Find the fastest legal/open-source-friendly way to retrieve open scholarly full text for our `Researcher_2` pipeline, with a target like:

- around 20 papers in under ~50 seconds
- around 80% success on truly reachable OA/full-text items

This document focuses on:

- where open full texts are actually served from
- what official services exist
- which open-source repos already solve parts of this problem
- what retrieval order makes sense before any browser fallback

## What the web says

### 1. PMC is the primary machine-friendly source

PMC's OA services are the cleanest path when a PMCID exists.

- The PMC OA Web Service explicitly says it can discover downloadable OA resources and that files are available as `tgz`, and sometimes as `PDF`.
- The PMC FTP/Cloud docs say:
  - individual article packages are available for the PMC Open Access Subset
  - those packages include XML, PDF if present, media, and supplementary files
  - individual PDFs are only available for certain licensed articles
- PMC ID Converter provides DOI/PMID/PMCID mapping and supports up to 200 IDs per call.

Operational meaning:

- do not guess PMC paths from HTML pages
- resolve PMCID first
- then hit PMC OA service / file lists
- prefer article package or explicit PDF path returned by the official service

### 2. Europe PMC separates "free to read" from reusable OA content

Europe PMC is useful in two different ways:

- it exposes an OA subset downloadable via web services / FTP
- it also tracks "free and legal" copies even when the full text is not hosted inside Europe PMC

Important distinction from the docs:

- "Full text in Europe PMC" means readable within Europe PMC
- "Link to free full text" means a legal external full-text copy
- only the open access subset is the clean bulk-download target

Operational meaning:

- Europe PMC is both a discovery layer and an OA/full-text source
- it is a better filter than naive PubMed `free full text[sb]`

### 3. Unpaywall is a discovery graph, not just a single link

Unpaywall's model is closer to what we need than raw DOI landing pages.

- It treats an OA location as a place where full text is freely available directly, via PDF link, or through an embedded reader.
- It explicitly excludes low-machine-usability cases like login-required or CAPTCHA-heavy locations.
- The `best_oa_location` / `url_for_pdf` / list-of-links pattern is exactly the right model for a downloader.

Operational meaning:

- Unpaywall should be a first-class discovery source
- not just one fallback query
- and not only one URL; the full location list matters

### 4. OpenAlex is now a serious full-text signal layer

OpenAlex is not just metadata anymore.

- `best_oa_location` and `locations` expose where copies live
- `has_content.pdf` and `content_url` are especially important
- docs state that about 60M works have downloadable PDF content cached by OpenAlex
- `open_access.any_repository_has_fulltext` helps surface "green OA" that may not be the publisher copy

Operational meaning:

- OpenAlex should be used before any browser stage
- especially as a fast filter for likely downloadable content

### 5. Crossref helps, but it is not enough

Crossref docs are explicit:

- they provide metadata and full-text URL metadata for TDM use cases
- but this is still metadata
- availability and usability depend on publisher side permissions and endpoints

Operational meaning:

- Crossref is useful for links and TDM endpoints
- but should not be treated as "guaranteed downloadable OA PDF"

## Why "open article" still does not mean "easy PDF"

The official docs align with what we saw in our own runs:

- some articles are free to read but only as HTML
- some are in PMC but not in the OA subset in the way we need
- some expose legal free copies but not a direct PDF
- some are legal to read but not machine-friendly to bulk download from a browser context

This is not just a tooling bug. The ecosystem itself is split across:

- OA package / FTP style delivery
- direct PDF delivery
- landing page delivery
- publisher TDM endpoints
- repository mirrors

## Open-source repos worth studying

### 1. `kermitt2/biblio_glutton_harvester`

Local clone:

- [biblio_glutton_harvester](/home/sina/Downloads/Researcher/Researcher_2/scrape_test/repos/biblio_glutton_harvester)

Repo:

- https://github.com/kermitt2/biblio_glutton_harvester

Why it matters:

- It is the closest repo to our exact problem.
- It harvests OA PDFs/XML at scale from Unpaywall and PMC.
- It is designed for millions of full texts, not toy scripts.

What it does from code inspection:

- input sources:
  - Unpaywall snapshot
  - PMC file lists
- selection logic:
  - if configured, prioritize PMC over publisher PDFs
  - if arXiv mirror exists, prioritize arXiv
  - if PLOS mirror exists, prioritize PLOS
  - otherwise use `best_oa_location`
  - keep `alternative_oa_locations` for retry
  - optionally skip IEEE entirely
- download logic:
  - try FTP / `wget` for FTP-style resources
  - optional `cloudscraper` for Cloudflare sites
  - then `requests`
  - then `wget`
  - then alternative OA locations
- concurrency:
  - batch processing
  - thread pool for downloading
  - thread pool again for post-processing
- validation:
  - validates downloaded PDFs/XML
  - removes invalid files

Most important insight:

- It does not lead with browser automation.
- It leads with structured OA sources plus alternative OA URLs.
- It prefers PMC and repository/mirror paths when available.

### 2. `ourresearch/oadoi`

Repo:

- https://github.com/ourresearch/oadoi

Why it matters:

- This is the backend behind Unpaywall.
- It is a blueprint for how a serious OA discovery system is decomposed.

From repo structure:

- dedicated modules for PMC (`oa_pmc.py`)
- page handling (`oa_page.py`)
- PDF URL logic (`pdf_url.py`)
- repository requests (`repo_request.py`)
- green OA scraping queues (`queue_green_oa_scrape.py`)
- PDF URL checking queues (`queue_pdf_url_check.py`)
- PubMed ingest (`load_pubmed_baseline_files.py`, `load_pubmed_update_files.py`)

Most important insight:

- production-grade OA retrieval is not a single downloader
- it is a pipeline:
  - ingest identifiers
  - map sources
  - discover repository copies
  - validate PDF URLs
  - rescrape missing items

### 3. `unpywall/unpywall`

Repo:

- https://github.com/unpywall/unpywall

Why it matters:

- Very small, useful Python client over Unpaywall
- Fastest way to integrate `best_oa_location`, `get_pdf_link`, `get_all_links`

What it exposes:

- DOI lookup
- text query
- `get_pdf_link`
- `get_doc_link`
- `get_all_links`
- CLI download mode

Most important insight:

- This is the lightest-weight discovery layer we can borrow ideas from immediately.
- It is not a full harvester, but it is a clean DOI -> OA location adapter.

### 4. `olivettigroup/article-downloader`

Repo:

- https://github.com/olivettigroup/article-downloader

Why it matters:

- Shows the publisher-API route clearly.
- It is explicit that it uses publisher-approved APIs and needs keys/permissions.

What it is good for:

- Elsevier or other publisher API integrations
- text-mining workflows where the user already has access

Why it is not our core open-source default:

- It does not solve general OA/full-text discovery by itself.
- It depends on publisher permissions.

### 5. `neuroquery/pubget`

Repo:

- https://github.com/neuroquery/pubget

Why it matters:

- Very clean example of "PMC OA subset first" design.
- Downloads articles in bulk from PMC only and extracts text/metadata.

Most important insight:

- This repo avoids most browser and publisher complexity by narrowing the problem to the PMC OA subset.
- That is exactly why it is simpler and faster.

### 6. `tiadams/pmc-downloader`

Repo:

- https://github.com/tiadams/pmc-downloader

Why it matters:

- Minimal shell-based PMCID -> PMC OA archive downloader
- Good reference for the pure PMC-only happy path

What it does:

- download index file from PMC
- check ID availability
- download sources from PMC FTP
- extract archive
- rename PDF/XML

### 7. `arundasan91/pubmed_pdf_downloader`

Repo:

- https://github.com/arundasan91/pubmed_pdf_downloader

Why it matters:

- Another small PMCID-based downloader
- Useful as a minimal PMC-only command-line approach

Limitation:

- still batch-delay oriented
- much narrower than what we need

## The pattern that shows up repeatedly

The best repos do **not** do this:

- DOI -> publisher page -> browser -> scrape everything

The better pattern is:

1. Resolve strong identifiers
2. Prefer PMC/Open Access subset sources
3. Use OA-location services like Unpaywall/OpenAlex
4. Try alternative legal OA locations
5. Only then touch publisher-specific logic

## Practical source order for `Researcher_2`

If the goal is speed first and legal/open-source-friendly behavior:

1. PMID/DOI -> PMCID mapping
   - PMC ID Converter
   - Europe PMC mapping files

2. PMCID present?
   - PMC OA Web Service
   - PMC OA file list / HTTPS file list
   - PMC article package / PDF if present

3. Europe PMC
   - OA subset search
   - "free and legal copy" signals
   - PMID/PMCID/DOI mapping file

4. Unpaywall
   - `best_oa_location`
   - all OA locations
   - repository copies

5. OpenAlex
   - `has_content.pdf`
   - `content_url`
   - `best_oa_location`
   - repository and publisher locations

6. Crossref
   - only as metadata / TDM link help

7. Optional publisher adapters
   - Elsevier / Wiley / ACS
   - only if user explicitly wants them or has credentials

8. Browser fallback
   - last resort only

## What this means for our current app

### What we should stop doing as the default

- treating browser fallback as the main recovery engine
- trusting DOI landing pages too early
- assuming `free full text[sb]` means machine-downloadable PDF

### What we should build next

#### Fast mode

- PMCID mapping
- PMC OA
- Europe PMC OA/free-legal
- Unpaywall
- OpenAlex
- no browser

Expected result:

- much lower latency
- lower recovery ceiling than deep browser mode
- likely best mode for interactive use

#### Balanced mode

- all of fast mode
- limited browser fallback only for high-value domains

Expected result:

- better success than fast mode
- still much faster than full browser recovery

#### Deep mode

- all of the above
- publisher/domain-specific browser or TDM adapters

Expected result:

- best success rate
- slowest
- should be opt-in

## Bottom line

There is a simpler way than "scrape harder":

- use PMC and Europe PMC as primary full-text infrastructure
- use Unpaywall and OpenAlex as OA discovery layers
- use Crossref as metadata assistance, not as truth
- copy the broad architecture of `biblio_glutton_harvester` and `oadoi`
- keep browser fallback as the exception, not the main path

That is the clearest route to:

- lower latency
- better legality/compliance
- cleaner open-source positioning

## Sources

- PMC OA Web Service: https://pmc.ncbi.nlm.nih.gov/tools/oa-service/
- PMC FTP / datasets: https://pmc.ncbi.nlm.nih.gov/tools/ftp/
- PMC ID Converter: https://pmc.ncbi.nlm.nih.gov/tools/id-converter-api
- Europe PMC open access downloads: https://europepmc.org/downloads/openaccess
- Europe PMC downloads: https://europepmc.org/downloads
- Europe PMC help: https://europepmc.org/help
- OpenAlex work object: https://docs.openalex.org/api-entities/works/work-object
- OpenAlex location object: https://docs.openalex.org/api-entities/works/work-object/location-object
- OpenAlex full-text PDFs: https://docs.openalex.org/download-all-data/full-text-pdfs
- Unpaywall FAQ on OA locations: https://support.unpaywall.org/support/solutions/articles/44002140100-what-counts-as-an-open-access-location-
- Crossref full-text access docs: https://www.crossref.org/documentation/retrieve-metadata/text-and-data-mining/
- biblio_glutton_harvester: https://github.com/kermitt2/biblio_glutton_harvester
- oadoi: https://github.com/ourresearch/oadoi
- unpywall: https://github.com/unpywall/unpywall
- article-downloader: https://github.com/olivettigroup/article-downloader
- pubget: https://github.com/neuroquery/pubget
- pmc-downloader: https://github.com/tiadams/pmc-downloader
- pubmed_pdf_downloader: https://github.com/arundasan91/pubmed_pdf_downloader
