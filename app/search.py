import os
import re
import json
import httpx
from datetime import datetime
from urllib.parse import urlparse, urlencode

from duckduckgo_search import DDGS
from dotenv import load_dotenv

load_dotenv()

# SearXNG Configuration
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8080")  # Self-hosted default
WARP_PROXY = os.getenv("WARP_PROXY", "socks5://127.0.0.1:40000")
WARP_ENABLED = os.getenv("WARP_ENABLED", "false").lower() == "true"

# Legacy Google API keys (kept for compatibility)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

MAX_RESULTS = 25  # Lấy đủ evidence cho CRITIC và JUDGE
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
    query = re.sub(r'^(TIN NÓNG|NÓNG|BREAKING|TIN MỚI|SỐC|CẢNH BÁO|⚠️|🔴|📢|🚨|❗)[:!]*\s*', '', query, flags=re.IGNORECASE)
    # Remove source citations that aren't helpful for search
    query = re.sub(r'^(Theo Reuters|Theo BBC|Theo AP|Thông tin từ AP|BBC đưa tin)[:]*\s*', '', query, flags=re.IGNORECASE)
    # Remove call-to-action phrases
    query = re.sub(r'\s*[-–]\s*(Xem ngay|Chia sẻ ngay|Đọc thêm|Click here).*$', '', query, flags=re.IGNORECASE)
    return query.strip()


def _is_international_event(text: str) -> bool:
    """Check if the claim is about an international event that needs English search."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in INTERNATIONAL_KEYWORDS)


def _extract_english_query(text: str) -> str:
    """Extract or create an English-friendly query from Vietnamese text."""
    # Keep proper nouns and numbers, remove Vietnamese particles
    # Common translations for search
    translations = {
        "vô địch": "champion winner",
        "ra mắt": "launch release",
        "qua đời": "died death",
        "mất tích": "disappeared missing",
        "sập cầu": "bridge collapse",
        "tháng": "",  # Remove, keep the number
        "năm": "",
        "vừa": "",
        "đêm qua": "",
        "hôm nay": "",
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
    if not any(kw in lower for kw in ["tin tức", "news", "thông tin", "báo", "article"]):
        return f"{query} tin tức".strip()
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
        print(f"🔒 Sử dụng Cloudflare WARP proxy: {WARP_PROXY}")
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
    Gọi SearXNG API để tìm kiếm, chỉ sử dụng Google engine.
    
    Args:
        query: Từ khóa tìm kiếm
        time_range: Khoảng thời gian (day, week, month, year)
    
    Returns:
        List các kết quả tìm kiếm, hoặc None nếu lỗi (để trigger fallback)
    """
    params = {
        "q": query,
        "format": "json",
        "engines": "google",  # CHỈ sử dụng Google để đạt chất lượng cao nhất
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
            print(f"✅ SearXNG (Google): Tìm thấy {len(results)} kết quả")
            return results
            
    except httpx.TimeoutException:
        print(f"⏱️ SearXNG timeout sau {SEARXNG_TIMEOUT}s - sẽ fallback sang DuckDuckGo")
        return None  # Trigger fallback
    except httpx.HTTPStatusError as e:
        print(f"❌ SearXNG HTTP error: {e.response.status_code} - sẽ fallback sang DuckDuckGo")
        return None  # Trigger fallback
    except Exception as exc:
        print(f"❌ SearXNG lỗi: {exc} - sẽ fallback sang DuckDuckGo")
        return None  # Trigger fallback


def _run_ddg_fallback(query: str, timelimit: str = "m") -> list:
    """
    DuckDuckGo fallback khi SearXNG không khả dụng.
    
    Args:
        query: Từ khóa tìm kiếm
        timelimit: Khoảng thời gian (d, w, m, y)
    
    Returns:
        List các kết quả tìm kiếm
    """
    print(f"🦆 Fallback: Đang gọi DuckDuckGo cho: {query}")
    try:
        with DDGS() as ddgs:
            results = ddgs.text(
                keywords=query,
                region="vi-vn",
                safesearch="off",
                timelimit=timelimit,
                max_results=MAX_RESULTS,
            ) or []
            print(f"✅ DuckDuckGo: Tìm thấy {len(results)} kết quả")
            return results
    except Exception as exc:
        print(f"❌ DuckDuckGo lỗi: {exc}")
        return []


def call_google_search(text_input: str, site_query_string: str) -> list:
    """
    IMPROVED: Use DDGS().news() for proper news search instead of text() with site: query.
    Priority: VN News → International News → Web fallback
    """
    print(f"Đang gọi Search cho: {text_input}")
    
    # Clean the query first
    cleaned_input = _clean_query(text_input)
    en_query = _extract_english_query(cleaned_input)
    query_vi = _ensure_news_keyword(cleaned_input)
    
    # Determine timelimit
    timelimit = None
    if any(kw in query_vi.lower() for kw in ["mới nhất", "latest", "hôm nay", "today", "vừa"]):
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

    # --- NEWS-FIRST SEARCH STRATEGY ---
    # Ưu tiên tin tức mới nhất từ nguồn news trước

    # Default timelimit = 1 tháng để lấy tin mới nhất
    if timelimit is None:
        timelimit = "m"  # Default: tin trong tháng

    # 1. PRIORITY 1: Vietnamese News (tin tức tiếng Việt mới nhất)
    print(f"  [DDG-NEWS] Tìm tin tức VN: {cleaned_input[:50]}...")
    _ingest_ddg(_run_ddg_news(cleaned_input, timelimit, region="vi-vn"), source_type="news")

    # 2. PRIORITY 2: International News (LUÔN search cả tiếng Anh)
    if en_query and len(en_query) > 5:
        print(f"  [DDG-NEWS] Tìm tin tức QT: {en_query[:50]}...")
        _ingest_ddg(_run_ddg_news(en_query, timelimit, region="wt-wt"), source_type="news")

    # 3. FALLBACK WEB: Khi ít news (<5), search web để lấy thêm từ Wikipedia, etc.
    if len(all_items) < 5:
        print(f"  [DDG-WEB] Fallback tìm kiếm web: {query_vi[:50]}...")
        _ingest_ddg(_run_ddg_text(query_vi, None, region="vi-vn"), source_type="web")  # No timelimit for wiki
        
        # English web fallback để lấy Wikipedia tiếng Anh
        if en_query and len(en_query) > 5:
            print(f"  [DDG-WEB] Tìm kiếm Wikipedia EN: {en_query[:50]}...")
            _ingest_ddg(_run_ddg_text(en_query, None, region="wt-wt"), source_type="web")

    # Sort by date (newest first)
    all_items.sort(key=_sort_key)

    print(f"📊 Search: Tổng cộng {len(all_items)} bằng chứng.")
    return all_items[:MAX_RESULTS]

