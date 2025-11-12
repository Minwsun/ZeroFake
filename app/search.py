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
    ƯU TIÊN các trang báo mới nhất để có thông tin chính xác.
    """

    print(f"Đang gọi DuckDuckGo Search (thay thế Google CSE) cho: {text_input}")
    all_items = []
    seen_urls = set()

    try:
        # Thêm timeout cho DuckDuckGo search
        with DDGS() as ddgs:
            # ƯU TIÊN: Thêm từ khóa "tin tức" hoặc "news" để ưu tiên các trang báo
            # Nếu query chưa có từ khóa tin tức, tự động thêm vào
            optimized_query = text_input
            query_lower = text_input.lower()
            if not any(kw in query_lower for kw in ['tin tức', 'news', 'thông tin', 'báo', 'article']):
                # Thêm "tin tức" vào cuối query để ưu tiên các trang báo
                optimized_query = f"{text_input} tin tức"
                print(f"DuckDuckGo Search: Tối ưu hóa query thành '{optimized_query}' để ưu tiên các trang báo")
            
            # Tăng max_results để lấy nhiều kết quả hơn (đặc biệt cho sự kiện đã xảy ra)
            # Ưu tiên kết quả mới nhất bằng cách thử timelimit='m' (tháng) hoặc 'w' (tuần)
            results = ddgs.text(
                keywords=optimized_query,
                region='vi-vn',
                safesearch='off',
                timelimit='m',  # Ưu tiên kết quả trong tháng gần đây (mới nhất)
                max_results=20  # Tăng từ 15 lên 20 để có nhiều kết quả hơn
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
                
                # ƯU TIÊN: Kiểm tra xem có phải là trang báo không
                # Các domain báo chí uy tín sẽ được ưu tiên cao hơn
                from urllib.parse import urlparse
                domain = urlparse(link).netloc.lower()
                is_news_site = any(news_kw in domain for news_kw in [
                    'vnexpress', 'dantri', 'tuoitre', 'thanhnien', 'vietnamnet', 'vtv', 'vov',
                    'nhandan', 'qdnd', 'cand', 'znews', 'laodong', 'tienphong', 'kenh14',
                    'bbc', 'nytimes', 'reuters', 'apnews', 'afp', 'cnn', 'theguardian',
                    'washingtonpost', 'wsj', 'news', 'press', 'post', 'times'
                ])
                
                all_items.append({
                    'title': title,
                    'link': link,
                    'snippet': snippet,  # Snippet đã được cải thiện
                    'pagemap': {},
                    'is_news_site': is_news_site,  # Đánh dấu để sắp xếp sau
                    'date': r.get('date') or None  # Lưu ngày nếu có
                })
            
            # SẮP XẾP: Ưu tiên các trang báo mới nhất
            # 1. Ưu tiên trang báo (is_news_site = True)
            # 2. Trong cùng loại, ưu tiên kết quả có ngày mới hơn
            from datetime import datetime
            def sort_key(item):
                is_news = item.get('is_news_site', False)
                date_str = item.get('date')
                # Nếu có ngày, parse và dùng để sắp xếp (mới nhất trước)
                date_score = 0
                if date_str:
                    try:
                        # Thử parse ngày từ nhiều format
                        date_obj = datetime.strptime(date_str[:10], '%Y-%m-%d')
                        date_score = date_obj.timestamp()  # Timestamp để so sánh
                    except:
                        pass
                # Trả về tuple: (is_news, date_score) - ưu tiên news site và ngày mới hơn
                return (not is_news, -date_score)  # False (news) < True (non-news), date mới hơn (timestamp lớn hơn) ở trước
            
            all_items.sort(key=sort_key)
            
            # Loại bỏ các field không cần thiết trước khi trả về (để tương thích)
            for item in all_items:
                item.pop('is_news_site', None)
                item.pop('date', None)
            
            # Nếu không có đủ kết quả, thử tìm kiếm với các biến thể
            if len(all_items) < 5:
                # Thử các biến thể query khác (không trùng với query gốc đã có "tin tức")
                enhanced_queries = [
                    f"{text_input} news",  # Thử tiếng Anh
                    f"tin tức {text_input}",  # Đảo thứ tự
                    f"{text_input} mới nhất"  # Thêm "mới nhất"
                ]
                
                for enhanced_query in enhanced_queries[:2]:  # Chỉ thử 2 queries đầu
                    try:
                        enhanced_results = ddgs.text(
                            keywords=enhanced_query,
                            region='vi-vn',
                            safesearch='off',
                            timelimit='m',  # Ưu tiên kết quả mới nhất
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

