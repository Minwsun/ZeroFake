import os
import re
import json
import httpx
import time
import random
from datetime import datetime
from urllib.parse import urlparse, urlencode

from duckduckgo_search import DDGS
from gnews import GNews
import wikipediaapi
from googlesearch import search as google_search
import trafilatura
from fake_useragent import UserAgent
from dotenv import load_dotenv

load_dotenv()

# SearXNG Configuration
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8080")  # Self-hosted default
WARP_PROXY = os.getenv("WARP_PROXY", "socks5://127.0.0.1:40000")
WARP_ENABLED = os.getenv("WARP_ENABLED", "false").lower() == "true"

# Legacy Google API keys (kept for compatibility)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

MAX_RESULTS = 20  # Láº¥y Ä‘á»§ evidence cho táº¥t cáº£ nguá»“n
SEARXNG_TIMEOUT = 30  # Timeout cho SearXNG requests
DDG_TIMEOUT = 20  # Timeout cho DuckDuckGo fallback

# Keywords indicating international events that need English search
INTERNATIONAL_KEYWORDS = [
    "apple", "google", "microsoft", "amazon", "meta", "facebook", "twitter", "x.com",
    "tesla", "spacex", "nvidia", "openai", "chatgpt", "samsung", "sony", "nintendo",
    "iphone", "ipad", "macbook", "galaxy", "pixel", "vision pro", "quest",
    "reuters", "bbc", "cnn", "nytimes", "ap news", "afp",
    "world cup", "champions league", "premier league", "nba", "nfl", "olympics",
    "us", "usa", "uk", "china", "japan", "korea", "europe", "america",
    "biden", "trump", "putin", "xi jinping", "elon musk", "tim cook", "satya nadella",
    "baltimore", "washington", "new york", "london", "tokyo", "beijing", "paris",
    "francis scott key", "mh370", "boeing", "airbus",
]


def get_site_query(config_path: str = "config.json") -> str:
    """Return empty string so we search the entire web."""
    return ""


def _clean_query(query: str) -> str:
    """Remove noise prefixes and emoji from query."""
    # Remove common Vietnamese news prefixes
    query = re.sub(r'^(TIN NÃ“NG|NÃ“NG|BREAKING|TIN Má»šI|Sá»C|Cáº¢NH BÃO|âš ï¸|ðŸ”´|ðŸ“¢|ðŸš¨|â—)[:!]*\s*', '', query, flags=re.IGNORECASE)
    # Remove source citations that aren't helpful for search
    query = re.sub(r'^(Theo Reuters|Theo BBC|Theo AP|ThÃ´ng tin tá»« AP|BBC Ä‘Æ°a tin)[:]*\s*', '', query, flags=re.IGNORECASE)
    # Remove call-to-action phrases
    query = re.sub(r'\s*[-â€“]\s*(Xem ngay|Chia sáº» ngay|Äá»c thÃªm|Click here).*$', '', query, flags=re.IGNORECASE)
    return query.strip()


