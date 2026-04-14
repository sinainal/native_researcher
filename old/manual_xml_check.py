
import asyncio
from pathlib import Path
import sys
import os

# Ensure app is in path
sys.path.append("/home/sina/Downloads/downloader/native_researcher")

from app.services.downloader.xml_bridge import XmlDownloaderBridge
from app.schemas.article import ArticleReference

async def test():
    bridge = XmlDownloaderBridge()
    # Test with a known PMC ID
    article = ArticleReference(title="Test", year="2020", pmc_id="PMC7003109")
    output_dir = Path("/home/sina/Downloads/downloader/native_researcher/test_downloads")
    output_dir.mkdir(exist_ok=True)
    
    print(f"Testing XML download for {article.pmc_id}...")
    result = await bridge.run(article, output_dir=output_dir)
    print(f"Result: {result['success']}, File: {result['file_path']}")
    
    if result['success']:
        print("SUCCESS: XML bridge is working perfectly.")
    else:
        print(f"FAILURE: {result.get('note')}")

if __name__ == "__main__":
    asyncio.run(test())
