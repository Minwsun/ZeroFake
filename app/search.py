# 22520876-NguyenNhatMinh
"""
Module 2a: Google Search API
"""
import os
import json
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

load_dotenv()

# Biến toàn cục
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")


def get_site_query(config_path="config.json") -> str:
    """
    Đọc config.json và tạo chuỗi query cho các site có rank >= 0.9.
    Trả về chuỗi rỗng nếu không có site nào để tránh sinh "()" trong query.
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    high_rank_sites = [site for site, rank in config.items() if isinstance(rank, (int, float)) and rank >= 0.9]
    if not high_rank_sites:
        return ""
    site_query_parts = [f"site:{site}" for site in high_rank_sites]
    site_query_string = " OR ".join(site_query_parts)
    return f"({site_query_string})"


def call_google_search(text_input: str, site_query_string: str) -> list:
    """
    Gọi Google Search API ở chế độ tiết kiệm quota (single-pass):
    - Chỉ 1 lệnh gọi CSE cho mỗi lần kiểm tra, num=1.
    - Ưu tiên precise query: "<text>" + site filter (nếu có); nếu không có site filter thì chỉ dùng "<text>".
    """
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        raise ValueError("GOOGLE_API_KEY hoặc GOOGLE_CSE_ID chưa được cấu hình trong .env")
    
    service = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)
    
    all_items = []
    seen_urls = set()

    def add_items(items):
        if not items:
            return
        if 'items' in items:
            for item in items['items']:
                link = item.get('link')
                if link and link not in seen_urls:
                    all_items.append(item)
                    seen_urls.add(link)

    # Single-pass precise query with num=1
    try:
        if site_query_string:
            precise_query = f'"{text_input}" {site_query_string}'
        else:
            precise_query = f'"{text_input}"'
        result_precise = service.cse().list(q=precise_query, cx=GOOGLE_CSE_ID, num=1, sort='date').execute()
        add_items(result_precise)
    except HttpError as e:
        if getattr(e, 'resp', None) and getattr(e.resp, 'status', None) == 429:
            print("CSE 429 in single-pass query - quota exceeded.")
            return all_items
        print(f"Lỗi trong single-pass query: {e}")
    except Exception as e:
        print(f"Lỗi trong single-pass query: {e}")

    print(f"Google Search (single-pass): Tìm thấy {len(all_items)} bằng chứng.")
    return all_items

