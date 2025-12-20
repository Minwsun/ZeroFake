import os
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

MAX_RESULTS = 40  # Tăng từ 20 để thu thập nhiều evidence hơn
SEARXNG_TIMEOUT = 30  # Timeout cho SearXNG requests
DDG_TIMEOUT = 20  # Timeout cho DuckDuckGo fallback
_TRUSTED_DOMAINS_CACHE = None


def get_site_query(config_path: str = "config.json") -> str:
    """Return empty string so we search the entire web."""
    return ""


def _ensure_news_keyword(query: str) -> str:
    query = (query or "").strip()
    lower = query.lower()
    if not any(kw in lower for kw in ["tin tức", "news", "thông tin", "báo", "article"]):
        return f"{query} tin tức".strip()
    return query


def _load_trusted_domains() -> tuple[set, set]:
    global _TRUSTED_DOMAINS_CACHE
    if _TRUSTED_DOMAINS_CACHE is not None:
        return _TRUSTED_DOMAINS_CACHE

    tier0_default = {
        'chinhphu.vn', 'moh.gov.vn', 'moet.gov.vn', 'mof.gov.vn',
        'sbv.gov.vn', 'vncert.gov.vn', 'who.int', 'un.org', 'worldbank.org',
        'imf.org', 'ec.europa.eu', 'reuters.com', 'apnews.com', 'afp.com',
        'bbc.com', 'nytimes.com', 'theguardian.com', 'washingtonpost.com',
        'wsj.com', 'ft.com', 'vnexpress.net', 'dantri.com.vn', 'tuoitre.vn',
        'thanhnien.vn', 'vietnamnet.vn', 'vtv.vn', 'vov.vn', 'nhandan.vn',
        'qdnd.vn', 'cand.com.vn', 'laodong.vn', 'tienphong.vn', 'zingnews.vn',
    }
    tier1_default = {
        'bloomberg.com', 'cnbc.com', 'forbes.com', 'yahoo.com', 'marketwatch.com',
        'nature.com', 'science.org', 'sciencemag.org', 'techcrunch.com', 'wired.com',
        'theverge.com', 'engadget.com', 'pcmag.com', 'cnet.com', 'cointelegraph.com',
        'coindesk.com',
    }

    tier0 = {d.lower() for d in tier0_default}
    tier1 = {d.lower() for d in tier1_default}

    json_path = os.path.join(os.path.dirname(__file__), "trusted_domains.json")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tier0.update(d.lower() for d in data.get("tier0") or [])
        tier1.update(d.lower() for d in data.get("tier1") or [])
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"WARNING: Cannot load trusted_domains.json: {exc}")

    _TRUSTED_DOMAINS_CACHE = (tier0, tier1)
    return _TRUSTED_DOMAINS_CACHE


def _source_tier(domain: str) -> int:
    tier0, tier1 = _load_trusted_domains()
    d = (domain or "").lower().replace("www.", "")
    if d.endswith((".gov", ".gov.vn")) or d in tier0:
        return 0
    if d in tier1:
        return 1

    keywords = (
        "news", "press", "times", "post", "journal", "tribune", "herald",
        "finance", "market", "economy", "business", "weather", "climate",
        "meteo", "forecast", "sport", "sports", "soccer", "football",
        "tech", "technology", "science", "nature", "academy"
    )
    if any(k in d for k in keywords):
        return 1
    return 2