def _is_international_event(text: str) -> bool:
    """Check if the claim is about an international event that needs English search."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in INTERNATIONAL_KEYWORDS)


def _extract_english_query(text: str) -> str:
    """Extract or create an English-friendly query from Vietnamese text.
    Translate key Vietnamese terms to proper English for accurate search."""
    
    # Comprehensive Vietnamese to English translations
    translations = {
        # Sports
        "vÃ´ Ä‘á»‹ch": "won championship",
        "giáº£i vÃ´ Ä‘á»‹ch": "championship",
        "Ä‘á»™i tuyá»ƒn Viá»‡t Nam": "Vietnam national team",
        "bÃ³ng Ä‘Ã¡": "football soccer",
        "SEA Games": "SEA Games",
        "AFF Cup": "AFF Cup",
        # Events
        "ra máº¯t": "launched released",
        "cÃ´ng bá»‘": "announced",
        "qua Ä‘á»i": "died passed away",
        "máº¥t tÃ­ch": "missing disappeared",
        "tai náº¡n": "accident",
        "sáº­p cáº§u": "bridge collapse",
        "Ä‘á»™ng Ä‘áº¥t": "earthquake",
        # Technology
        "Ä‘iá»‡n thoáº¡i": "smartphone phone",
        "mÃ¡y tÃ­nh": "computer",
        "trÃ­ tuá»‡ nhÃ¢n táº¡o": "artificial intelligence AI",
        # Politics
        "báº§u cá»­": "election",
        "tá»•ng thá»‘ng": "president",
        "thá»§ tÆ°á»›ng": "prime minister",
        "chÃ­nh phá»§": "government",
        # Geography
        "Viá»‡t Nam": "Vietnam",
        "HÃ  Ná»™i": "Hanoi",
        "Campuchia": "Cambodia",
        "ThÃ¡i Lan": "Thailand",
        # Time (remove Vietnamese, keep numbers)
        "thÃ¡ng": "month",
        "nÄƒm": "year",
        "vá»«a": "just recently",
        "Ä‘Ãªm qua": "last night",
        "hÃ´m nay": "today",
        "má»›i nháº¥t": "latest",
    }
    
    result = text
    for vn, en in translations.items():
        result = re.sub(vn, en, result, flags=re.IGNORECASE)
    
    # Keep alphanumeric, spaces, and common punctuation
    result = re.sub(r'[^\w\s\-\./]', ' ', result)
    result = re.sub(r'\s+', ' ', result).strip()
    
    return result


def _ensure_news_keyword(query: str) -> str:
    query = (query or "").strip()
    lower = query.lower()
    if not any(kw in lower for kw in ["tin tá»©c", "news", "thÃ´ng tin", "bÃ¡o", "article"]):
        return f"{query} tin tá»©c".strip()
    return query


def _sort_key(item: dict) -> tuple:
    """Simple sort by date (newest first)."""
    date_str = item.get("date") or "1970-01-01"
    try:
        ts = datetime.strptime(date_str[:10], "%Y-%m-%d").timestamp()
    except Exception:
        ts = 0
    return (-ts,)  # Sort by date descending


def _create_http_client() -> httpx.Client:
    """Create HTTP client with optional WARP proxy."""
    if WARP_ENABLED:
        print(f"ðŸ”’ Sá»­ dá»¥ng Cloudflare WARP proxy: {WARP_PROXY}")
        return httpx.Client(
            proxy=WARP_PROXY,
            timeout=SEARXNG_TIMEOUT,
            follow_redirects=True,
        )
    else:
        return httpx.Client(
            timeout=SEARXNG_TIMEOUT,
            follow_redirects=True,
        )


def _run_searxng(query: str, time_range: str = "month") -> list:
    """
    Gá»i SearXNG API Ä‘á»ƒ tÃ¬m kiáº¿m, chá»‰ sá»­ dá»¥ng Google engine.
    
    Args:
        query: Tá»« khÃ³a tÃ¬m kiáº¿m
        time_range: Khoáº£ng thá»i gian (day, week, month, year)
    
    Returns:
        List cÃ¡c káº¿t quáº£ tÃ¬m kiáº¿m, hoáº·c None náº¿u lá»—i (Ä‘á»ƒ trigger fallback)
    """
    params = {
        "q": query,
        "format": "json",
        "engines": "google",  # CHá»ˆ sá»­ dá»¥ng Google Ä‘á»ƒ Ä‘áº¡t cháº¥t lÆ°á»£ng cao nháº¥t
        "language": "vi-VN",
        "safesearch": "0",
        "pageno": "1",
    }
    
    # Map time range
    if time_range == "w":
        params["time_range"] = "week"
    elif time_range == "d":
        params["time_range"] = "day"
    elif time_range == "y":
        params["time_range"] = "year"
    else:
        params["time_range"] = "month"
    
    search_url = f"{SEARXNG_URL.rstrip('/')}/search"
    
    try:
        with _create_http_client() as client:
            response = client.get(search_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            results = data.get("results", [])
            print(f"âœ… SearXNG (Google): TÃ¬m tháº¥y {len(results)} káº¿t quáº£")
            return results
            
    except httpx.TimeoutException:
        print(f"â±ï¸ SearXNG timeout sau {SEARXNG_TIMEOUT}s - sáº½ fallback sang DuckDuckGo")
        return None  # Trigger fallback
    except httpx.HTTPStatusError as e:
        print(f"âŒ SearXNG HTTP error: {e.response.status_code} - sáº½ fallback sang DuckDuckGo")
        return None  # Trigger fallback
    except Exception as exc:
        print(f"âŒ SearXNG lá»—i: {exc} - sáº½ fallback sang DuckDuckGo")
        return None  # Trigger fallback


def _run_ddg_fallback(query: str, timelimit: str = "m") -> list:
    """
    DuckDuckGo fallback khi SearXNG khÃ´ng kháº£ dá»¥ng.
    
    Args:
        query: Tá»« khÃ³a tÃ¬m kiáº¿m
        timelimit: Khoáº£ng thá»i gian (d, w, m, y)
    
    Returns:
        List cÃ¡c káº¿t quáº£ tÃ¬m kiáº¿m
    """
    print(f"ðŸ¦† Fallback: Äang gá»i DuckDuckGo cho: {query}")
    try:
        with DDGS() as ddgs:
            results = ddgs.text(
                keywords=query,
                region="vi-vn",
                safesearch="off",
                timelimit=timelimit,
                max_results=MAX_RESULTS,
            ) or []
            print(f"âœ… DuckDuckGo: TÃ¬m tháº¥y {len(results)} káº¿t quáº£")
            return results
    except Exception as exc:
        print(f"âŒ DuckDuckGo lá»—i: {exc}")
        return []


def call_google_search(text_input: str, site_query_string: str) -> list:
    """
    IMPROVED: Use DDGS().news() for proper news search instead of text() with site: query.
    Priority: VN News â†’ International News â†’ Web fallback
    """
    print(f"Äang gá»i Search cho: {text_input}")
    
    # Clean the query first
    cleaned_input = _clean_query(text_input)
    en_query = _extract_english_query(cleaned_input)
    query_vi = _ensure_news_keyword(cleaned_input)
    
    # Determine timelimit
    timelimit = None
    if any(kw in query_vi.lower() for kw in ["má»›i nháº¥t", "latest", "hÃ´m nay", "today", "vá»«a"]):
        timelimit = "w"  # This week

    all_items = []
    seen = set()

    def _ingest_ddg(results, source_type="web"):
        """Ingest results from DuckDuckGo."""
        for r in results:
            # DDG .news() returns different keys than .text()
            link = r.get("url") or r.get("href")
            if not link or link in seen:
                continue
            seen.add(link)

            snippet = r.get("body") or r.get("snippet") or ""
            title = r.get("title") or ""
            date_raw = r.get("date") or ""
            source = r.get("source") or ""  # .news() often has source field

            # Skip if snippet too short
            if len(snippet) < 30 and "youtube.com" not in link:
                continue

            # Show source in title if available
            display_title = title
            if source and source not in title:
                display_title = f"[{source}] {title}"

            all_items.append({
                "title": display_title,
                "link": link,
                "snippet": snippet,
                "source": source,
                "pagemap": {},
                "date": date_raw,
            })

    def _run_ddg_news(q: str, tl: str | None, region: str = "vi-vn"):
        """Use DDGS().news() for actual news articles."""
        try:
            with DDGS() as ddgs:
                return ddgs.news(
                    keywords=q,
                    region=region,
                    safesearch="off",
                    timelimit=tl,
                    max_results=MAX_RESULTS
                ) or []
        except Exception as exc:
            print(f"  DDG NEWS error ({region}): {exc}")
            return []

    def _run_ddg_text(q: str, tl: str | None, region: str = "vi-vn"):
        """Fallback to web search."""
        try:
            with DDGS() as ddgs:
                kwargs = {
                    "keywords": q,
                    "region": region,
                    "safesearch": "off",
                    "max_results": MAX_RESULTS,
                }
                if tl:
                    kwargs["timelimit"] = tl
                return ddgs.text(**kwargs) or []
        except Exception as exc:
            print(f"  DDG TEXT error ({region}): {exc}")
            return []

    def _run_google_cse(query: str) -> list:
        """Google Custom Search Engine - Primary search."""
        if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
            print("  [CSE] API key/CSE ID not configured - skip")
            return None  # Return None to trigger DDG fallback
        
        try:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {
                "key": GOOGLE_API_KEY,
                "cx": GOOGLE_CSE_ID,
                "q": query,
                "num": min(10, MAX_RESULTS),  # CSE max 10 per request
                "lr": "lang_vi",  # Vietnamese
            }
            
            with httpx.Client(timeout=15) as client:
                response = client.get(url, params=params)
                
                if response.status_code == 429:
                    print("  [CSE] Quota exceeded - fallback to DDG")
                    return None  # Trigger DDG fallback
                    
                response.raise_for_status()
                data = response.json()
                items = data.get("items", [])
                print(f"  [CSE] Found {len(items)} results")
                return items
                
        except httpx.HTTPStatusError as e:
            print(f"  [CSE] HTTP error {e.response.status_code} - fallback to DDG")
            return None
        except Exception as exc:
            print(f"  [CSE] Error: {exc} - fallback to DDG")
            return None

    def _ingest_cse(results: list):
        """Ingest Google CSE results."""
        if not results:
            return
        for r in results:
            link = r.get("link")
            if not link or link in seen:
                continue
            seen.add(link)
            
            snippet = r.get("snippet", "")
            title = r.get("title", "")
            
            if len(snippet) < 30:
                continue
                
            all_items.append({
                "title": title,
                "link": link,
                "snippet": snippet,
                "source": "google_cse",
                "pagemap": r.get("pagemap", {}),
                "date": "",
            })

    # --- GOOGLE NEWS + DDG COMPREHENSIVE SEARCH ---
    
    # 0. GOOGLE NEWS (Primary - via gnews library, free, no API)
    def _run_gnews(query: str, language: str = "vi", country: str = "VN") -> list:
        """Search Google News using gnews library."""
        try:
            gn = GNews(language=language, country=country, max_results=10)
            results = gn.get_news(query)
            print(f"  [GNEWS-{language.upper()}] Found {len(results)} results")
            return results
        except Exception as exc:
            print(f"  [GNEWS] Error: {exc}")
            return []
    
    def _ingest_gnews(results: list):
        """Ingest Google News results."""
        if not results:
            return
        for r in results:
            link = r.get("url", "")
            if not link or link in seen:
                continue
            seen.add(link)
            
            title = r.get("title", "")
            description = r.get("description", "")
            publisher = r.get("publisher", {}).get("title", "")
            pub_date = r.get("published date", "")
            
            # Combine title + description for better evidence
            snippet = f"{title}. {description}" if description else title
            
            if len(snippet) < 30:
                continue
                
            all_items.append({
                "title": title,
                "link": link,
                "snippet": snippet,
                "source": f"google_news_{publisher}",
                "pagemap": {},
                "date": pub_date,
            })
    
    # --- OPTIMIZED SEARCH STRATEGY ---
    # Priority: GNews (fast) â†’ Wikipedia (fast) â†’ DDG (fallback if < 5 results)
    
    # =========================================================================
    # NEW: SITE-SPECIFIC QUERY DETECTION (Skip GNews/Wiki for trusted sources)
    # =========================================================================
    is_site_query = text_input.strip().lower().startswith("site:")
    
    if is_site_query:
        print(f"  [SITE-QUERY] Detected site: query - using DDG primary, Google backup")
        
        # Skip GNews and Wikipedia for site: queries
        # Priority: DDG (works better) â†’ Google with English
        
        site_query = text_input.strip()
        
        # Extract domain and claim content
        site_match = re.match(r'^site:(\S+)\s+(.+)$', site_query, re.IGNORECASE)
        domain = ""
        claim_content = site_query
        if site_match:
            domain = site_match.group(1)
            claim_content = site_match.group(2).strip()
        
        # 1. DDG WEB SEARCH (Primary - works best with site: queries)
        print(f"  [DDG-SITE] TÃ¬m DDG: {site_query[:60]}...")
        _ingest_ddg(_run_ddg_text(site_query, None, region="wt-wt"), source_type="web")
        
        # 2. DDG search claim content only (Vietnamese)
        if claim_content != site_query:
            print(f"  [DDG-CLAIM-VN] TÃ¬m DDG claim: {claim_content[:50]}...")
            _ingest_ddg(_run_ddg_text(claim_content + " tin tá»©c", timelimit or "m", region="vi-vn"), source_type="web")
        
        # 3. DDG search claim content (English) for international news
        en_claim = _extract_english_query(claim_content)
        if en_claim and len(en_claim) > 10:
            print(f"  [DDG-CLAIM-EN] TÃ¬m DDG EN: {en_claim[:50]}...")
            _ingest_ddg(_run_ddg_text(en_claim + " news", None, region="wt-wt"), source_type="web")
        
        # 4. GOOGLE WEB with English query (backup)
        if domain and en_claim:
            google_site_query = f"site:{domain} {en_claim}"
            print(f"  [GOOGLE-SITE-EN] TÃ¬m Google EN: {google_site_query[:60]}...")
            try:
                time.sleep(random.uniform(0.5, 1.5))
                urls = list(google_search(google_site_query, num_results=5, lang="en"))
                print(f"  [GOOGLE-SITE-EN] Found {len(urls)} URLs")
                for url in urls[:3]:
                    if url not in seen:
                        seen.add(url)
                        try:
                            downloaded = trafilatura.fetch_url(url)
                            if downloaded:
                                content = trafilatura.extract(downloaded, include_comments=False)
                                if content and len(content) > 50:
                                    all_items.append({
                                        "title": url.split("/")[-1][:50],
                                        "link": url,
                                        "snippet": content[:400],
                                        "source": "google_site",
                                        "pagemap": {},
                                        "date": "",
                                    })
                        except Exception:
                            pass
            except Exception as exc:
                print(f"  [GOOGLE-SITE-EN] Error: {exc}")
        
        # Sort and return early
        all_items.sort(key=_sort_key)
        print(f"ðŸ“Š Site-Search: Tá»•ng cá»™ng {len(all_items)} báº±ng chá»©ng tá»« DDG/Google.")
        return all_items[:MAX_RESULTS]
    
    # =========================================================================
    # NORMAL FLOW (for non-site: queries)
    # =========================================================================
    
    # 1. GOOGLE NEWS: Primary news source (fast, reliable)
    print(f"  [GNEWS-VN] TÃ¬m Google News VN: {cleaned_input[:50]}...")
    _ingest_gnews(_run_gnews(cleaned_input, language="vi", country="VN"))
    
    if en_query and len(en_query) > 5:
        print(f"  [GNEWS-EN] TÃ¬m Google News QT: {en_query[:50]}...")
        _ingest_gnews(_run_gnews(en_query, language="en", country="US"))
    
    # 2. WIKIPEDIA: Fast direct Wikipedia search for entities
    def _search_wikipedia(query: str, lang: str = "vi") -> list:
        """Search Wikipedia directly for entity info."""
        try:
            wiki = wikipediaapi.Wikipedia(
                user_agent='ZeroFake/1.0 (fact-checker)',
                language=lang
            )
            # Try to find page
            page = wiki.page(query)
            if page.exists():
                return [{
                    "title": page.title,
                    "link": page.fullurl,
                    "snippet": page.summary[:500] if page.summary else "",
                    "source": f"wikipedia_{lang}",
                    "date": "",
                }]
            return []
        except Exception as exc:
            print(f"  [WIKI] Error: {exc}")
            return []
    
    # Extract main entity from claim for Wikipedia search
    main_entity = cleaned_input.split()[0:5]  # First 5 words
    main_entity_str = " ".join(main_entity)
    
    print(f"  [WIKI-VN] TÃ¬m Wikipedia VN: {main_entity_str[:30]}...")
    wiki_results = _search_wikipedia(main_entity_str, "vi")
    for wr in wiki_results:
        if wr["link"] not in seen:
            seen.add(wr["link"])
            all_items.append(wr)
    
    if en_query:
        print(f"  [WIKI-EN] TÃ¬m Wikipedia EN: {en_query[:30]}...")
        wiki_results_en = _search_wikipedia(en_query.split()[0:3] if len(en_query.split()) > 3 else en_query, "en")
        for wr in wiki_results_en:
            if wr["link"] not in seen:
                seen.add(wr["link"])
                all_items.append(wr)
    
    # 3. GOOGLE WEB SEARCH (with anti-block)
    def _run_google_web(query: str, num: int = 5) -> list:
        """Search Google Web directly with anti-block measures."""
        try:
            # Random delay to avoid detection
            time.sleep(random.uniform(1.0, 2.0))
            
            urls = list(google_search(query, num_results=num, lang="vi"))
            print(f"  [GOOGLE-WEB] Found {len(urls)} URLs")
            return urls
        except Exception as exc:
            print(f"  [GOOGLE-WEB] Error: {exc}")
            return []
    
    def _extract_with_trafilatura(url: str) -> str:
        """Extract article content from URL using trafilatura."""
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(downloaded, include_comments=False)
                return text[:500] if text else ""
            return ""
        except Exception:
            return ""
    
    # Run Google Web search for top URLs
    if len(all_items) < 10:
        print(f"  [GOOGLE-WEB] TÃ¬m Google Web: {cleaned_input[:40]}...")
        google_urls = _run_google_web(cleaned_input, num=5)
        
        for url in google_urls[:3]:  # Only extract top 3 to save time
            if url not in seen:
                seen.add(url)
                # Try to extract content with trafilatura
                content = _extract_with_trafilatura(url)
                if content and len(content) > 50:
                    all_items.append({
                        "title": url.split("/")[-1][:50],
                        "link": url,
                        "snippet": content[:400],
                        "source": "google_web",
                        "pagemap": {},
                        "date": "",
                    })
    
    # 4. DDG: FALLBACK only if still not enough results
    if len(all_items) == 0:  # Only run DDG when NO sources found
        print(f"  [DDG] Fallback: cáº§n thÃªm evidence ({len(all_items)} < 5)...")
        _ingest_ddg(_run_ddg_news(cleaned_input, timelimit or "m", region="vi-vn"), source_type="news")
        
        if en_query and len(en_query) > 5 and len(all_items) < 3:  # Supplement with EN if still very few
            _ingest_ddg(_run_ddg_text(en_query, None, region="wt-wt"), source_type="web")

    # Sort by date (newest first)
    all_items.sort(key=_sort_key)

    print(f"ðŸ“Š Search: Tá»•ng cá»™ng {len(all_items)} báº±ng chá»©ng tá»« ALL sources.")
    return all_items[:MAX_RESULTS]



