# 22520876-NguyenNhatMinh
"""
Module 2b: Source Ranker 
"""
from typing import Optional, Dict
from urllib.parse import urlparse
from datetime import datetime


SOURCE_RANKER_CONFIG: Dict[str, float] = {"default": 0.6}

WEATHER_DOMAINS = {
    "weather.com",
    "accuweather.com",
    "windy.com",
    "windy.app",
    "ventusky.com",
    "meteoblue.com",
    "yr.no",
    "nchmf.gov.vn",
    "bom.gov.au",
    "metoffice.gov.uk",
    "open-meteo.com",
    "openweathermap.org",
    "thoitiet.vn",
    "dubaothoitiet.info",
    "wunderground.com",
    "weather.gov",
    "weatherchannel.com",
}

WEATHER_KEYWORDS = [
    "weather",
    "forecast",
    "accuweather",
    "windy",
    "meteoblue",
    "ventusky",
    "yr.no",
    "thoitiet",
    "nchmf",
    "metoffice",
    "bom.gov",
]


def _flatten_config(nested_dict: dict) -> dict:
    """
    Hàm private để làm phẳng config JSON lồng nhau.
    """
    flat_map = {}
    for key, value in nested_dict.items():
        if key.startswith("__"):  # Bỏ qua các key comment/nhãn nhóm
            if isinstance(value, dict):
                # Đệ quy vào các nhóm lồng nhau
                flat_map.update(_flatten_config(value))
            continue

        if isinstance(value, (int, float)):
            # Đây là một domain:rank
            flat_map[key] = float(value)
        elif isinstance(value, dict):
            # Đệ quy vào các nhóm lồng nhau (trường hợp không có __)
            flat_map.update(_flatten_config(value))

    return flat_map


def load_ranker_config(config_path="config.json"):
    """Tải config từ config.json và kết hợp với heuristic toàn cục."""
    global SOURCE_RANKER_CONFIG
    import json
    import os
    
    # Khởi tạo với default
    SOURCE_RANKER_CONFIG = {"default": 0.6}
    
    # Thử tải config.json
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Làm phẳng config lồng nhau
            flattened = _flatten_config(config_data)
            SOURCE_RANKER_CONFIG.update(flattened)
            print(f"Ranker: Đã tải {len(flattened)} nguồn từ config.json.")
        else:
            print(f"Ranker: Không tìm thấy {config_path}, sử dụng heuristic toàn cục.")
    except Exception as e:
        print(f"Ranker: Lỗi khi tải config.json: {e}, sử dụng heuristic toàn cục.")


# Danh sách các domain báo chí uy tín (để phát hiện domain giả)
TRUSTED_NEWS_DOMAINS = {
    "vnexpress.net", "dantri.com.vn", "tuoitre.vn", "thanhnien.vn", "vietnamnet.vn",
    "vtv.vn", "vov.vn", "nhandan.vn", "qdnd.vn", "cand.com.vn", "ttxvn.vn",
    "znews.vn", "laodong.vn", "tienphong.vn", "sggp.org.vn", "hanoimoi.com.vn",
    "kenh14.vn", "vietnamplus.vn", "baotintuc.vn", "vnanet.vn",
    "bbc.com", "nytimes.com", "reuters.com", "apnews.com", "afp.com",
    "cnn.com", "theguardian.com", "washingtonpost.com", "wsj.com"
}

# Đuôi domain đáng ngờ (thường dùng cho domain giả)
SUSPICIOUS_TLDS = {'.info', '.xyz', '.top', '.click', '.online', '.site', '.website', '.space', '.store', '.shop'}

def _is_fake_domain(domain: str) -> bool:
    """
    Phát hiện domain giả dạng báo chí.
    Trả về True nếu domain có vẻ là giả (thêm chữ, đổi đuôi, subdomain lạ).
    """
    domain_lower = domain.lower()
    
    # Kiểm tra đuôi đáng ngờ
    for tld in SUSPICIOUS_TLDS:
        if domain_lower.endswith(tld):
            # Nếu domain có tên giống báo chí nhưng dùng đuôi lạ → có thể là giả
            for trusted in TRUSTED_NEWS_DOMAINS:
                trusted_base = trusted.split('.')[0]  # Lấy phần đầu (ví dụ: "vnexpress" từ "vnexpress.net")
                if trusted_base in domain_lower and domain_lower != trusted:
                    print(f"Ranker: Phát hiện domain giả (đuôi lạ): {domain} (giống {trusted})")
                    return True
    
    # Kiểm tra domain giả bằng cách thêm chữ (ví dụ: vnexpresss.com)
    for trusted in TRUSTED_NEWS_DOMAINS:
        trusted_parts = trusted.split('.')
        if len(trusted_parts) >= 2:
            trusted_base = trusted_parts[0]  # "vnexpress"
            trusted_tld = '.' + '.'.join(trusted_parts[1:])  # ".net"
            
            # Kiểm tra nếu domain có tên giống nhưng thêm chữ hoặc đổi đuôi
            if trusted_base in domain_lower:
                # Nếu domain khác với domain uy tín → có thể là giả
                if domain_lower != trusted and domain_lower != f"www.{trusted}":
                    # Kiểm tra xem có phải là subdomain hợp lệ không
                    if not domain_lower.endswith('.' + trusted):
                        # Có thể là domain giả (thêm chữ hoặc đổi đuôi)
                        # Ví dụ: vnexpresss.com, vnexpress.vip, vnexpress.news.today
                        if len(domain_lower) > len(trusted) + 2:  # Thêm chữ
                            print(f"Ranker: Phát hiện domain giả (thêm chữ): {domain} (giống {trusted})")
                            return True
                        elif not domain_lower.endswith(trusted_tld):  # Đổi đuôi
                            print(f"Ranker: Phát hiện domain giả (đổi đuôi): {domain} (giống {trusted})")
                            return True
    
    return False


