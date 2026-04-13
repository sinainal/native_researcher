"""
XmlDownloaderBridge
────────────────────
ArticleReference.pmc_id varsa → NCBI eFetch veya Europe PMC REST ile
doğrudan JATS XML indirir. Yayıncı sitelerine hiç gitmez.

Aynı bridge arayüzünü (resolve_candidates / run) uygular → service.py
ile sıfır sürtüşmeli entegrasyon.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from app.schemas.article import ArticleReference


_NCBI_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_EPMC_XML    = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


class XmlDownloaderBridge:
    """
    Hızlı, güvenilir, anti-bot gerektirmeyen tam metin XML indirici.

    Kullanım sırası:
      1. NCBI eFetch  → JATS XML (öncelikli, API key ile 10 req/s)
      2. Europe PMC   → fullTextXML (yedek, herhangi bir rate-limit yok)
    """

    def __init__(self, *, ncbi_api_key: str | None = None, email: str | None = None, timeout_sec: float = 15.0) -> None:
        self.ncbi_api_key = ncbi_api_key
        self.email        = email
        self.timeout      = httpx.Timeout(connect=5.0, read=timeout_sec, write=5.0, pool=2.0)
        
        ua = "NativeResearcher-XMLBridge/1.0"
        if email:
            ua += f" (mailto:{email})"
        self._headers = {"User-Agent": ua}

    # ── Yardımcılar ──────────────────────────────────────────────────────────

    @staticmethod
    def _clean_pmcid(raw: str | None) -> str | None:
        """'PMC1234567' veya '1234567' → 'PMC1234567'"""
        if not raw:
            return None
        text = str(raw).upper().strip()
        if text.startswith("PMC"):
            digits = "".join(c for c in text[3:] if c.isdigit())
            return f"PMC{digits}" if digits else None
        digits = "".join(c for c in text if c.isdigit())
        return f"PMC{digits}" if digits else None

    @staticmethod
    def _valid_xml(content: bytes) -> bool:
        return len(content) > 500 and content.strip().startswith(b"<")

    def _file_dest(self, article: ArticleReference, output_dir: Path) -> Path:
        pmcid = self._clean_pmcid(article.pmc_id) or "article"
        return output_dir / f"{pmcid}.xml"

    # ── İndirme: NCBI eFetch ──────────────────────────────────────────────────

    async def _ncbi_fetch(self, client: httpx.AsyncClient, pmcid: str, dest: Path) -> bool:
        raw_id = pmcid.replace("PMC", "")
        params: dict[str, str] = {"db": "pmc", "id": raw_id, "retmode": "xml"}
        if self.ncbi_api_key:
            params["api_key"] = self.ncbi_api_key
        try:
            r = await client.get(_NCBI_EFETCH, params=params, headers=self._headers, timeout=self.timeout)
            if r.status_code == 200 and self._valid_xml(r.content):
                dest.write_bytes(r.content)
                return True
        except Exception:
            pass
        return False

    # ── İndirme: Europe PMC REST ─────────────────────────────────────────────

    async def _epmc_fetch(self, client: httpx.AsyncClient, pmcid: str, dest: Path) -> bool:
        url = _EPMC_XML.format(pmcid=pmcid)
        try:
            r = await client.get(url, headers=self._headers, timeout=self.timeout, follow_redirects=True)
            if r.status_code == 200 and self._valid_xml(r.content):
                dest.write_bytes(r.content)
                return True
        except Exception:
            pass
        return False

    # ── Bridge Arayüzü ────────────────────────────────────────────────────────

    async def resolve_candidates(
        self,
        article: ArticleReference,
        *,
        mode: str = "fast",
    ) -> list[dict[str, Any]]:
        """service.py ile uyumlu arayüz — resolve aşamasında candidate listesi döner."""
        pmcid = self._clean_pmcid(article.pmc_id)
        if not pmcid:
            return []
        return [
            {"source": "ncbi_xml",    "url": f"{_NCBI_EFETCH}?db=pmc&id={pmcid.replace('PMC','')}&retmode=xml"},
            {"source": "epmc_xml",    "url": _EPMC_XML.format(pmcid=pmcid)},
        ]

    async def run(
        self,
        article: ArticleReference,
        *,
        output_dir: Path,
        mode: str = "fast",
        budget_seconds: float = 60.0,
    ) -> dict[str, Any]:
        """
        Standart bridge çıktısı:
          success, source, file_path, total_ms, candidate_count, note, attempts
        """
        started = time.perf_counter()
        output_dir.mkdir(parents=True, exist_ok=True)
        attempts: list[dict[str, Any]] = []

        pmcid = self._clean_pmcid(article.pmc_id)

        if not pmcid:
            return self._fail(article, started, attempts, "no_pmc_id")

        dest = self._file_dest(article, output_dir)

        async with httpx.AsyncClient() as client:
            # 1. NCBI eFetch
            t0 = time.perf_counter()
            ok = await self._ncbi_fetch(client, pmcid, dest)
            attempts.append(self._attempt("ncbi_efetch_xml", f"{_NCBI_EFETCH}?db=pmc&id={pmcid.replace('PMC','')}&retmode=xml", ok, time.perf_counter() - t0))
            if ok:
                return self._success(article, "ncbi_xml", str(dest), started, attempts)

            # 2. Europe PMC fullTextXML (yedek)
            t0 = time.perf_counter()
            ok = await self._epmc_fetch(client, pmcid, dest)
            attempts.append(self._attempt("epmc_fulltext_xml", _EPMC_XML.format(pmcid=pmcid), ok, time.perf_counter() - t0))
            if ok:
                return self._success(article, "epmc_xml", str(dest), started, attempts)

        return self._fail(article, started, attempts, "xml_not_available_from_ncbi_or_epmc")

    # ── Sonuç yardımcıları ────────────────────────────────────────────────────

    @staticmethod
    def _attempt(source: str, url: str, success: bool, elapsed: float) -> dict[str, Any]:
        return {
            "step"       : "download",
            "source"     : source,
            "url"        : url,
            "status"     : "ok" if success else "error",
            "elapsed_ms" : int(elapsed * 1000),
        }

    @staticmethod
    def _success(
        article: ArticleReference,
        source: str,
        file_path: str,
        started: float,
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "article"        : article.model_dump(),
            "mode"           : "xml",
            "success"        : True,
            "source"         : source,
            "url"            : None,
            "file_path"      : file_path,
            "total_ms"       : int((time.perf_counter() - started) * 1000),
            "attempts"       : attempts,
            "candidate_count": 2,
            "note"           : None,
        }

    @staticmethod
    def _fail(
        article: ArticleReference,
        started: float,
        attempts: list[dict[str, Any]],
        note: str,
    ) -> dict[str, Any]:
        return {
            "article"        : article.model_dump(),
            "mode"           : "xml",
            "success"        : False,
            "source"         : None,
            "url"            : None,
            "file_path"      : None,
            "total_ms"       : int((time.perf_counter() - started) * 1000),
            "attempts"       : attempts,
            "candidate_count": 0,
            "note"           : note,
        }
