# app/agent_planner.py
import os
import json
import re
from dotenv import load_dotenv
from typing import Optional, Tuple

from app.weather import classify_claim
from app.model_clients import (
    call_gemini_model,
    call_groq_chat_completion,
    call_openrouter_chat_completion,
    call_compound_model,
    ModelClientError,
)

# Import geopy cho geocoding toàn cầu
try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    GEOPY_AVAILABLE = True
except ImportError:
    GEOPY_AVAILABLE = False
    print("WARNING: geopy is not installed. Run: pip install geopy")

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PLANNER_PROMPT = ""

# Từ khóa địa điểm toàn cầu (nhiều ngôn ngữ)
LOCATION_KEYWORDS = {
    # Tiếng Anh
    "city", "province", "state", "county", "district", "region", "town", "village", "borough",
    "capital", "metropolis", "municipality", "prefecture", "territory", "republic", "kingdom",
    # Tiếng Việt
    "thành phố", "tỉnh", "quận", "huyện", "thị xã", "xã", "phường", "thị trấn", "thủ đô",
    # Tiếng Pháp
    "ville", "province", "région", "département", "commune", "préfecture",
    # Tiếng Tây Ban Nha
    "ciudad", "provincia", "estado", "región", "municipio", "capital",
    # Tiếng Đức
    "stadt", "provinz", "bundesland", "region", "gemeinde",
    # Tiếng Nhật
    "shi", "ken", "to", "fu", "do", "gun", "cho", "son",
    # Tiếng Trung
    "市", "省", "县", "区", "州", "府",
    # Tiếng Hàn
    "시", "도", "군", "구", "읍", "면",
    # Các từ khóa chung
    "port", "bay", "island", "islands", "peninsula", "mountain", "valley", "river", "lake",
    "hải cảng", "vịnh", "đảo", "bán đảo", "núi", "thung lũng", "sông", "hồ"
}

# Danh sách địa danh phổ biến (chỉ dùng làm fallback/ưu tiên, không giới hạn)
COMMON_LOCATIONS = [
    # Việt Nam
    "Thành phố Hồ Chí Minh", "Hồ Chí Minh", "Ho Chi Minh City",
    "Hà Nội", "Hanoi",
    "Đà Nẵng", "Da Nang",
    "Hải Phòng", "Hai Phong",
    "Cần Thơ", "Can Tho",
    # Quốc tế (một số thành phố lớn)
    "New York", "New York City", "Los Angeles", "San Francisco", "Chicago", "Houston",
    "London", "Paris", "Tokyo", "Seoul", "Beijing", "Shanghai", "Moscow", "Berlin",
    "Madrid", "Rome", "Bangkok", "Singapore", "Sydney", "Melbourne", "Toronto", "Vancouver"
]

# Mapping địa danh Việt Nam sang tiếng Anh (chỉ một số phổ biến, fallback)
LOCATION_EN_MAP = {
    "Thành phố Hồ Chí Minh": "Ho Chi Minh City",
    "Hồ Chí Minh": "Ho Chi Minh City",
    "Hà Nội": "Hanoi",
    "Đà Nẵng": "Da Nang",
    "Hải Phòng": "Hai Phong",
    "Cần Thơ": "Can Tho",
}

# Cache đơn giản cho geocoding (tránh gọi API nhiều lần)
_location_cache = {}