def get_rank_from_url(url: str) -> float:
    """
    Phân tích domain và subdomain để lấy score từ SOURCE_RANKER_CONFIG (đã được làm phẳng).
    Có logic phát hiện domain giả dạng báo chí.
    """
    if not SOURCE_RANKER_CONFIG:
        load_ranker_config()

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Loại bỏ www.
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Phát hiện domain giả (SCAR 2: NGUỒN)
        if _is_fake_domain(domain):
            print(f"Ranker: Domain giả được phát hiện: {domain} → rank = 0.1 (rất thấp)")
            return 0.1  # Rank rất thấp cho domain giả

        # Ưu tiên các trang dự báo thời tiết chuyên dụng (accuweather.com được ưu tiên cao nhất)
        if 'accuweather.com' in domain:
            return 0.98  # Accuweather được ưu tiên cao nhất
        if any(domain == d or domain.endswith('.' + d) for d in WEATHER_DOMAINS) or any(k in domain for k in WEATHER_KEYWORDS):
            return 0.95

        # Kiểm tra config.json trước (ưu tiên nguồn uy tín từ config)
        if domain in SOURCE_RANKER_CONFIG:
            config_score = SOURCE_RANKER_CONFIG[domain]
            if config_score >= 0.85:  # Nguồn uy tín từ config
                print(f"Ranker: Tìm thấy nguồn uy tín từ config.json: {domain} = {config_score}")
                return config_score
        
        # Kiểm tra subdomain trong config
        parts = domain.split('.')
        if len(parts) > 2:
            base_domain_2 = '.'.join(parts[-2:])
            if base_domain_2 in SOURCE_RANKER_CONFIG:
                config_score = SOURCE_RANKER_CONFIG[base_domain_2]
                if config_score >= 0.85:
                    print(f"Ranker: Tìm thấy nguồn uy tín từ config.json: {base_domain_2} = {config_score}")
                    return config_score
        
        # Domain heuristics (fallback)
        score = None

        if domain.endswith(('.gov', '.gov.vn', '.gob', '.go.jp', '.mil', '.mil.vn')):
            score = 0.92
        elif domain.endswith(('.edu', '.edu.vn', '.ac.uk', '.ac.jp', '.ac')):
            score = 0.87
        elif domain.endswith(('.int', '.org')):
            score = 0.8

        HIGH_TRUST_KEYWORDS = ['news', 'press', 'post', 'times', 'guardian', 'telegraph', 'tribune', 'herald']
        if score is None and any(keyword in domain for keyword in HIGH_TRUST_KEYWORDS):
            score = 0.78

        SOCIAL_DOMAINS = ['facebook.com', 'twitter.com', 'x.com', 'instagram.com', 'tiktok.com', 'youtube.com', 'reddit.com', 'weibo.com', 'telegram.org', 't.me']
        if any(domain.endswith(soc) or soc in domain for soc in SOCIAL_DOMAINS):
            return 0.15

        LOW_TRUST_KEYWORDS = ['blogspot', 'wordpress', 'medium.com', 'tumblr', 'substack', 'forum']
        if any(keyword in domain for keyword in LOW_TRUST_KEYWORDS):
            score = 0.3

        if score is not None:
            return score

        # Nếu là subdomain của các domain được đánh giá cao theo heuristic
        parts = domain.split('.')
        if len(parts) > 2:
            base_domain_1 = '.'.join(parts[-2:])
            if any(base_domain_1 == d for d in WEATHER_DOMAINS):
                return 0.95
            if base_domain_1.endswith(('.gov', '.edu', '.int')):
                return 0.85

        return SOURCE_RANKER_CONFIG.get("default", 0.6)
    except Exception:
        return SOURCE_RANKER_CONFIG.get("default", 0.6)


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

        # Lọc các nguồn có rank quá thấp
        if rank_score <= 0.1:
            continue

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
