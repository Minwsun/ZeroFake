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
            # Ưu tiên kết quả mới nhất: nếu query có "mới nhất" hoặc "latest", ưu tiên tuần gần đây
            timelimit = 'w' if any(kw in optimized_query.lower() for kw in ['mới nhất', 'latest', 'recent', 'mới']) else 'm'
            results = ddgs.text(
                keywords=optimized_query,
                region='vi-vn',
                safesearch='off',
                timelimit=timelimit,  # Ưu tiên kết quả trong tuần/tháng gần đây (mới nhất)
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
            
            # SẮP XẾP: ưu tiên nguồn chính thống & trang báo mới nhất
            # 1. Ưu tiên domain chính thống (báo lớn, .gov, tổ chức quốc tế)
            # 2. Trong cùng tier, ưu tiên trang báo (is_news_site = True)
            # 3. Ưu tiên kết quả có ngày mới hơn
            from datetime import datetime
            from urllib.parse import urlparse
            import os
            import json

            _DDG_TRUSTED_DOMAINS_CACHE = None

            def _load_trusted_domains_ddg():
                nonlocal _DDG_TRUSTED_DOMAINS_CACHE
                if _DDG_TRUSTED_DOMAINS_CACHE is not None:
                    return _DDG_TRUSTED_DOMAINS_CACHE

                tier0_default = {
                    'chinhphu.vn', 'moh.gov.vn', 'moet.gov.vn', 'mof.gov.vn',
                    'sbv.gov.vn', 'vncert.gov.vn',
                    'who.int', 'un.org', 'worldbank.org', 'imf.org', 'ec.europa.eu',
                    'reuters.com', 'apnews.com', 'afp.com', 'bbc.com', 'nytimes.com',
                    'theguardian.com', 'washingtonpost.com', 'wsj.com', 'ft.com',
                    'vnexpress.net', 'dantri.com.vn', 'tuoitre.vn', 'thanhnien.vn',
                    'vietnamnet.vn', 'vtv.vn', 'vov.vn', 'nhandan.vn', 'qdnd.vn',
                    'cand.com.vn', 'laodong.vn', 'tienphong.vn', 'zingnews.vn',
                }
                tier1_default = {
                    'bloomberg.com', 'cnbc.com', 'forbes.com', 'yahoo.com',
                    'marketwatch.com', 'nature.com', 'science.org', 'sciencemag.org',
                    'techcrunch.com', 'wired.com', 'theverge.com', 'engadget.com',
                    'pcmag.com', 'cnet.com', 'cointelegraph.com', 'coindesk.com',
                }

                tier0 = {d.lower() for d in tier0_default}
                tier1 = {d.lower() for d in tier1_default}

                json_path = os.path.join(os.path.dirname(__file__), "trusted_domains.json")
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    extra_tier0 = data.get("tier0") or []
                    extra_tier1 = data.get("tier1") or []
                    tier0.update(d.lower() for d in extra_tier0 if isinstance(d, str))
                    tier1.update(d.lower() for d in extra_tier1 if isinstance(d, str))
                except FileNotFoundError:
                    pass
                except Exception as e:
                    print(f"WARNING: Cannot load trusted_domains.json for DDG: {type(e).__name__}: {e}")

                _DDG_TRUSTED_DOMAINS_CACHE = (tier0, tier1)
                return _DDG_TRUSTED_DOMAINS_CACHE

            def _source_tier_for_ddg(item):
                tier0, tier1 = _load_trusted_domains_ddg()
                domain = urlparse(item.get('link', '')).netloc.lower().replace('www.', '')
                if domain.endswith(('.gov', '.gov.vn')):
                    return 0
                if domain in tier0:
                    return 0
                if domain in tier1:
                    return 1

                news_keywords = ("news", "press", "times", "post", "journal", "tribune", "herald")
                business_keywords = ("finance", "money", "market", "stock", "economy", "business")
                weather_keywords = ("weather", "climate", "meteo", "forecast")
                sports_keywords = ("sport", "sports", "soccer", "football", "basketball", "tennis", "fifa", "uefa")
                tech_keywords = ("tech", "technology", "android", "apple", "pcmag", "gsmarena", "hardware")
                science_keywords = ("science", "nature", "sciencemag", "research", "academy")

                if any(kw in domain for kw in news_keywords):
                    return 1
                if any(kw in domain for kw in business_keywords):
                    return 1
                if any(kw in domain for kw in weather_keywords):
                    return 1
                if any(kw in domain for kw in sports_keywords):
                    return 1
                if any(kw in domain for kw in tech_keywords):
                    return 1
                if any(kw in domain for kw in science_keywords):
                    return 1

                return 2

            def sort_key(item):
                source_tier = _source_tier_for_ddg(item)
                is_news = item.get('is_news_site', False)
                date_str = item.get('date')
                date_score = 0
                if date_str:
                    try:
                        date_obj = datetime.strptime(date_str[:10], '%Y-%m-%d')
                        date_score = date_obj.timestamp()
                    except Exception:
                        pass
                # tier thấp hơn tốt hơn, news tốt hơn, ngày mới hơn tốt hơn
                return (source_tier, not is_news, -date_score)

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
                        # Ưu tiên kết quả mới nhất cho enhanced queries
                        enhanced_timelimit = 'w' if any(kw in enhanced_query.lower() for kw in ['mới nhất', 'latest', 'recent', 'mới']) else 'm'
                        enhanced_results = ddgs.text(
                            keywords=enhanced_query,
                            region='vi-vn',
                            safesearch='off',
                            timelimit=enhanced_timelimit,  # Ưu tiên kết quả mới nhất
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

