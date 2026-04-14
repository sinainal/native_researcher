import time
import asyncio
from pathlib import Path
from typing import Any
from app.schemas.article import ArticleReference
from app.services.downloader.xml_bridge import XmlDownloaderBridge
from app.services.downloader.final_method.orchestrator import FinalMethodBridge

class PerfectDownloaderBridge:
    """
    XML ve PDF dünyalarını birleştiren 'Perfect' modu.
    Önce XML dener, bulamazsa anında FinalMethod PDF'e geçer.
    Hız ve başarıyı maksimize eder.
    """
    def __init__(self, **kwargs):
        self.xml_bridge = XmlDownloaderBridge(**kwargs)
        self.pdf_bridge = FinalMethodBridge() # No kwargs here

    async def run(self, article: ArticleReference, *, output_dir: Path, **kwargs) -> dict[str, Any]:
        started = time.perf_counter()
        
        # 1. XML Denemesi (Öncelikli)
        xml_res = await self.xml_bridge.run(article, output_dir=output_dir, **kwargs)
        if xml_res.get("success"):
            xml_res["source"] = f"{xml_res.get('source')} (XML)"
            return xml_res
        
        # XML bulunamadıysa (milisaniyeler içinde buraya gelir)
        # 2. PDF Denemesi (FinalMethod - En hızlı API PDF)
        pdf_res = await self.pdf_bridge.run(article, output_dir=output_dir, **kwargs)
        if pdf_res.get("success"):
            pdf_res["source"] = f"{pdf_res.get('source')} (PDF)"
            return pdf_res
            
        # Her ikisi de başarısız
        return {
            "success": False, 
            "error": "no_fulltext_found",
            "note": f"XML fail: {xml_res.get('error')}, PDF fail: {pdf_res.get('error')}",
            "total_ms": int((time.perf_counter()-started)*1000)
        }
