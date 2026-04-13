import asyncio
import time
import re
from typing import Any
from pathlib import Path
from urllib.parse import urlparse
import httpx
from app.schemas.article import ArticleReference

class FinalMethodDownloader:
    def __init__(self, output_dir: Path, budget_seconds: float = 60.0):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.budget_seconds = min(budget_seconds, 60.0) 
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=3.0, read=15.0, write=5.0, pool=5.0),
            headers={"User-Agent": "NativeResearcher FinalMethod/1.0", "Accept": "application/pdf, text/html, */*"},
            follow_redirects=True,
            verify=False
        )
        self.attempts = []
        
    async def close(self):
        await self.client.aclose()
        
    def _log_attempt(self, step: str, source: str, status: str, started: float, url: str=None, detail: str=None):
        elapsed = int((time.perf_counter() - started) * 1000)
        self.attempts.append({
            "step": step,
            "source": source,
            "status": status,
            "elapsed_ms": elapsed,
            "url": url,
            "detail": detail
        })
        
    async def _safe_get_json(self, url: str) -> dict:
        started = time.perf_counter()
        source = urlparse(url).netloc
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()
            self._log_attempt("metadata", source, "ok", started, url, f"status={resp.status_code}")
            return data
        except Exception as e:
            self._log_attempt("metadata", source, "error", started, url, str(e))
            return {}

    async def get_candidates(self, article: ArticleReference) -> list[dict]:
        candidates = []
        tasks = []
        
        # 1. Unpaywall & OpenAlex
        if article.doi:
            unpaywall_url = f"https://api.unpaywall.org/v2/{article.doi}?email=bot@example.com"
            tasks.append(("unpaywall", self._safe_get_json(unpaywall_url)))
            
            openalex_url = f"https://api.openalex.org/works/https://doi.org/{article.doi}"
            tasks.append(("openalex", self._safe_get_json(openalex_url)))
            
        # 2. Europe PMC search
        epmc_queries = []
        if article.pmc_id: epmc_queries.append(f"PMCID:{article.pmc_id}")
        if article.doi: epmc_queries.append(f"DOI:\"{article.doi}\"")
        if article.pmid: epmc_queries.append(f"EXT_ID:{article.pmid}")
        
        if epmc_queries:
            query_str = " OR ".join(epmc_queries)
            epmc_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={query_str}&format=json&resultType=core"
            tasks.append(("europe_pmc", self._safe_get_json(epmc_url)))
            
        if tasks:
            results = await asyncio.gather(*(t[1] for t in tasks), return_exceptions=True)
            for (source_name, _), res in zip(tasks, results):
                if isinstance(res, Exception) or not res: continue
                
                if source_name == "unpaywall":
                    # Unpaywall usually lists all oa locations
                    oa_locs = res.get("oa_locations", [])
                    for loc in oa_locs:
                        url = loc.get("url_for_pdf") or loc.get("url")
                        if url: candidates.append({"source": "unpaywall", "url": url})
                
                elif source_name == "openalex":
                    oa_locs = res.get("locations", [])
                    for loc in oa_locs:
                        url = loc.get("pdf_url") or loc.get("landing_page_url")
                        if url: candidates.append({"source": "openalex", "url": url})
                
                elif source_name == "europe_pmc":
                    items = res.get("resultList", {}).get("result", [])
                    if items:
                        # Direct PMCID render hack
                        pmcid = items[0].get("pmcid")
                        if pmcid:
                            candidates.append({"source": "europe_pmc_render", "url": f"https://europepmc.org/articles/{pmcid}?pdf=render"})
                            candidates.append({"source": "europe_pmc_ftp", "url": f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf"})
                            
                        # Listed URLs
                        urls = items[0].get("fullTextUrlList", {}).get("fullTextUrl", [])
                        for u in urls:
                            url_val = u.get("url")
                            if url_val: candidates.append({"source": "europe_pmc", "url": url_val})
                            
        # 3. Predictable Direct Links
        if article.doi:
            if "10.1038/" in article.doi.lower() or "10.1186/" in article.doi.lower():
                suffix = article.doi.split("/", 1)[1]
                candidates.append({"source": "nature_direct", "url": f"https://www.nature.com/articles/{suffix}.pdf"})
            
        if getattr(article, 'oa_pdf_url', None):
            candidates.append({"source": "article_oa_pdf", "url": article.oa_pdf_url})
            
        # Deduplicate & Prioritize Direct PDFs
        seen = set()
        dedup = []
        for c in candidates:
            if c["url"] not in seen:
                seen.add(c["url"])
                # prioritize pdf links
                if ".pdf" in c["url"].lower() or "render" in c["url"].lower() or "blobtype=pdf" in c["url"].lower():
                    dedup.insert(0, c)
                else:
                    dedup.append(c)
        return dedup

    async def _try_download(self, candidate: dict, started_total: float, pmc_id: str = None) -> dict:
        url = candidate["url"]
        source = candidate["source"]
        
        if time.perf_counter() - started_total > self.budget_seconds - 2.0:
            return None
            
        started = time.perf_counter()
        try:
            resp = await self.client.get(url)
            body = resp.content
            ctype = resp.headers.get("content-type", "").lower()
            
            # Follow some redirect explicitly if needed, but httpx already does it.
            if resp.status_code in [200, 206]:
                is_pdf = "pdf" in ctype or body.startswith(b"%PDF")
                is_full_text_xml = "xml" in ctype and b"<body" in body.lower()
                is_full_text_html = "html" in ctype and len(body) > 15000 and (b"citation_title" in body.lower() or b"abstract" in body.lower())
                
                # Drop anti-bot pages quickly
                if "html" in ctype and (b"just a moment" in body.lower() or b"cloudflare" in body.lower() or b"captcha" in body.lower()):
                    self._log_attempt("download", source, "cloudflare_blocked", started, url)
                    return None
                    
                if is_pdf or is_full_text_xml or is_full_text_html:
                    ext = ".pdf" if is_pdf else ".xml" if is_full_text_xml else ".html"
                    self._log_attempt("download", source, "ok", started, str(resp.url), f"ctype={ctype}")
                    return {"success": True, "body": body, "ext": ext, "source": source, "url": str(resp.url)}
            
            self._log_attempt("download", source, "reject", started, str(resp.url), f"status={resp.status_code}")
            return None
        except Exception as e:
            self._log_attempt("download", source, "error", started, url, str(e))
            return None

    async def run(self, article: ArticleReference) -> dict:
        started_total = time.perf_counter()
        
        candidates = await self.get_candidates(article)
        
        overall_success = False
        final_file = None
        final_source = None
        final_url = None
        
        if candidates:
            # Launch max 5 concurrent downloads to win the race
            tasks = [asyncio.create_task(self._try_download(c, started_total, article.pmc_id)) for c in candidates[:5]]
            
            try:
                for future in asyncio.as_completed(tasks):
                    res = await future
                    if res and res["success"]:
                        overall_success = True
                        final_source = res["source"]
                        final_url = res["url"]
                        
                        stem = getattr(article, "doi", None) or getattr(article, "pmid", None) or "article"
                        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:50]
                        filename = f"{safe_stem}_{final_source}{res['ext']}"
                        final_file = self.output_dir / filename
                        final_file.write_bytes(res["body"])
                        
                        for t in tasks: t.cancel()
                        break
            finally:
                for t in tasks:
                    if not t.done(): t.cancel()
                    
        total_ms = int((time.perf_counter() - started_total) * 1000)
        return {
            "article": article.model_dump() if hasattr(article, 'model_dump') else article.dict(),
            "mode": "final_method",
            "success": overall_success,
            "source": final_source,
            "url": final_url,
            "file_path": str(final_file) if final_file else None,
            "total_ms": total_ms,
            "attempts": self.attempts,
            "candidate_count": len(candidates),
            "note": "success" if overall_success else "no_successful_candidate"
        }

class FinalMethodBridge:
    async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast") -> list[dict]:
        with httpx.Client(verify=False) as client:
            downloader = FinalMethodDownloader(Path("/tmp"), budget_seconds=10.0)
            cands = asyncio.run(downloader.get_candidates(article))
            return cands
            
    async def run(self, article: ArticleReference, *, output_dir: Path, mode: str = "fast", budget_seconds: float = 60.0) -> dict:
        downloader = FinalMethodDownloader(output_dir, budget_seconds=budget_seconds)
        try:
            return await downloader.run(article)
        finally:
            await downloader.close()
