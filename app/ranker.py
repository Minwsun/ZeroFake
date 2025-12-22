# 22520876-NguyenNhatMinh
"""
Module 2b: Source Ranker - Binary Classification (USABLE vs BLOCKED)
"""
from typing import Optional
from urllib.parse import urlparse
from datetime import datetime


# Suspicious TLDs often used for fake domains
SUSPICIOUS_TLDS = {'.xyz', '.top', '.click', '.online', '.site', '.website', '.space', '.store', '.shop', '.info', '.tk', '.ml', '.ga', '.cf', '.gq'}

def _is_fake_domain(domain: str) -> bool:
    """
    Detect fake/typosquatting domains.
    Returns True if domain looks like a typosquat (suspicious TLD + looks like major brand).
    """
    domain_lower = domain.lower()
    
    # Major brands/companies often targeted by typosquatters
    MAJOR_BRANDS = ['vnexpress', 'dantri', 'tuoitre', 'thanhnien', 'vtv', 'vov', 
                    'bbc', 'cnn', 'reuters', 'google', 'facebook', 'apple', 'microsoft']
    
    # Check for suspicious TLD + brand name
    for tld in SUSPICIOUS_TLDS:
        if domain_lower.endswith(tld):
            for brand in MAJOR_BRANDS:
                if brand in domain_lower:
                    print(f"Ranker: Phát hiện domain giả (typosquat): {domain}")
                    return True
    
    return False
    
    return False


