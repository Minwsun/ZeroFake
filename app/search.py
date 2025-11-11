# 22520876-NguyenNhatMinh
"""
Module 2a: (SỬA ĐỔI) Thay thế Google CSE API
bằng DuckDuckGo Search để không bị giới hạn quota.
"""
import os
from dotenv import load_dotenv
from duckduckgo_search import DDGS


load_dotenv()


# Biến toàn cục (Giữ lại để app/main.py không lỗi khi import)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")


def get_site_query(config_path="config.json") -> str:
    """
    (Giữ nguyên)
    Trả về chuỗi rỗng để tìm kiếm trên toàn bộ web.
    """
    return ""


def call_google_search(text_input: str, site_query_string: str) -> list:
    """
    (SỬA ĐỔI HOÀN TOÀN)
    Hàm này giờ đây gọi DuckDuckGo Search (DDGS) thay vì Google.
    Nó trả về kết quả dưới định dạng giống Google API để tương thích.
    """

    print(f"Đang gọi DuckDuckGo Search (thay thế Google CSE) cho: {text_input}")
    all_items = []

    try:
        # Thêm timeout cho DuckDuckGo search
        with DDGS() as ddgs:
            # Tăng max_results để lấy nhiều kết quả hơn (đặc biệt cho thời tiết)
            results = ddgs.text(
                keywords=text_input,
                region='vi-vn',
                safesearch='off',
                timelimit=None,
                max_results=10  # Tăng từ 5 lên 10 để có nhiều snippet hơn
            )

            if not results:
                print("DuckDuckGo Search: Không tìm thấy kết quả.")
                return []

            for r in results:
                snippet = r.get('body', '')
                # Nếu snippet quá ngắn, thử lấy thêm thông tin từ title
                if len(snippet) < 50 and r.get('title'):
                    snippet = f"{r.get('title')}. {snippet}".strip()
                
                all_items.append({
                    'title': r.get('title'),
                    'link': r.get('href'),
                    'snippet': snippet,  # Snippet đã được cải thiện
                    'pagemap': {}
                })

    except Exception as e:
        print(f"Lỗi khi gọi DuckDuckGo Search: {e}")
        return []

    print(f"DuckDuckGo Search: Tìm thấy {len(all_items)} bằng chứng.")
    return all_items

