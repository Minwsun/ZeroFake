"""
Search Helper Module - For JUDGE and CRITIC agents
Provides direct search access with anti-block measures
"""
import os
import time
import random
from typing import Optional, List, Dict

from gnews import GNews
import wikipediaapi
from googlesearch import search as google_search
import trafilatura
from fake_useragent import UserAgent

# Anti-block settings
USE_DELAYS = True
MIN_DELAY = 1.0  # seconds
MAX_DELAY = 3.0  # seconds
USE_WARP_PROXY = os.getenv("WARP_ENABLED", "false").lower() == "true"
WARP_PROXY = os.getenv("WARP_PROXY", "socks5://127.0.0.1:40000")

# User agent rotation
try:
    ua = UserAgent()
except:
    ua = None


def _get_random_user_agent() -> str:
    """Get random user agent to avoid detection."""
    if ua:
        return ua.random
    return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _random_delay():
    """Add random delay to avoid rate limiting."""
    if USE_DELAYS:
        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        time.sleep(delay)


def search_google_news(query: str, language: str = "vi", country: str = "VN", max_results: int = 10) -> List[Dict]:
    """
    Search Google News using gnews library.
    Returns list of news articles.
    """
    try:
        gn = GNews(language=language, country=country, max_results=max_results)
        results = gn.get_news(query)
        
        items = []
        for r in results:
            items.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("description", ""),
                "publisher": r.get("publisher", {}).get("title", ""),
                "date": r.get("published date", ""),
                "source": "google_news",
            })
        return items
    except Exception as e:
        print(f"[GNEWS] Error: {e}")
        return []


def search_wikipedia(query: str, language: str = "vi") -> Optional[Dict]:
    """
    Search Wikipedia directly.
    Returns page summary if found.
    """
    try:
        wiki = wikipediaapi.Wikipedia(
            user_agent='ZeroFake/1.0 (fact-checker)',
            language=language
        )
        page = wiki.page(query)
        
        if page.exists():
            return {
                "title": page.title,
                "url": page.fullurl,
                "summary": page.summary[:1000] if page.summary else "",
                "source": f"wikipedia_{language}",
            }
        return None
    except Exception as e:
        print(f"[WIKI] Error: {e}")
        return None


def search_google_web(query: str, num_results: int = 10) -> List[str]:
    """
    Search Google Web directly using googlesearch-python.
    Returns list of URLs.
    WARNING: May get blocked if used too frequently!
    """
    try:
        _random_delay()  # Anti-block delay
        
        results = list(google_search(query, num_results=num_results, lang="vi"))
        return results
    except Exception as e:
        print(f"[GOOGLE] Error: {e}")
        return []


def extract_article_content(url: str) -> Optional[str]:
    """
    Extract article content from URL using trafilatura.
    Fast and reliable article extraction.
    """
    try:
        _random_delay()
        
        # Download with custom user agent
        headers = {"User-Agent": _get_random_user_agent()}
        downloaded = trafilatura.fetch_url(url)
        
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            return text
        return None
    except Exception as e:
        print(f"[TRAFILATURA] Error: {e}")
        return None


def quick_fact_check(claim: str) -> Dict:
    """
    Quick fact check using multiple sources.
    For JUDGE/CRITIC to use when they need more evidence.
    
    Returns: {
        "gnews_results": [...],
        "wikipedia": {...},
        "google_urls": [...],
        "evidence_summary": "..."
    }
    """
    results = {
        "gnews_results": [],
        "wikipedia": None,
        "google_urls": [],
        "evidence_summary": "",
    }
    
    # 1. Google News (fast, reliable)
    print(f"  [QUICK-CHECK] Searching Google News: {claim[:50]}...")
    gnews_vi = search_google_news(claim, language="vi", country="VN", max_results=5)
    gnews_en = search_google_news(claim, language="en", country="US", max_results=5)
    results["gnews_results"] = gnews_vi + gnews_en
    
    # 2. Wikipedia (for entity verification)
    words = claim.split()[:3]  # First 3 words as entity
    entity = " ".join(words)
    print(f"  [QUICK-CHECK] Searching Wikipedia: {entity}...")
    wiki_vi = search_wikipedia(entity, language="vi")
    wiki_en = search_wikipedia(entity, language="en")
    results["wikipedia"] = wiki_vi or wiki_en
    
    # 3. Build summary
    summaries = []
    for item in results["gnews_results"][:3]:
        summaries.append(f"- {item['title']} ({item['publisher']})")
    
    if results["wikipedia"]:
        wiki = results["wikipedia"]
        summaries.append(f"- Wikipedia: {wiki['title']}: {wiki['summary'][:200]}...")
    
    results["evidence_summary"] = "\n".join(summaries)
    
    return results


# Export for use in agent_synthesizer
__all__ = [
    "search_google_news",
    "search_wikipedia", 
    "search_google_web",
    "extract_article_content",
    "quick_fact_check",
]