def get_rank_from_url(url: str) -> float:
    """
    SIMPLIFIED BINARY RANKING: USABLE (0.8) vs BLOCKED (0.1)
    
    Philosophy: Trust most sources EXCEPT:
    - User-generated content (social media, blogs, forums)
    - Tabloids / báo lá cải (sensationalist, clickbait)
    - Anti-state / propaganda / báo chống phá
    - Unreliable / low-quality news sources
    
    USABLE (0.8): News, official, corporate, Wikipedia, etc.
    BLOCKED (0.1): Social, blog, UGC, tabloid, propaganda
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Remove www.
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # ==========================================================
        # BLOCKED SOURCES (0.1)
        # ==========================================================
        
        # 1. FAKE DOMAINS - Impersonating trusted sources
        if _is_fake_domain(domain):
            print(f"Ranker: BLOCKED (fake domain): {domain}")
            return 0.1
        
        # 2. SOCIAL MEDIA - 100% user-generated content
        SOCIAL_DOMAINS = [
            'facebook.com', 'fb.com', 'fb.watch', 'm.facebook.com',
            'twitter.com', 'x.com', 'mobile.twitter.com',
            'instagram.com', 'tiktok.com', 'youtube.com', 'youtu.be',
            'reddit.com', 'weibo.com', 'telegram.org', 't.me',
            'threads.net', 'mastodon.social', 'bsky.app',
            'linkedin.com', 'pinterest.com', 'snapchat.com',
            'zalo.me', 'zalo.vn',
        ]
        if any(domain == soc or domain.endswith('.' + soc) for soc in SOCIAL_DOMAINS):
            print(f"Ranker: BLOCKED (social media): {domain}")
            return 0.1
        
        # 3. BLOG/UGC PLATFORMS - User-written content
        BLOG_PLATFORMS = [
            'blogspot.com', 'blogger.com', 'wordpress.com', 'wordpress.org',
            'tumblr.com', 'substack.com', 'medium.com', 
            'wix.com', 'weebly.com', 'squarespace.com',
            'notion.so', 'notion.site', 'ghost.io',
            'towardsdatascience.com', 'dev.to', 'hashnode.dev',
        ]
        if any(domain == blog or domain.endswith('.' + blog) for blog in BLOG_PLATFORMS):
            print(f"Ranker: BLOCKED (blog platform): {domain}")
            return 0.1
        
        # 4. FORUMS - User discussions, not news
        FORUM_KEYWORDS = ['forum', 'community', 'discuss', 'boards', 'voz.vn', 'tinhte.vn', 'otofun']
        if any(kw in domain for kw in FORUM_KEYWORDS):
            print(f"Ranker: BLOCKED (forum): {domain}")
            return 0.1
        
        # 5. TABLOIDS / BÁO LÁ CẢI - Sensationalist, clickbait, unreliable
        TABLOID_DOMAINS = [
            # International tabloids
            'dailymail.co.uk', 'thesun.co.uk', 'mirror.co.uk', 'express.co.uk',
            'nypost.com', 'nationalenquirer.com', 'tmz.com', 'pagesix.com',
            'buzzfeed.com', 'huffpost.com', 'dailybeast.com',
            'infowars.com', 'breitbart.com', 'thegatewaypundit.com',
            
            # Vietnamese tabloids / báo lá cải
            'eva.vn', 'afamily.vn', 'ngoisao.net', '2sao.vn', 
            'gamek.vn', 'yan.vn', 'yeah1.com', 'docbao.vn',
            'webtretho.com', 'tinmoi.vn', 'tintuconline.com.vn',
            'soha.vn', 'kienthuc.net.vn', 'giadinh.net.vn',
            'anninhthudo.vn',  # Often sensationalist
            'nguoiduatin.vn', 'phapluatplus.vn',
            'congly.vn', 'baomoi.com',  # Aggregator with low quality
            'tiin.vn', '24h.com.vn',  # Clickbait heavy
            'doisongphapluat.com', 'danviet.vn',
        ]
        if any(domain == tab or domain.endswith('.' + tab) for tab in TABLOID_DOMAINS):
            print(f"Ranker: BLOCKED (tabloid/báo lá cải): {domain}")
            return 0.1
        
        # 6. ANTI-STATE / PROPAGANDA / BÁO CHỐNG PHÁ
        PROPAGANDA_DOMAINS = [
            # Anti-Vietnam government propaganda
            'rfa.org', 'rfavietnam.com', 'voatiengviet.com',
            'bbc.com/vietnamese',  # Note: bbc.com main is OK
            'nguoi-viet.com', 'vietbao.com', 'viettan.org',
            'chantroimoimedia.com', 'danchimviet.info',
            'baocalitoday.com', 'saigonnhonews.com',
            'vietbf.com', 'vietinfo.eu', 'thoibao.de',
            'luatkhoa.org', 'thevietnamese.org',
            
            # General propaganda/conspiracy sites
            'rt.com', 'sputniknews.com', 'globalresearch.ca',
            'naturalnews.com', 'zerohedge.com',
            'epochtimes.com', 'ntd.com', 'theepochtimes.com',
        ]
        if any(domain == prop or domain.endswith('.' + prop) or prop in domain for prop in PROPAGANDA_DOMAINS):
            print(f"Ranker: BLOCKED (propaganda/chống phá): {domain}")
            return 0.1
        
        # 7. UNRELIABLE / LOW QUALITY NEWS - BÁO KHÔNG UY TÍN
        UNRELIABLE_DOMAINS = [
            # Vietnamese low-quality news
            'dantricdn.com', 'img.vn',  # CDN/image hosts
            'xahoi.com.vn', 'vietnamfinance.vn',
            'petrotimes.vn', 'congan.com.vn',
            'giadinhvietnam.com', 'giaoducthoidai.vn',
            'baophapluat.vn', 'baodatviet.vn',
            
            # International unreliable
            'theonion.com', 'babylonbee.com',  # Satire (can be misleading)
            'clickhole.com', 'waterfordwhispersnews.com',
        ]
        if any(domain == unreliable or domain.endswith('.' + unreliable) for unreliable in UNRELIABLE_DOMAINS):
            print(f"Ranker: BLOCKED (unreliable/không uy tín): {domain}")
            return 0.1
        
        # 8. SUSPICIOUS TLDs with fake news history
        SUSPICIOUS_TLDS = ['.xyz', '.top', '.click', '.online', '.site', '.website', '.space', '.store', '.shop', '.info', '.tk', '.ml', '.ga', '.cf', '.gq']
        if any(domain.endswith(tld) for tld in SUSPICIOUS_TLDS):
            print(f"Ranker: BLOCKED (suspicious TLD): {domain}")
            return 0.1
        
        # ==========================================================
        # USABLE SOURCES (0.8) - Everything else
        # ==========================================================
        # News sites, official websites, corporate sites, Wikipedia, etc.
        return 0.8
        
    except Exception:
        return 0.8  # Default to usable on error


def test_query_results(query: str) -> None:
    """
    Test function to check search results - what comes back and if it's usable.
    Usage: from app.ranker import test_query_results; test_query_results("Apple Vision Pro")
    """
    from app.search import call_google_search
    
    print(f"\n{'='*60}")
    print(f"TEST QUERY: {query}")
    print(f"{'='*60}")
    
    results = call_google_search(query, "")
    
    print(f"\nFound {len(results)} results total")
    print(f"\n{'─'*60}")
    
    usable_count = 0
    blocked_count = 0
    
    for i, r in enumerate(results[:10], 1):
        url = r.get("link", "")
        title = r.get("title", "")[:50]
        snippet = r.get("snippet", "")[:80]
        
        score = get_rank_from_url(url)
        status = "✓ USABLE" if score >= 0.5 else "✗ BLOCKED"
        
        if score >= 0.5:
            usable_count += 1
        else:
            blocked_count += 1
        
        domain = urlparse(url).netloc.replace("www.", "")
        
        print(f"\n{i}. [{status}] {domain}")
        print(f"   Title: {title}...")
        print(f"   Snippet: {snippet}...")
    
    print(f"\n{'='*60}")
    print(f"SUMMARY: {usable_count} usable, {blocked_count} blocked out of top 10")
    print(f"{'='*60}\n")


def _extract_date(item: dict) -> Optional[str]:
    """
    Trích xuất ngày tháng "chịu lỗi" với nhiều định dạng khác nhau.
    Chiến lược:
    1) Duyệt TẤT CẢ metatags và nhiều key ngày phổ biến
    2) Chuẩn hoá chuỗi (bỏ mili-giây, chuẩn hoá Z, cắt timezone khi cần)
    3) Thử nhiều format ISO/VN/US + tên tháng tiếng Anh
    4) Fallback: tìm pattern trong URL/snippet
    Trả về YYYY-MM-DD hoặc None
    """
    import re
    try:
        def normalize(s: str) -> str:
            s = s.strip()
            # bỏ mili-giây và timezone dạng .123Z hoặc .123+07:00
            s = re.sub(r"\.\d{1,6}(Z|[\+\-]\d{2}:?\d{2})?$", "", s)
            # Z -> +00:00 (để fmt %z có thể xử lý)
            s = s.replace('Z', '+00:00')
            return s

        def try_parse_many(ds: str) -> Optional[str]:
            ds_norm = normalize(ds)
            fmts = [
                '%Y-%m-%dT%H:%M:%S%z',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%d %H:%M:%S',
                '%Y-%m-%d',
                '%Y/%m/%d',
                '%d/%m/%Y',
                '%m/%d/%Y',
            ]
            for fmt in fmts:
                try:
                    dt = datetime.strptime(ds_norm[:max(10, len(ds_norm))], fmt)
                    return dt.strftime('%Y-%m-%d')
                except Exception:
                    continue
            # RFC-like: Tue, 15 Nov 2024 12:45:26 GMT
            for fmt in ['%a, %d %b %Y %H:%M:%S', '%d %b %Y %H:%M:%S']:
                try:
                    dt = datetime.strptime(ds_norm[:25], fmt)
                    return dt.strftime('%Y-%m-%d')
                except Exception:
                    pass
            # Month-name patterns (English)
            month_map = {'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
                         'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12}
            patterns = [
                r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\b",
                r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),\s*(\d{4})\b",
            ]
            for pat in patterns:
                m = re.search(pat, ds_norm, flags=re.IGNORECASE)
                if m:
                    g = list(m.groups())
                    try:
                        if pat.startswith(r"\\b(\\d"):
                            d = int(g[0]); mon = month_map[g[1][:3].lower()]; y = int(g[2])
                        else:
                            mon = month_map[g[0][:3].lower()]; d = int(g[1]); y = int(g[2])
                        dt = datetime(y, mon, d)
                        return dt.strftime('%Y-%m-%d')
                    except Exception:
                        pass
            return None

        pagemap = item.get('pagemap', {})
        metatags = pagemap.get('metatags', []) or []
        candidates = []
        date_keys = [
            'article:published_time','og:published_time','date','og:updated_time',
            'article:modified_time','article:published','publishdate','pubdate',
            'datePublished','dateModified','article:created','parsely-pub-date',
            'sailthru.date','dc.date','dc.date.issued','dc.date.created'
        ]
        for meta in metatags:
            for k in date_keys:
                v = meta.get(k)
                if v:
                    candidates.append(str(v))
        for ds in candidates:
            parsed = try_parse_many(ds)
            if parsed:
                return parsed

        # URL fallback
        link = item.get('link') or ''
        url_patterns = [
            r"/(20\d{2})[\-/](\d{1,2})[\-/](\d{1,2})/",
            r"/(\d{1,2})[\-/](\d{1,2})[\-/](20\d{2})/",
        ]
        for pat in url_patterns:
            m = re.search(pat, link)
            if m:
                try:
                    g = [int(x) for x in m.groups()]
                    if pat.startswith(r"/(20"):
                        y, mo, d = g
                    else:
                        d, mo, y = g
                    dt = datetime(y, mo, d)
                    return dt.strftime('%Y-%m-%d')
                except Exception:
                    pass

        # Snippet fallback
        snippet = (item.get('snippet') or '')
        snippet_patterns = [
            r"\b(20\d{2})[\-/](\d{1,2})[\-/](\d{1,2})\b",
            r"\b(\d{1,2})[\-/](\d{1,2})[\-/](20\d{2})\b",
        ]
        for pat in snippet_patterns:
            m = re.search(pat, snippet)
            if m:
                try:
                    g = [int(x) for x in m.groups()]
                    if pat.startswith(r"\\b(20"):
                        y, mo, d = g
                    else:
                        d, mo, y = g
                    dt = datetime(y, mo, d)
                    return dt.strftime('%Y-%m-%d')
                except Exception:
                    pass

        return None
    except Exception:
        return None


def process_search_results(search_items: list) -> str:
    """
    Xử lý kết quả tìm kiếm: xếp hạng, trích xuất ngày, format JSON.
    """
    evidence_list = []

    if not search_items:
        return json.dumps([])

    for item in search_items:
        link = item.get('link', '')
        if not link:
            continue

        snippet = item.get('snippet', '').replace('\n', ' ').replace('\r', ' ')

        # Lấy rank score
        rank_score = get_rank_from_url(link)

        # REMOVED FILTER: Giữ tất cả nguồn, không lọc theo rank
        # if rank_score <= 0.1:
        #     continue

        # Trích xuất ngày
        date_str = _extract_date(item)

        # Tạo evidence dict
        evidence = {
            "nguon": urlparse(link).netloc.replace('www.', ''),
            "url": link,
            "tom_tat": snippet,
            "diem_uy_tin": rank_score,
            "ngay_dang": date_str
        }

        evidence_list.append(evidence)

    # Sắp xếp theo diem uy tin 
    evidence_list.sort(key=lambda x: x['diem_uy_tin'], reverse=True)

  
    return json.dumps(evidence_list, indent=2, ensure_ascii=False)