def _geocode_location_online(location_name: str) -> Optional[Tuple[str, str]]:
    """
    Sử dụng geopy/Nominatim để tìm kiếm địa danh toàn cầu online.
    Hỗ trợ nhận diện địa danh từ mọi quốc gia trên thế giới.
    Trả về (tên chuẩn hóa, tên tiếng Anh) hoặc None nếu không tìm thấy.
    
    Args:
        location_name: Tên địa danh cần tìm (có thể là tiếng Việt, tiếng Anh, hoặc bất kỳ ngôn ngữ nào)
        
    Returns:
        Tuple[str, str] | None: (tên chuẩn hóa, tên tiếng Anh) hoặc None
    """
    if not GEOPY_AVAILABLE:
        return None
    
    # Kiểm tra cache
    location_key = location_name.lower().strip()
    if location_key in _location_cache:
        return _location_cache[location_key]
    
    try:
        # Sử dụng Nominatim (OpenStreetMap) - free, không cần API key, hỗ trợ toàn cầu
        geolocator = Nominatim(user_agent="ZeroFake-FactChecker/1.0")
        
        # Thử nhiều cách tìm kiếm để tăng độ chính xác
        location = None
        
        # Cách 1: Tìm kiếm trực tiếp với tên gốc
        try:
            location = geolocator.geocode(location_name, timeout=10, language='en', exactly_one=True)
        except Exception as e:
            print(f"Geopy: Error geocoding '{location_name}': {e}")
        
        # Cách 2: Nếu không tìm thấy, thử thêm "city" hoặc "thành phố" vào cuối
        if not location:
            try:
                # Thử với "city" (tiếng Anh)
                if "city" not in location_name.lower() and "thành phố" not in location_name.lower():
                    location = geolocator.geocode(f"{location_name}, city", timeout=10, language='en', exactly_one=True)
            except Exception:
                pass
        
        # Cách 3: Nếu vẫn không tìm thấy, thử tìm kiếm rộng hơn (không exactly_one)
        if not location:
            try:
                results = geolocator.geocode(location_name, timeout=10, language='en', exactly_one=False)
                if results and len(results) > 0:
                    # Chọn kết quả đầu tiên (có thể cải thiện logic chọn sau)
                    location = results[0]
            except Exception:
                pass
        
        if location:
            # Lấy thông tin chi tiết từ address
            address_parts = location.address.split(',')
            
            # Tên chính (thường là phần đầu)
            normalized_name = address_parts[0].strip()
            
            # Tên tiếng Anh: thử lấy từ raw (nếu có) hoặc dùng normalized_name
            english_name = normalized_name
            
            # Nếu có raw data, thử lấy tên tiếng Anh từ đó
            if hasattr(location, 'raw') and location.raw:
                raw_data = location.raw
                # Thử lấy tên từ display_name hoặc name
                if 'display_name' in raw_data:
                    display_name = raw_data['display_name']
                    # Lấy phần đầu của display_name (thường là tên chính)
                    english_name = display_name.split(',')[0].strip()
                elif 'name' in raw_data:
                    english_name = raw_data['name']
            
            # Kiểm tra xem có phải là địa danh hợp lệ không (có tọa độ)
            if location.latitude and location.longitude:
                # Lưu vào cache
                result = (normalized_name, english_name)
                _location_cache[location_key] = result
                print(f"Geopy: Found '{normalized_name}' (EN: '{english_name}') at [{location.latitude}, {location.longitude}]")
                return result
            else:
                print(f"Geopy: Found '{normalized_name}' but no valid coordinates")
                return None
        else:
            print(f"Geopy: Location '{location_name}' not found")
            return None
            
    except GeocoderTimedOut:
        print(f"Geopy: Timeout searching for '{location_name}'")
        return None
    except GeocoderServiceError as e:
        print(f"Geopy: Service error searching for '{location_name}': {e}")
        return None
    except Exception as e:
        print(f"Geopy: Unexpected error searching for '{location_name}': {type(e).__name__}: {e}")
        return None
    
    return None


def _get_english_location_name(location_name: str) -> str:
    """
    Lấy tên tiếng Anh của địa danh.
    Ưu tiên: LOCATION_EN_MAP -> geopy online -> giữ nguyên
    """
    # Thử map cục bộ trước
    if location_name in LOCATION_EN_MAP:
        return LOCATION_EN_MAP[location_name]
    
    # Thử geocoding online
    if GEOPY_AVAILABLE:
        result = _geocode_location_online(location_name)
        if result:
            return result[1]  # Tên tiếng Anh
    
    # Fallback: giữ nguyên hoặc xử lý đơn giản
    # Nếu có "Thành phố" hoặc "City", rút gọn
    if "thành phố" in location_name.lower():
        parts = location_name.split()
        parts_filtered = [p for p in parts if p.lower() not in ["thành", "phố"]]
        if parts_filtered:
            return " ".join(parts_filtered)
    
    return location_name


