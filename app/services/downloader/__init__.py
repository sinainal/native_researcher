"""Downloader service package."""

from app.services.downloader.article_downloader_bridge import ArticleDownloaderBridge
from app.services.downloader.hybrid_bridge import HybridDownloaderBridge
from app.services.downloader.legacy_bridge import ExactNewMethodBridge
from app.services.downloader.service import PDFService
from app.services.downloader.xml_bridge import XmlDownloaderBridge

__all__ = ["ArticleDownloaderBridge", "HybridDownloaderBridge", "ExactNewMethodBridge", "PDFService", "XmlDownloaderBridge"]
