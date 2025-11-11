# 22520876-NguyenNhatMinh
"""
Module 2b: Source Ranker 
"""
import json
from typing import Optional, Dict
from urllib.parse import urlparse
from datetime import datetime


SOURCE_RANKER_CONFIG: Dict[str, float] = {}


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
    """
    Đọc config.json (lồng nhau) và tải vào SOURCE_RANKER_CONFIG (phẳng).
    """
    global SOURCE_RANKER_CONFIG
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            nested_config = json.load(f)

        # Làm phẳng cấu trúc
        SOURCE_RANKER_CONFIG = _flatten_config(nested_config)

        if "default" not in SOURCE_RANKER_CONFIG:
            SOURCE_RANKER_CONFIG["default"] = 0.5

        print(f"Ranker: Đã tải và làm phẳng {len(SOURCE_RANKER_CONFIG)} nguồn tin.")

    except FileNotFoundError:
        print(f"LỖI: Không tìm thấy tệp {config_path}. Sử dụng danh sách mặc định.")
        SOURCE_RANKER_CONFIG = {"default": 0.5, "vnexpress.net": 1.0, "chinhphu.vn": 1.0}
    except json.JSONDecodeError:
        print(f"LỖI: Tệp {config_path} không phải là JSON hợp lệ.")
        raise
    except Exception as e:
        print(f"LỖI không xác định khi tải ranker config: {e}")
        raise


def get_rank_from_url(url: str) -> float:
    """
    Phân tích domain và subdomain để lấy score từ SOURCE_RANKER_CONFIG (đã được làm phẳng).
    """
    if not SOURCE_RANKER_CONFIG:
        load_ranker_config()

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Loại bỏ www.
        if domain.startswith('www.'):
            domain = domain[4:]

        # 1. Thử tìm exact match
        if domain in SOURCE_RANKER_CONFIG:
            return SOURCE_RANKER_CONFIG[domain]

        # 2. Thử tìm với subdomain
        parts = domain.split('.')
        if len(parts) > 2:
            # Thử b.c.com
            base_domain_1 = '.'.join(parts[-2:])
            if base_domain_1 in SOURCE_RANKER_CONFIG:
                return SOURCE_RANKER_CONFIG[base_domain_1]

           
            base_domain_2 = '.'.join(parts[-3:])
            if base_domain_2 in SOURCE_RANKER_CONFIG:
                return SOURCE_RANKER_CONFIG[base_domain_2]

        # 3. Trả về default
        return SOURCE_RANKER_CONFIG.get("default", 0.5)
    except Exception:
        return SOURCE_RANKER_CONFIG.get("default", 0.5)


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
