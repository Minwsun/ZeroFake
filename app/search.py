import os
import json
from datetime import datetime
from urllib.parse import urlparse

from duckduckgo_search import DDGS
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

MAX_RESULTS = 20
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


def call_google_search(text_input: str, site_query_string: str) -> list:
    print(f"Đang gọi DuckDuckGo Search cho: {text_input}")
    query = _ensure_news_keyword(text_input)
    timelimit = "w" if any(kw in query.lower() for kw in ["mới nhất", "latest", "recent", "mới"]) else "m"

    all_items = []
    seen = set()

    def _run_ddg(q: str, tl: str):
        try:
            with DDGS() as ddgs:
                return ddgs.text(
                    keywords=q,
                    region="vi-vn",
                    safesearch="off",
                    timelimit=tl,
                    max_results=MAX_RESULTS,
                ) or []
        except Exception as exc:
            print(f"DuckDuckGo Search lỗi: {exc}")
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

    _ingest(_run_ddg(query, timelimit))

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
            _ingest(_run_ddg(eq, tl))
            if len(all_items) >= 10:
                break

    all_items.sort(key=_sort_key)

    for item in all_items:
        item.pop("is_news_site", None)
        item.pop("source_tier", None)

    print(f"DuckDuckGo Search: Tìm thấy {len(all_items)} bằng chứng.")
    return all_items[:MAX_RESULTS]
