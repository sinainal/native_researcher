import time
import asyncio
from pathlib import Path
from typing import Any
import httpx
from app.schemas.article import ArticleReference

class XmlDownloaderBridge:
    """
    Yüksek performanslı XML Downloader.
    NCBI, Unpaywall ve Europe PMC kaynaklarını hibrit olarak kullanarak %95+ başarı hedefler.
    """
    def __init__(self, **kwargs):
        self.settings = kwargs.get("settings")
        self.email = _read_unpaywall_email()
        self.headers = {"User-Agent": "NativeResearcher-XMLBridge/1.1"}

    async def _resolve_xml_link(self, client: httpx.AsyncClient, article: ArticleReference) -> dict[str, Any] | None:
        doi = article.doi
        # 1. NCBI IdConv
        pmcid = self._clean_pmcid(article.pmc_id)
        if not pmcid and doi:
            try:
                url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={doi}&format=json&tool=NativeResearcher&email={self.email}"
                r = await client.get(url, timeout=5.0, follow_redirects=True)
                if r.status_code == 200:
                    for rec in r.json().get("records", []):
                        if rec.get("pmcid"): pmcid = self._clean_pmcid(rec["pmcid"])
            except Exception: pass

        # 2. Europe PMC Search (Deep Check)
        if doi:
            try:
                url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:\"{doi}\"&format=json&resultType=core"
                r = await client.get(url, headers=self.headers, timeout=8.0)
                if r.status_code == 200:
                    data = r.json()
                    results = data.get("resultList", {}).get("result", [])
                    if results:
                        res = results[0]
                        if not pmcid: pmcid = self._clean_pmcid(res.get("pmcid"))
                        # Check fullTextUrlList
                        for u in res.get("fullTextUrlList", {}).get("fullTextUrl", []):
                            if u.get("documentStyle") == "xml" or "xml" in u.get("url", "").lower():
                                return {"url": u["url"], "source": "epmc_xml", "pmcid": pmcid}
                elif r.status_code == 301 or r.status_code == 302:
                     # Attempt again with redirect if manually needed
                     pass
            except Exception: pass

        # 3. Crossref (Publisher XML Link Bulma)
        if doi:
            try:
                url = f"https://api.crossref.org/works/{doi}"
                r = await client.get(url, headers=self.headers, timeout=5.0)
                if r.status_code == 200:
                    data = r.json()
                    links = data.get("message", {}).get("link", [])
                    for l in links:
                        if l.get("content-type") == "text/xml" or l.get("content-type") == "application/xml":
                            return {"url": l["URL"], "source": "crossref_publisher_xml", "pmcid": pmcid}
            except Exception: pass

        # 4. Unpaywall (Mirror XML Bulma)
        if doi:
            try:
                url = f"https://api.unpaywall.org/v2/{doi}?email={self.email}"
                r = await client.get(url, timeout=5.0)
                if r.status_code == 200:
                    data = r.json()
                    for loc in data.get("oa_locations", []):
                        u = loc.get("url_for_pdf") or loc.get("url")
                        if u and (".xml" in u.lower() or "fulltextxml" in u.lower()):
                            return {"url": u, "source": "unpaywall_xml", "pmcid": pmcid}
            except Exception: pass

        # FINAL: NCBI eFetch Fallback
        if pmcid:
            raw_id = pmcid.replace("PMC", "")
            return {"url": f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={raw_id}&retmode=xml", "source": "ncbi_xml", "pmcid": pmcid}
        
        return None

    def _clean_pmcid(self, val: Any) -> str | None:
        if not val or not str(val).startswith("PMC"): return None
        return str(val).strip()

    async def run(self, article: ArticleReference, *, output_dir: Path, **kwargs) -> dict[str, Any]:
        started = time.perf_counter()
        async with httpx.AsyncClient(verify=False) as client:
            res = await self._resolve_xml_link(client, article)
            if not res:
                return {
                    "success": False, "error": "no_xml_metadata", 
                    "note": f"DOI={article.doi}, PMCID={article.pmc_id}",
                    "total_ms": int((time.perf_counter()-started)*1000)
                }
            
            # RETRY LOOP (Max 3 attempts with backoff)
            for attempt in range(3):
                try:
                    r = await client.get(res["url"], timeout=20.0, follow_redirects=True)
                    if r.status_code == 200:
                        stem = article.doi.replace("/", "_") if article.doi else (res["pmcid"] or "article")
                        path = output_dir / f"{stem}.xml"
                        path.write_bytes(r.content)
                        return {
                            "success": True, "source": res["source"], "file_path": str(path),
                            "total_ms": int((time.perf_counter()-started)*1000), "candidate_count": 1
                        }
                    elif r.status_code == 429: # Rate limit
                        await asyncio.sleep(1.0 + attempt)
                        continue
                    else:
                        break # Other HTTP errors
                except Exception:
                    await asyncio.sleep(0.5)
                    continue
            
        return {"success": False, "error": "download_failed_after_retries", "total_ms": int((time.perf_counter()-started)*1000)}

def _read_unpaywall_email():
    path = Path("/home/sina/Downloads/downloader/native_researcher/unpaywall_email")
    if path.exists(): return path.read_text().strip()
    return "anon@example.com"
