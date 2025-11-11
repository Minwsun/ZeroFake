# 22520876-NguyenNhatMinh
"""
Module 2a: Google Search API
"""
import os
import json
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

# Biến toàn cục
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")


def get_site_query(config_path="config.json") -> str:
    """
    Đọc config.json và tạo chuỗi query cho các site có rank >= 0.9.
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Lọc các site có rank >= 0.9
    high_rank_sites = [site for site, rank in config.items() if isinstance(rank, (int, float)) and rank >= 0.9]
    
    # Tạo chuỗi query
    site_query_parts = [f"site:{site}" for site in high_rank_sites]
    site_query_string = " OR ".join(site_query_parts)
    
    return f"({site_query_string})"


def call_google_search(text_input: str, site_query_string: str) -> list:
    """
    Gọi Google Search API với logic 3-pass (v3.8) linh hoạt:
    - Lần 1: Precise query (chính xác) trên các trang uy tín (tìm tin đính chính).
    - Lần 2: Broad query (rộng) trên TOÀN BỘ WEB (tìm tin gốc/tin đồn).
    - Lần 3: Keyword query (từ khóa) trên các trang uy tín (nếu 2 lần đầu thất bại).
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

    # Pass 1: Precise on trusted
    try:
        precise_query = f'"{text_input}" {site_query_string}'
        result_precise = service.cse().list(q=precise_query, cx=GOOGLE_CSE_ID, num=3, sort='date').execute()
        add_items(result_precise)
    except Exception as e:
        print(f"Lỗi trong precise query: {e}")

    # Pass 2: Broad on entire web
    try:
        broad_query = f"{text_input}"
        result_broad = service.cse().list(q=broad_query, cx=GOOGLE_CSE_ID, num=5, sort='date').execute()
        add_items(result_broad)
    except Exception as e:
        print(f"Lỗi trong broad query: {e}")

    # Pass 3: Keyword on trusted if still empty
    if not all_items:
        try:
            keyword_query = " ".join(text_input.split()[:50]) + f" {site_query_string}"
            result_keyword = service.cse().list(q=keyword_query, cx=GOOGLE_CSE_ID, num=5, sort='date').execute()
            add_items(result_keyword)
        except Exception as e:
            print(f"Lỗi trong keyword query: {e}")

    print(f"Google Search (v3.8): Tìm thấy {len(all_items)} bằng chứng.")
    return all_items