def _normalize_phrase(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _get_date_for_query(relative_time: str | None, explicit_date: str | None, days_ahead: int | None = None) -> tuple[str, str]:
    """
    Chuyển đổi relative_time hoặc explicit_date thành date cụ thể (DD/MM/YYYY) và time string cho query.
    
    Args:
        relative_time: Chuỗi thời gian tương đối (ví dụ: "ngày mai", "chiều mai", "hôm nay")
        explicit_date: Ngày cụ thể (YYYY-MM-DD)
        days_ahead: Số ngày sau hôm nay (nếu có)
    
    Returns:
        tuple[str, str]: (date_str DD/MM/YYYY, time_str với relative_time đầy đủ nếu có)
    """
    from datetime import datetime, timedelta
    
    today = datetime.now()
    time_str = ""
    
    # Nếu có explicit_date (YYYY-MM-DD), chuyển sang DD/MM/YYYY
    if explicit_date:
        try:
            date_obj = datetime.strptime(explicit_date, '%Y-%m-%d')
            date_str = date_obj.strftime('%d/%m/%Y')
            # Giữ nguyên relative_time nếu có để thêm vào query
            if relative_time:
                time_str = relative_time
            return (date_str, time_str)
        except Exception:
            pass
    
    # Nếu có relative_time, chuyển đổi
    if relative_time:
        relative_lower = relative_time.lower()
        relative_original = relative_time  # Giữ nguyên để dùng trong query
        
        # Hôm nay
        if "hôm nay" in relative_lower or "today" in relative_lower:
            date_str = today.strftime('%d/%m/%Y')
            time_str = relative_original  # Giữ "hôm nay" hoặc "chiều hôm nay"
            return (date_str, time_str)
        
        # Ngày mai
        if "ngày mai" in relative_lower or "tomorrow" in relative_lower:
            tomorrow = today + timedelta(days=1)
            date_str = tomorrow.strftime('%d/%m/%Y')
            # Giữ nguyên relative_time để có "chiều mai 13/11/2025"
            time_str = relative_original  # Giữ "ngày mai" hoặc "chiều mai"
            return (date_str, time_str)
        
        # Hôm qua
        if "hôm qua" in relative_lower or "yesterday" in relative_lower:
            yesterday = today - timedelta(days=1)
            date_str = yesterday.strftime('%d/%m/%Y')
            time_str = relative_original
            return (date_str, time_str)
        
        # Tuần tới
        if "tuần tới" in relative_lower or "next week" in relative_lower:
            next_week = today + timedelta(days=7)
            date_str = next_week.strftime('%d/%m/%Y')
            time_str = relative_original
            return (date_str, time_str)
    
    # Nếu có days_ahead
    if days_ahead is not None:
        target_date = today + timedelta(days=days_ahead)
        date_str = target_date.strftime('%d/%m/%Y')
        if relative_time:
            time_str = relative_time
        return (date_str, time_str)
    
    # Fallback: hôm nay
    date_str = today.strftime('%d/%m/%Y')
    if relative_time:
        time_str = relative_time
    return (date_str, time_str)


def _refine_city_name(candidate: str | None, text_input: str) -> str | None:
    """
    Tinh chỉnh tên địa danh toàn cầu, ưu tiên cụm đầy đủ, tránh nhầm với từ đơn lẻ.
    Hỗ trợ nhận diện địa danh từ mọi quốc gia trên thế giới.
    Sử dụng geopy/Nominatim để xác minh địa danh online.
    """
    if candidate:
        candidate = _normalize_phrase(candidate)
    
    def norm(text: str) -> str:
        import unicodedata
        text = text.lower()
        text = unicodedata.normalize('NFD', text)
        text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
        return text

    text_norm = norm(text_input)
    
    # Bước 1: Ưu tiên tìm các địa danh phổ biến trong danh sách (nếu có)
    for loc in COMMON_LOCATIONS:
        loc_norm = norm(loc)
        if loc_norm in text_norm:
            # Kiểm tra xem có phải là cụm đầy đủ không (không phải từ đơn lẻ)
            if len(loc.split()) >= 2:
                return loc
    
    # Bước 2: Nếu candidate quá ngắn (<3 ký tự hoặc 1 từ) → bỏ qua
    if candidate:
        norm_candidate = norm(candidate)
        if len(norm_candidate.replace(" ", "")) < 3 or len(candidate.split()) == 1:
            # Từ đơn lẻ như "Hồ", "Hà", "Paris" (có thể là tên người) → bỏ qua, tìm cụm dài hơn
            candidate = None
    
    # Bước 3: Tìm các cụm địa danh khả dĩ trong input (ưu tiên cụm dài)
    # Pattern mở rộng: hỗ trợ nhiều ký tự Unicode (chữ cái, dấu, ký tự đặc biệt)
    pattern = r"\b([A-ZÀ-ÝÁÉÍÓÚÝĂÂÊÔƠƯĐ][A-Za-zÀ-ỹáéíóúýăâêôơưđ\-'\.\s]+?)\b"
    phrases = []
    for match in re.finditer(pattern, text_input):
        phrase = _normalize_phrase(match.group(1))
        phrase_norm = norm(phrase)
        if len(phrase_norm.replace(" ", "")) < 3:
            continue
        # Chỉ chấp nhận cụm có 2+ từ
        if len(phrase.split()) < 2:
            continue
        
        lower_phrase = phrase.lower()
        # Ưu tiên cụm có từ khóa địa điểm (toàn cầu)
        if any(keyword in lower_phrase for keyword in LOCATION_KEYWORDS):
            phrases.append(phrase)
            continue
        
        # Pattern địa danh: thường có cấu trúc đặc biệt
        # - Có từ khóa địa điểm: "City of X", "X City", "X Province"
        # - Cấu trúc "X, Country": tìm pattern có dấu phẩy
        if "," in phrase or any(kw in lower_phrase for kw in ["of", "de", "du", "del", "van", "von", "al", "el"]):
            phrases.append(phrase)
            continue
    
    # Bước 4: Tìm pattern "thành phố X", "city of X", "X city", etc.
    location_patterns = [
        r"(?:thành phố|city of|ville de|ciudad de|stadt)\s+([A-ZÀ-ÝÁÉÍÓÚÝĂÂÊÔƠƯĐ][A-Za-zÀ-ỹáéíóúýăâêôơưđ\-'\.\s]+?)(?:[,\.;:!\?\)\]\}]|\s|$)",
        r"([A-ZÀ-ÝÁÉÍÓÚÝĂÂÊÔƠƯĐ][A-Za-zÀ-ỹáéíóúýăâêôơưđ\-'\.\s]+?)\s+(?:city|province|state|county|prefecture|shi|ken|市|省)",
    ]
    for pat in location_patterns:
        for match in re.finditer(pat, text_input, re.IGNORECASE):
            phrase = _normalize_phrase(match.group(1))
            if len(phrase.split()) >= 1:  # Có thể là 1 từ nếu có từ khóa địa điểm
                phrases.append(phrase)
    
    # Sắp xếp theo độ dài (dài nhất trước) và ưu tiên cụm có từ khóa địa điểm
    def phrase_score(p: str) -> tuple:
        lower_p = p.lower()
        has_keyword = any(kw in lower_p for kw in LOCATION_KEYWORDS)
        word_count = len(p.split())
        return (has_keyword, word_count)
    
    phrases = sorted(phrases, key=phrase_score, reverse=True)
    
    # Bước 5: Xác minh địa danh bằng geopy (nếu có)
    final_candidate = None
    candidates_to_check = []
    
    if candidate and len(candidate.split()) >= 2:
        candidates_to_check.append(candidate)
    if phrases:
        candidates_to_check.extend(phrases[:3])  # Chỉ check top 3
    
    # Thử xác minh bằng geopy
    for cand in candidates_to_check:
        if GEOPY_AVAILABLE:
            result = _geocode_location_online(cand)
            if result:
                final_candidate = result[0]  # Tên chuẩn hóa từ geopy
                break
    
    # Bước 6: Chọn kết quả (ưu tiên kết quả từ geopy)
    if final_candidate:
        return final_candidate
    
    if candidate and phrases:
        # Nếu candidate nằm trong cụm dài hơn → chọn cụm dài hơn
        norm_candidate = norm(candidate)
        for phrase in phrases:
            phrase_norm = norm(phrase)
            if norm_candidate in phrase_norm and phrase_norm != norm_candidate:
                return phrase
        # Nếu candidate là cụm đầy đủ (2+ từ) → giữ nguyên
        if len(candidate.split()) >= 2:
            return candidate
    
    if phrases:
        return phrases[0]
    
    if candidate and len(candidate.split()) >= 2:
        return candidate
    
    return None


def load_planner_prompt(prompt_path="planner_prompt.txt"):
    """Load prompt for Agent 1 (Planner)"""
    global PLANNER_PROMPT
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            PLANNER_PROMPT = f.read()
        print("INFO: Planner Prompt loaded successfully.")
    except Exception as e:
        print(f"ERROR: Could not load {prompt_path}: {e}")
        raise


def _parse_json_from_text(text: str) -> dict:
    """Safely extract JSON from LLM response text"""
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            print(f"ERROR: Agent 1 (Planner) returned invalid JSON. Text: {text}")
            return {}
    print(f"ERROR: Agent 1 (Planner) did not find JSON. Text: {text}")
    return {}


def _optimize_search_query(query: str, text_input: str) -> str:
    """
    Tối ưu hóa query để truy vấn DuckDuckGo tốt hơn, đảm bảo ra đúng kết quả.
    Ưu tiên các trang báo mới nhất.
    """
    query = query.strip()
    if not query:
        return text_input
    
    query_lower = query.lower()
    
    # 1. Thêm từ khóa "tin tức" hoặc "news" nếu chưa có (ưu tiên các trang báo)
    if not any(kw in query_lower for kw in ['tin tức', 'news', 'thông tin', 'báo', 'article', 'report']):
        # Thêm "tin tức" vào cuối query
        query = f"{query} tin tức"
    
    # 2. Thêm năm hiện tại nếu query có vẻ là về sự kiện (không có năm)
    # Nhưng chỉ thêm nếu query không có năm nào
    if not re.search(r'\b(19|20)\d{2}\b', query):
        from datetime import datetime
        current_year = datetime.now().year
        # Chỉ thêm năm nếu query có vẻ là về sự kiện cụ thể
        if any(kw in query_lower for kw in ['ra mắt', 'launch', 'release', 'xảy ra', 'happened', 'đã', 'was']):
            query = f"{query} {current_year}"
    
    # 3. Loại bỏ các từ không cần thiết hoặc làm giảm độ chính xác
    # Giữ nguyên query vì có thể chứa thông tin quan trọng
    
    return query.strip()


def _generate_search_queries(text_input: str, plan_struct: dict) -> list[str]:
    """Create a richer set of search queries to improve recall."""
    from datetime import datetime

    candidates = []
    seen = set()
    text_lower = (text_input or "").lower()

    def add(q: str):
        q = (q or "").strip()
        if q and q not in seen:
            seen.add(q)
            candidates.append(q)

    base = (text_input or "").strip()
    main_claim = (plan_struct.get("main_claim") or "").strip()
    time_refs = plan_struct.get("time_references") or {}
    entities = plan_struct.get("entities_and_values") or {}

    if base:
        add(base)  # giữ nguyên câu gốc
        add(f"{base} tin tức")
        add(f"tin tức {base}")
        add(f"{base} mới nhất")

    if main_claim and main_claim.lower() != base.lower():
        add(main_claim)
        add(f"{main_claim} tin tức")

    current_year = datetime.now().year
    if base:
        add(f"{base} {current_year}")

    explicit_date = (time_refs.get("explicit_date") or "").strip()
    if explicit_date and explicit_date[:4].isdigit():
        add(f"{base} {explicit_date[:4]}")

    locations = (entities.get("locations") or [])[:3]
    if not locations:
        common_locations = [
            ("ukraina", "ukraina"),
            ("ukraine", "ukraine"),
            ("nga", "nga"),
            ("russia", "nga"),
            ("trung quốc", "trung quốc"),
            ("china", "trung quốc"),
            ("gaza", "gaza"),
            ("israel", "israel"),
        ]
        for token, norm in common_locations:
            if token in text_lower:
                display = norm.title() if norm.islower() else norm
                locations.append(display)

    for loc in locations[:3]:
        loc = loc.strip()
        if loc:
            add(f"{loc} {base} tin tức" if base else loc)

    for org in (entities.get("organizations") or [])[:1]:
        org = org.strip()
        if org:
            add(f"{org} {current_year} tin tức")

    for event in (entities.get("events") or [])[:1]:
        event = event.strip()
        if event:
            add(f"{event} tin tức")

    conflict_keywords = [
        "chiến sự", "xung đột", "tấn công", "đụng độ", "invasion", "war", "attacked", "tấn công quân sự"
    ]
    if any(kw in text_lower for kw in conflict_keywords):
        for loc in locations[:2]:
            if loc:
                add(f"tình hình chiến sự {loc}")
                add(f"chiến sự {loc} mới nhất")

    return candidates or [base or text_input]


def _is_common_knowledge(text_input: str) -> bool:
    """
    Check if the input is common knowledge (sự thật hiển nhiên).
    Common knowledge facts have volatility = "low" or "static".
    """
    text_lower = text_input.lower()
    
    # Common knowledge patterns
    common_knowledge_patterns = [
        # Scientific facts
        r"mặt trời mọc phía đông",
        r"sun rises in the east",
        r"nước sôi ở 100 độ",
        r"water boils at 100",
        r"trái đất quay quanh mặt trời",
        r"earth revolves around the sun",
        r"nước đóng băng ở 0 độ",
        r"water freezes at 0",
        r"trọng lực",
        r"gravity",
        r"oxy cần thiết",
        r"oxygen is necessary",
        # Geographic facts
        r"paris là thủ đô pháp",
        r"paris is the capital of france",
        r"london là thủ đô anh",
        r"london is the capital of england",
        r"hà nội là thủ đô việt nam",
        r"hanoi is the capital of vietnam",
        r"việt nam nằm ở đông nam á",
        r"vietnam is in southeast asia",
        r"sông nile là sông dài nhất",
        r"nile is the longest river",
        # Mathematical facts
        r"2\s*\+\s*2\s*=\s*4",
        r"1\s*\+\s*1\s*=\s*2",
        # Historical facts (well-established)
        r"thế chiến 2 kết thúc năm 1945",
        r"world war 2 ended in 1945",
        r"việt nam độc lập năm 1945",
        r"vietnam gained independence in 1945",
    ]
    
    for pattern in common_knowledge_patterns:
        if re.search(pattern, text_lower):
            return True
    
    return False


def _normalize_plan(plan: dict, text_input: str, flash_mode: bool = False) -> dict:
    """
    (ĐÃ SỬA ĐỔI)
    Đảm bảo plan đủ schema.
    Nếu là tin thời tiết -> tạo search query, KHÔNG gọi weather tool.
    """
    import re
    plan = plan or {}

    # Khung chuẩn
    plan_struct = {
        "main_claim": plan.get("main_claim") or text_input,
        "claim_type": plan.get("claim_type") or "unknown",
        "volatility": plan.get("volatility") or "medium",
        "entities_and_values": plan.get("entities_and_values") or {
            "locations": [],
            "persons": [],
            "organizations": [],
            "events": [],
            "data_points": []
        },
        "time_references": plan.get("time_references") or {
            "explicit_date": None,
            "relative_time": None,
            "time_scope": "present"
        },
        "required_tools": plan.get("required_tools") if isinstance(plan.get("required_tools"), list) else [],
        "browse_findings": plan.get("browse_findings") if isinstance(plan.get("browse_findings"), list) else []
    }
    
    # QUAN TRỌNG: Hiệu chỉnh volatility cho sự thật hiển nhiên (common knowledge) - ƯU TIÊN CAO NHẤT
    if _is_common_knowledge(text_input):
        plan_struct["volatility"] = "low"  # or "static" - using "low" for consistency
        print(f"Agent Planner: Adjusted volatility = 'low' for common knowledge fact: {text_input[:100]}")
    
    # QUAN TRỌNG: Hiệu chỉnh volatility cho tin lịch sử
    time_scope = plan_struct.get("time_references", {}).get("time_scope", "present")
    claim_type = plan_struct.get("claim_type", "").lower()
    
    # Danh sách claim_type liên quan đến lịch sử (không thể thay đổi)
    historical_claim_types = [
        "lịch sử", "history", "sự kiện lịch sử", "phân tích lịch sử",
        "historical event", "historical analysis", "lịch sử & địa lý"
    ]
    
    # Tin lịch sử (historical) → volatility = "low" (không thể thay đổi)
    is_historical = (
        time_scope == "historical" or 
        any(ht in claim_type for ht in historical_claim_types)
    )
    
    if is_historical:
        plan_struct["volatility"] = "low"
        print(f"Agent Planner: Adjusted volatility = 'low' for historical news (time_scope={time_scope}, claim_type={claim_type})")

    # Trích data_points (ví dụ 40°C, mm mưa, %)
    data_points = set(plan_struct["entities_and_values"]["data_points"] or [])
    for m in re.findall(r"\b\d{1,3}\s?(?:°C|mm|%)\b", text_input):
        data_points.add(m.strip())
    plan_struct["entities_and_values"]["data_points"] = list(data_points)

    # Phát hiện claim thời tiết
    try:
        claim = classify_claim(text_input)
    except Exception:
        claim = {"is_weather": False}

    # (SỬA ĐỔI) Bỏ tìm kiếm thời tiết bằng search, chỉ dùng OpenWeather API
    if claim.get("is_weather"):
        plan_struct["claim_type"] = "Thời tiết"
        plan_struct["volatility"] = "high"
        city = claim.get("city")
        city = _refine_city_name(city, text_input)
        relative_time = claim.get("relative_time")
        explicit_date = plan_struct.get("time_references", {}).get("explicit_date")
        days_ahead = claim.get("days_ahead")
        
        # QUAN TRỌNG: Parse trực tiếp từ input để tính days_ahead/date (fallback nếu Agent 1 không làm đúng)
        import re
        from datetime import datetime, timedelta
        text_lower = text_input.lower()
        today = datetime.now().date()
        parsed_date = None
        parsed_days_ahead = None
        
        # Pattern 1: "X ngày nữa", "X ngày tới", "X ngày sau"
        days_match = re.search(r'(\d+)\s*(?:ngày|day|days)\s*(?:nữa|tới|sau|toi|ahead|later)', text_lower)
        if days_match:
            try:
                num_days = int(days_match.group(1))
                parsed_days_ahead = num_days
                parsed_date = (today + timedelta(days=num_days)).strftime('%Y-%m-%d')
                print(f"Agent Planner: Direct parse from input - '{num_days} ngày nữa' → days_ahead={parsed_days_ahead}, date={parsed_date}")
            except ValueError:
                pass
        
        # Pattern 2: "trong X ngày tới"
        if not parsed_days_ahead:
            days_match2 = re.search(r'(?:trong|in)\s+(\d+)\s*(?:ngày|day|days)\s*(?:tới|toi|ahead)', text_lower)
            if days_match2:
                try:
                    num_days = int(days_match2.group(1))
                    parsed_days_ahead = num_days
                    parsed_date = (today + timedelta(days=num_days)).strftime('%Y-%m-%d')
                    print(f"Agent Planner: Direct parse from input - 'trong {num_days} ngày tới' → days_ahead={parsed_days_ahead}, date={parsed_date}")
                except ValueError:
                    pass
        
        # Pattern 3: "ngày mai", "tomorrow"
        if not parsed_days_ahead:
            if "ngày mai" in text_lower or "tomorrow" in text_lower:
                parsed_days_ahead = 1
                parsed_date = (today + timedelta(days=1)).strftime('%Y-%m-%d')
                print(f"Agent Planner: Direct parse from input - 'ngày mai' → days_ahead={parsed_days_ahead}, date={parsed_date}")
        
        # Pattern 4: "hôm nay", "today"
        if not parsed_days_ahead:
            if "hôm nay" in text_lower or "today" in text_lower:
                parsed_days_ahead = 0
                parsed_date = today.strftime('%Y-%m-%d')
                print(f"Agent Planner: Direct parse from input - 'hôm nay' → days_ahead={parsed_days_ahead}, date={parsed_date}")
        
        # Pattern 5: "tuần tới", "next week"
        if not parsed_days_ahead:
            if "tuần tới" in text_lower or "next week" in text_lower:
                parsed_days_ahead = 7
                parsed_date = (today + timedelta(days=7)).strftime('%Y-%m-%d')
                print(f"Agent Planner: Direct parse from input - 'tuần tới' → days_ahead={parsed_days_ahead}, date={parsed_date}")
        
        # Lưu city thô vào entities
        if city and city not in (plan_struct["entities_and_values"].get("locations") or []):
            plan_struct["entities_and_values"].setdefault("locations", []).append(city)
        
        # CHỈ tạo tool "weather" với OpenWeather API, KHÔNG tạo search queries
        if city and len(city.split()) >= 2:
            # Lấy tên tiếng Anh sử dụng hàm helper (có geopy)
            city_en = _get_english_location_name(city)
            
            # Lấy part_of_day từ claim (sáng, chiều, tối)
            part_of_day = claim.get("part_of_day")
            
            # QUAN TRỌNG: Tính days_ahead với thứ tự ưu tiên (parse trực tiếp > Agent 1 > explicit_date > classify_claim)
            # Ưu tiên 1: Parse trực tiếp từ input (chính xác nhất)
            calculated_days_ahead = None
            final_date = None
            
            if parsed_days_ahead is not None:
                calculated_days_ahead = parsed_days_ahead
                final_date = parsed_date
                print(f"Agent Planner: PRIORITY - Using direct parse: days_ahead={calculated_days_ahead}, date={final_date}")
            
            # Ưu tiên 2: Date từ Agent 1
            if calculated_days_ahead is None:
                agent1_weather_tool = None
                agent1_date = None
                for tool in plan_struct.get("required_tools", []):
                    if tool.get("tool_name") == "weather":
                        agent1_weather_tool = tool
                        agent1_date = tool.get("parameters", {}).get("date")
                        break
                
                if agent1_date:
                    try:
                        target_date = datetime.strptime(agent1_date, '%Y-%m-%d').date()
                        calculated_days_ahead = (target_date - today).days
                        final_date = agent1_date
                        print(f"Agent Planner: Using date from Agent 1: {agent1_date} → days_ahead={calculated_days_ahead}")
                    except Exception as e:
                        print(f"Agent Planner: WARNING - Could not parse date from Agent 1: {agent1_date}, error: {e}")
            
            # Ưu tiên 3: explicit_date từ plan
            if calculated_days_ahead is None and explicit_date:
                try:
                    target_date = datetime.strptime(explicit_date, '%Y-%m-%d').date()
                    calculated_days_ahead = (target_date - today).days
                    final_date = explicit_date
                    print(f"Agent Planner: Using explicit_date={explicit_date} → days_ahead={calculated_days_ahead}")
                except Exception as e:
                    print(f"Agent Planner: WARNING - Could not parse explicit_date: {explicit_date}, error: {e}")
            
            # Ưu tiên 4: days_ahead từ classify_claim
            if calculated_days_ahead is None and days_ahead is not None:
                calculated_days_ahead = days_ahead
                if not final_date:
                    final_date = (today + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
                print(f"Agent Planner: Using days_ahead={days_ahead} from classify_claim")
            
            # Fallback: default = 0 (today)
            if calculated_days_ahead is None:
                calculated_days_ahead = 0
                final_date = today.strftime('%Y-%m-%d')
                print(f"Agent Planner: WARNING - No time information, using days_ahead=0 (today)")
            
            final_days_ahead = calculated_days_ahead
            print(f"Agent Planner: Weather tool params - city={city_en}, days_ahead={final_days_ahead}, part_of_day={part_of_day}")
            
            # Xóa weather tool cũ từ Agent 1 (nếu có) và tạo lại với days_ahead đúng
            plan_struct["required_tools"] = [t for t in plan_struct.get("required_tools", []) if t.get("tool_name") != "weather"]
            
            # Tạo tool "weather" với OpenWeather API
            weather_tool_params = {
                "city": city_en,  # Dùng tên tiếng Anh cho OpenWeather
                "days_ahead": final_days_ahead  # Đã tính toán chính xác
            }
            # Truyền date nếu có (ưu tiên final_date từ parse trực tiếp)
            if final_date:
                weather_tool_params["date"] = final_date
            elif explicit_date:
                weather_tool_params["date"] = explicit_date
            if part_of_day:
                weather_tool_params["part_of_day"] = part_of_day
            
            plan_struct["required_tools"].append({
                "tool_name": "weather",
                "parameters": weather_tool_params
            })
            
            print(f"Weather claim: Only using OpenWeather API for '{city}' (EN: '{city_en}'), days_ahead={days_ahead}, date={explicit_date}")
        elif city:
            # City không hợp lệ (từ đơn lẻ) → không tạo tool, log cảnh báo
            print(f"WARNING: Location '{city}' is invalid (single word), skipping weather tool creation.")

    # Tạo bộ câu truy vấn search (CHỈ cho các claim KHÔNG phải thời tiết)
    # Nếu là claim thời tiết, đã có tool "weather" rồi, không cần search
    is_weather = plan_struct.get("claim_type") == "Thời tiết"
    
    if not is_weather:
        # Chỉ tạo search tool cho các claim không phải thời tiết
        has_search = any(m.get('tool_name') == 'search' for m in plan_struct["required_tools"])
        generated_queries = _generate_search_queries(text_input, plan_struct)
        if not has_search:
            plan_struct["required_tools"].append({
                "tool_name": "search",
                "parameters": {"queries": generated_queries, "search_type": "broad"}
            })
        else:
            for tool in plan_struct["required_tools"]:
                if tool.get("tool_name") == "search":
                    existing = tool.get("parameters", {}).get("queries", []) or []
                    combined = list(dict.fromkeys(existing + generated_queries))
                    tool.setdefault("parameters", {})["queries"] = combined
                    break

        # Tối ưu hóa queries và giới hạn khi cần
        for tool in plan_struct["required_tools"]:
            if tool.get("tool_name") == "search":
                queries = tool.get("parameters", {}).get("queries", [])
                # Tối ưu hóa từng query để đảm bảo ra đúng kết quả
                optimized_queries = [_optimize_search_query(q, text_input) for q in queries]
                # Đảm bảo luôn có query nguyên bản (không tối ưu) của input
                raw_query = text_input.strip()
                final_queries = optimized_queries[:]
                if raw_query:
                    # Đặt raw_query ở đầu danh sách, giữ các query khác phía sau và loại trùng
                    final_queries = [raw_query] + [q for q in final_queries if q != raw_query]
                if not flash_mode:
                    tool["parameters"]["queries"] = final_queries[:5]
                else:
                    tool["parameters"]["queries"] = list(dict.fromkeys(final_queries))
                print(f"Agent Planner: Đã tối ưu hóa {len(queries)} queries thành {len(tool['parameters']['queries'])} queries")
    else:
        print("Weather claim: Skipping search tool creation, only using OpenWeather API")

    return plan_struct


def _normalize_agent1_model(model_key: str | None) -> str:
    """Normalize Agent 1 model identifier."""
    if not model_key:
        return "models/gemini-2.5-flash"
    mapping = {
        "gemini_flash": "models/gemini-2.5-flash",
        "gemini flash": "models/gemini-2.5-flash",
        "gemini-1.5-flash": "models/gemini-2.5-flash",
        "gemini-2.5-flash": "models/gemini-2.5-flash",
        "models/gemini_flash": "models/gemini-2.5-flash",
        "groq/compound": "groq/compound",
        "compound": "groq/compound",
        "gemma-3-1b": "models/gemma-3-1b-it",
        "gemma-3-1b-it": "models/gemma-3-1b-it",
        "gemma-3-2b": "models/gemma-3-4b-it",  # 2B not available, fallback to 4B
        "gemma-3-4b": "models/gemma-3-4b-it",
        "gemma-3-4b-it": "models/gemma-3-4b-it",
        "gemma-3-12b": "models/gemma-3-12b-it",
        "gemma-3-12b-it": "models/gemma-3-12b-it",
        "gemma-3-27b": "models/gemma-3-27b-it",
        "gemma-3-27b-it": "models/gemma-3-27b-it",
        "google/gemma-3-1b": "models/gemma-3-1b-it",
        "google/gemma-3-2b": "models/gemma-3-4b-it",
        "google/gemma-3-4b": "models/gemma-3-4b-it",
        "google/gemma-3-12b": "models/gemma-3-12b-it",
        "google/gemma-3-27b": "models/gemma-3-27b-it",
        "models/gemma-3-1b": "models/gemma-3-1b-it",
        "models/gemma-3-2b": "models/gemma-3-4b-it",
        "models/gemma-3-4b": "models/gemma-3-4b-it",
        "models/gemma-3-12b": "models/gemma-3-12b-it",
        "models/gemma-3-27b": "models/gemma-3-27b-it",
        "models/gemma-3-1b-it": "models/gemma-3-1b-it",
        "models/gemma-3-4b-it": "models/gemma-3-4b-it",
        "models/gemma-3-12b-it": "models/gemma-3-12b-it",
        "models/gemma-3-27b-it": "models/gemma-3-27b-it",
        "models/gemma-3n-e2b-it": "models/gemma-3n-e2b-it",
        "models/gemma-3n-e4b-it": "models/gemma-3n-e4b-it",
    }
    return mapping.get(model_key, model_key)


def _detect_agent1_provider(model_name: str) -> str:
    """Detect provider for Agent 1 model."""
    if not model_name:
        return "gemini"
    lowered = model_name.lower()
    if "gemini" in lowered or "gemma" in lowered:
        return "gemini"
    # All Agent 1 models now use Gemini API
    return "gemini"


async def create_action_plan(
    text_input: str,
    model_key: str | None = None,
    flash_mode: bool = False,
    unlimit_mode: bool = False,
) -> dict:
    """
    Gọi Agent 1 để phân tích tin và tạo kế hoạch thực thi chi tiết theo model đã chọn.
    """
    if not PLANNER_PROMPT:
        raise ValueError("Planner prompt (prompt 1) chưa được tải.")

    from datetime import datetime

    current_date = datetime.now().strftime('%Y-%m-%d')
    prompt = PLANNER_PROMPT.replace("{text_input}", text_input)
    prompt = prompt.replace("{current_date}", current_date)

    if unlimit_mode:
        prompt += (
            "\n\n[UNLIMIT MODE ENABLED]\n"
            "Ưu tiên khai thác các API chuyên ngành (giao thông, bản đồ, khí hậu, tài chính, "
            "công nghệ, khoa học, y tế, thể thao) để xây dựng kế hoạch thu thập bằng chứng toàn diện."
        )

    model_name = _normalize_agent1_model(model_key)
    
    # Fallback chain for Agent 1: gemini flash -> gemma 3-4B -> gemma 3-1B
    # Note: gemma 3-2B is not available, so we skip it
    fallback_chain = [
        model_name,  # Try user's selected model first
        "models/gemini-2.5-flash",
        "models/gemma-3-4b-it",
        "models/gemma-3-1b-it",
    ]
    # Remove duplicates while preserving order
    seen = set()
    fallback_chain = [x for x in fallback_chain if not (x in seen or seen.add(x))]
    
    if not GEMINI_API_KEY:
        raise ModelClientError("GEMINI_API_KEY is not configured.")
    
    text = ""
    last_error = None
    
    for fallback_model in fallback_chain:
        try:
            provider = _detect_agent1_provider(fallback_model)
            if provider != "gemini":
                continue  # Skip non-gemini models
            
            print(f"Planner: trying model '{fallback_model}' (provider={provider})")
            timeout = None if flash_mode else 30.0
            enable_browse = "gemini" in (fallback_model or "").lower()
            text = await call_gemini_model(
                fallback_model,
                prompt,
                timeout=timeout,
                enable_browse=enable_browse,
            )
            
            # If we got text, try to parse it
            plan_json = _parse_json_from_text(text) if text else {}
            plan_json = _normalize_plan(plan_json, text_input, flash_mode)
            if plan_json:
                print(f"Planner: Successfully generated plan with model '{fallback_model}'")
                return plan_json
        except Exception as exc:
            last_error = exc
            print(f"Planner: Error using model '{fallback_model}': {exc}")
            continue
    
    # If all models failed, use heuristic fallback
    print("Planner: All models failed, falling back to heuristic plan normalization.")
    fallback = _normalize_plan({}, text_input, flash_mode)
    return fallback
