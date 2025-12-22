# app/article_scraper.py
"""
Article scraper using cloudscraper and newspaper4k.
Extracts full article content from URLs for better evidence analysis.
Uses cloudscraper to bypass Cloudflare protection.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Thread pool for concurrent scraping
_executor = ThreadPoolExecutor(max_workers=5)

# Timeout for scraping (seconds)
SCRAPE_TIMEOUT = 15


def _get_cloudscraper_session():
    """Get a cloudscraper session that can bypass Cloudflare."""
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            },
            delay=5
        )
        return scraper
    except ImportError:
        logger.warning("cloudscraper not installed, falling back to requests")
        import requests
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8',
        })
        return session


def _scrape_with_cloudscraper(url: str) -> dict:
    """Scrape article using cloudscraper + newspaper4k."""
    try:
        from newspaper import Article
        
        # Use cloudscraper to bypass Cloudflare
        scraper = _get_cloudscraper_session()
        
        try:
            response = scraper.get(url, timeout=12, allow_redirects=True)
            
            # Check for Cloudflare block
            if response.status_code == 403:
                if 'Just a moment' in response.text or 'cloudflare' in response.text.lower():
                    logger.debug(f"Cloudflare block detected for {url}")
                    return {"url": url, "text": "", "success": False, "error": "Cloudflare block"}
            
            if response.status_code != 200:
                logger.debug(f"HTTP {response.status_code} for {url}")
                return {"url": url, "text": "", "success": False, "error": f"HTTP {response.status_code}"}
            
            html = response.text
            
        except Exception as e:
            logger.debug(f"Request failed for {url}: {e}")
            html = None
        
        # Parse with newspaper4k
        article = Article(url, language='vi')
        
        if html:
            article.download(input_html=html)
        else:
            article.download()
        
        article.parse()
        
        # Get text content (limit to 2000 chars for efficiency)
        text = article.text or ""
        if len(text) > 2000:
            text = text[:2000] + "..."
        
        if len(text) < 100:  # Too short, probably failed
            return {"url": url, "text": "", "success": False}
        
        return {
            "url": url,
            "title": article.title or "",
            "text": text,
            "authors": article.authors or [],
            "publish_date": str(article.publish_date) if article.publish_date else None,
            "success": True,
            "method": "cloudscraper+newspaper4k",
        }
    except Exception as e:
        logger.debug(f"cloudscraper+newspaper4k failed for {url}: {e}")
        return {
            "url": url,
            "text": "",
            "success": False,
            "error": str(e),
        }


async def scrape_article(url: str) -> dict:
    """
    Scrape article using cloudscraper to bypass Cloudflare.
    Runs synchronously in thread pool executor.
    """
    loop = asyncio.get_event_loop()
    
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(_executor, _scrape_with_cloudscraper, url),
            timeout=SCRAPE_TIMEOUT
        )
        if result.get("success") and len(result.get("text", "")) > 100:
            return result
    except asyncio.TimeoutError:
        logger.debug(f"Scraping timeout for {url}")
    except Exception as e:
        logger.debug(f"Scraping error for {url}: {e}")
    
    return {
        "url": url,
        "text": "",
        "success": False,
        "error": "Scraping failed",
    }


async def scrape_multiple_articles(urls: list[str], max_articles: int = 5) -> list[dict]:
    """
    Scrape multiple articles concurrently.
    Returns list of scraped article data.
    """
    # Limit number of articles to scrape
    urls_to_scrape = urls[:max_articles]
    
    tasks = [scrape_article(url) for url in urls_to_scrape]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    scraped = []
    for result in results:
        if isinstance(result, Exception):
            continue
        if isinstance(result, dict) and result.get("success"):
            scraped.append(result)
    
    return scraped


def enrich_search_results_with_full_text(search_results: list[dict], scraped_articles: list[dict]) -> list[dict]:
    """
    Merge scraped article content into search results.
    Adds 'full_text' field to matching results.
    """
    # Create lookup by URL
    scraped_lookup = {a["url"]: a for a in scraped_articles if a.get("success")}
    
    for result in search_results:
        url = result.get("link")
        if url and url in scraped_lookup:
            article = scraped_lookup[url]
            result["full_text"] = article.get("text", "")
            if article.get("publish_date"):
                result["scraped_date"] = article["publish_date"]
    
    return search_results
