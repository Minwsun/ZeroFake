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
    Cải thiện để tìm kiếm tốt hơn các sự kiện đã xảy ra.
    """

    print(f"Đang gọi DuckDuckGo Search (thay thế Google CSE) cho: {text_input}")
    all_items = []
    seen_urls = set()

    try:
        # Thêm timeout cho DuckDuckGo search
        with DDGS() as ddgs:
            # Tăng max_results để lấy nhiều kết quả hơn (đặc biệt cho sự kiện đã xảy ra)
            results = ddgs.text(
                keywords=text_input,
                region='vi-vn',
                safesearch='off',
                timelimit=None,
                max_results=15  # Tăng từ 10 lên 15 để có nhiều snippet hơn cho sự kiện đã xảy ra
            )

            if not results:
                print("DuckDuckGo Search: Không tìm thấy kết quả.")
                return []

            for r in results:
                link = r.get('href', '')
                # Tránh trùng lặp URL
                if link in seen_urls:
                    continue
                seen_urls.add(link)
                
                snippet = r.get('body', '')
                title = r.get('title', '')
                
                # Cải thiện snippet: Nếu snippet quá ngắn, kết hợp với title
                if len(snippet) < 50 and title:
                    snippet = f"{title}. {snippet}".strip()
                
                # Ưu tiên snippet dài hơn (có nhiều thông tin hơn)
                if len(snippet) < 30:
                    continue  # Bỏ qua snippet quá ngắn
                
                all_items.append({
                    'title': title,
                    'link': link,
                    'snippet': snippet,  # Snippet đã được cải thiện
                    'pagemap': {}
                })
            
            # Nếu không có đủ kết quả, thử tìm kiếm với các biến thể
            if len(all_items) < 5:
                # Thử thêm từ khóa "tin tức" hoặc "news"
                enhanced_queries = [
                    f"{text_input} tin tức",
                    f"{text_input} news",
                    f"tin tức {text_input}"
                ]
                
                for enhanced_query in enhanced_queries[:2]:  # Chỉ thử 2 queries đầu
                    try:
                        enhanced_results = ddgs.text(
                            keywords=enhanced_query,
                            region='vi-vn',
                            safesearch='off',
                            timelimit=None,
                            max_results=5
                        )
                        
                        for r in enhanced_results or []:
                            link = r.get('href', '')
                            if link not in seen_urls:
                                seen_urls.add(link)
                                snippet = r.get('body', '')
                                title = r.get('title', '')
                                
                                if len(snippet) < 50 and title:
                                    snippet = f"{title}. {snippet}".strip()
                                
                                if len(snippet) >= 30:
                                    all_items.append({
                                        'title': title,
                                        'link': link,
                                        'snippet': snippet,
                                        'pagemap': {}
                                    })
                                    
                                    if len(all_items) >= 10:
                                        break
                        
                        if len(all_items) >= 10:
                            break
                    except Exception as e:
                        print(f"DuckDuckGo Search: Lỗi khi tìm kiếm với query '{enhanced_query}': {e}")
                        continue

    except Exception as e:
        print(f"Lỗi khi gọi DuckDuckGo Search: {e}")
        return []

    print(f"DuckDuckGo Search: Tìm thấy {len(all_items)} bằng chứng.")
    return all_items