def _sort_key(item: dict) -> tuple:
    tier = item.get("source_tier", 2)
    is_news = item.get("is_news_site", False)
    date_str = item.get("date") or "1970-01-01"
    try:
        ts = datetime.strptime(date_str[:10], "%Y-%m-%d").timestamp()
    except Exception:
        ts = 0
    return (tier, not is_news, -ts)


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
    Tìm kiếm thông qua SearXNG với Google engine.
    Fallback sang DuckDuckGo nếu SearXNG timeout hoặc bị chặn IP.
    Sử dụng Cloudflare WARP để bypass rate limit nếu được bật.
    """
    print(f"🔍 Đang gọi SearXNG (Google) cho: {text_input}")
    query = _ensure_news_keyword(text_input)
    time_range = "w" if any(kw in query.lower() for kw in ["mới nhất", "latest", "recent", "mới"]) else "m"

    all_items = []
    seen = set()
    use_ddg_fallback = False

    def _ingest_searxng(results):
        """Ingest results từ SearXNG format."""
        for r in results:
            # SearXNG trả về 'url' thay vì 'href'
            link = r.get("url") or r.get("href")
            if not link or link in seen:
                continue
            seen.add(link)

            # SearXNG trả về 'content' thay vì 'body'
            snippet = r.get("content") or r.get("body") or ""
            title = r.get("title") or ""
            if len(snippet) < 30:
                continue

            domain = urlparse(link).netloc.lower().replace("www.", "")
            is_news_site = any(kw in domain for kw in [
                "vnexpress", "dantri", "tuoitre", "thanhnien", "vietnamnet", "vtv", "vov",
                "nhandan", "qdnd", "cand", "znews", "laodong", "tienphong", "kenh14",
                "bbc", "nytimes", "reuters", "apnews", "afp", "cnn", "theguardian",
                "washingtonpost", "wsj", "news", "press", "post", "times"
            ])

            # SearXNG có thể trả về 'publishedDate'
            date = r.get("publishedDate") or r.get("date") or None

            all_items.append({
                "title": title,
                "link": link,
                "snippet": snippet,
                "pagemap": {},
                "date": date,
                "is_news_site": is_news_site,
                "source_tier": _source_tier(domain),
            })

    def _ingest_ddg(results):
        """Ingest results từ DuckDuckGo format."""
        for r in results:
            link = r.get("href")
            if not link or link in seen:
                continue
            seen.add(link)

            snippet = r.get("body") or ""
            title = r.get("title") or ""
            if len(snippet) < 30:
                continue

            domain = urlparse(link).netloc.lower().replace("www.", "")
            is_news_site = any(kw in domain for kw in [
                "vnexpress", "dantri", "tuoitre", "thanhnien", "vietnamnet", "vtv", "vov",
                "nhandan", "qdnd", "cand", "znews", "laodong", "tienphong", "kenh14",
                "bbc", "nytimes", "reuters", "apnews", "afp", "cnn", "theguardian",
                "washingtonpost", "wsj", "news", "press", "post", "times"
            ])

            all_items.append({
                "title": title,
                "link": link,
                "snippet": snippet,
                "pagemap": {},
                "date": r.get("date") or None,
                "is_news_site": is_news_site,
                "source_tier": _source_tier(domain),
            })

    # Tìm kiếm chính qua SearXNG
    searxng_results = _run_searxng(query, time_range)
    
    if searxng_results is None:
        # SearXNG lỗi -> Fallback sang DuckDuckGo
        use_ddg_fallback = True
        _ingest_ddg(_run_ddg_fallback(query, time_range))
    else:
        _ingest_searxng(searxng_results)

    # Nếu ít kết quả, thử các query bổ sung
    if len(all_items) < 5:
        enhanced_queries = [
            f"{text_input} news",
            f"tin tức {text_input}",
            f"{text_input} mới nhất",
        ]
        for eq in enhanced_queries[:2]:
            if len(all_items) >= 10:
                break
            tl = "w" if any(kw in eq.lower() for kw in ["mới nhất", "latest", "recent", "mới"]) else "m"
            
            if use_ddg_fallback:
                _ingest_ddg(_run_ddg_fallback(eq, tl))
            else:
                additional_results = _run_searxng(eq, tl)
                if additional_results is None:
                    # SearXNG failed mid-search -> Switch to DDG
                    use_ddg_fallback = True
                    _ingest_ddg(_run_ddg_fallback(eq, tl))
                else:
                    _ingest_searxng(additional_results)
            
            if len(all_items) >= 10:
                break

    all_items.sort(key=_sort_key)

    for item in all_items:
        item.pop("is_news_site", None)
        item.pop("source_tier", None)

    source = "DuckDuckGo (fallback)" if use_ddg_fallback else "SearXNG (Google)"
    print(f"📊 {source}: Tổng cộng {len(all_items)} bằng chứng.")
    return all_items[:MAX_RESULTS]
