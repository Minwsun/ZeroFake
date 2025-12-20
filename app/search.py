import os
import re
import json
from datetime import datetime
from urllib.parse import urlparse

from duckduckgo_search import DDGS
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

MAX_RESULTS = 40  # Tăng từ 20 để thu thập nhiều evidence hơn
_TRUSTED_DOMAINS_CACHE = None

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
        'coindesk.com', 'apple.com', 'microsoft.com', 'google.com',
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


def call_google_search(text_input: str, site_query_string: str) -> list:
    """
    Enhanced DuckDuckGo search with:
    1. Multi-region search (Vietnamese + Worldwide)
    2. Smart query cleaning
    3. English search for international events
    """
    print(f"Đang gọi DuckDuckGo Search cho: {text_input}")
    
    # Clean the query first
    cleaned_input = _clean_query(text_input)
    query_vi = _ensure_news_keyword(cleaned_input)
    
    # Determine timelimit
    timelimit = None  # No time limit for broader results
    if any(kw in query_vi.lower() for kw in ["mới nhất", "latest", "recent", "hôm nay", "today"]):
        timelimit = "w"

    all_items = []
    seen = set()

    def _run_ddg(q: str, tl: str | None, region: str = "vi-vn"):
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
            print(f"DuckDuckGo Search lỗi ({region}): {exc}")
            return []

    def _ingest(results):
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
                "washingtonpost", "wsj", "news", "press", "post", "times",
                "techcrunch", "theverge", "wired", "engadget", "cnet",
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

    # 1. Search Vietnamese sources
    print(f"  [DDG] Searching Vietnamese: {query_vi[:60]}...")
    _ingest(_run_ddg(query_vi, timelimit, region="vi-vn"))

    # 2. Search worldwide (wt-wt) for international reach
    print(f"  [DDG] Searching Worldwide: {cleaned_input[:60]}...")
    _ingest(_run_ddg(cleaned_input, timelimit, region="wt-wt"))

    # 3. If international event, also search in English
    if _is_international_event(text_input):
        en_query = _extract_english_query(cleaned_input)
        if en_query and len(en_query) > 10:
            print(f"  [DDG] Searching English: {en_query[:60]}...")
            _ingest(_run_ddg(en_query, timelimit, region="wt-wt"))

    # 4. Fallback enhanced queries if still < 5 results
    if len(all_items) < 5:
        enhanced_queries = [
            f"{cleaned_input} confirmed official",
            f"{cleaned_input} news",
        ]
        for eq in enhanced_queries:
            if len(all_items) >= 10:
                break
            _ingest(_run_ddg(eq, None, region="wt-wt"))

    all_items.sort(key=_sort_key)

    for item in all_items:
        item.pop("is_news_site", None)
        item.pop("source_tier", None)

    print(f"DuckDuckGo Search: Tìm thấy {len(all_items)} bằng chứng.")
    return all_items[:MAX_RESULTS]
