# app/agent_planner.py
import os
import json
import google.generativeai as genai
import re
import asyncio
from dotenv import load_dotenv
from typing import Optional, Tuple

from app.weather import classify_claim

# Import geopy cho geocoding toàn cầu
try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError
    GEOPY_AVAILABLE = True
except ImportError:
    GEOPY_AVAILABLE = False
    print("WARNING: geopy không được cài đặt. Chạy: pip install geopy")

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
            print(f"Geopy: Lỗi khi geocode '{location_name}': {e}")
        
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
                print(f"Geopy: Tìm thấy '{normalized_name}' (EN: '{english_name}') tại [{location.latitude}, {location.longitude}]")
                return result
            else:
                print(f"Geopy: Tìm thấy '{normalized_name}' nhưng không có tọa độ hợp lệ")
                return None
        else:
            print(f"Geopy: Không tìm thấy địa danh '{location_name}'")
            return None
            
    except GeocoderTimedOut:
        print(f"Geopy: Timeout khi tìm kiếm '{location_name}'")
        return None
    except GeocoderServiceError as e:
        print(f"Geopy: Service error khi tìm kiếm '{location_name}': {e}")
        return None
    except Exception as e:
        print(f"Geopy: Unexpected error khi tìm kiếm '{location_name}': {type(e).__name__}: {e}")
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
    """Tải prompt cho Agent 1 (Planner)"""
    global PLANNER_PROMPT
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            PLANNER_PROMPT = f.read()
        print("INFO: Tải Planner Prompt thành công.")
    except Exception as e:
        print(f"LỖI: không thể tải {prompt_path}: {e}")
        raise


def _parse_json_from_text(text: str) -> dict:
    """Trích xuất JSON an toàn từ text trả về của LLM"""
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            print(f"LỖI: Agent 1 (Planner) trả về JSON không hợp lệ. Text: {text}")
            return {}
    print(f"LỖI: Agent 1 (Planner) không tìm thấy JSON. Text: {text}")
    return {}


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
        "required_tools": plan.get("required_tools") if isinstance(plan.get("required_tools"), list) else []
    }

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
        
        # Lưu city thô vào entities
        if city and city not in (plan_struct["entities_and_values"].get("locations") or []):
            plan_struct["entities_and_values"].setdefault("locations", []).append(city)
        
        # CHỈ tạo tool "weather" với OpenWeather API, KHÔNG tạo search queries
        if city and len(city.split()) >= 2:
            # Lấy tên tiếng Anh sử dụng hàm helper (có geopy)
            city_en = _get_english_location_name(city)
            
            # Lấy part_of_day từ claim (sáng, chiều, tối)
            part_of_day = claim.get("part_of_day")
            
            # Đảm bảo days_ahead không None
            if days_ahead is None:
                days_ahead = 0
                print(f"Agent Planner: WARNING - days_ahead là None, sử dụng 0 (hôm nay)")
            
            print(f"Agent Planner: Weather tool params - city={city_en}, days_ahead={days_ahead}, part_of_day={part_of_day}")
            
            # Tạo tool "weather" với OpenWeather API
            weather_tool_params = {
                "city": city_en,  # Dùng tên tiếng Anh cho OpenWeather
                "days_ahead": days_ahead  # Đã đảm bảo không None ở trên
            }
            if explicit_date:
                weather_tool_params["date"] = explicit_date
            if part_of_day:
                weather_tool_params["part_of_day"] = part_of_day
            
            plan_struct["required_tools"].append({
                "tool_name": "weather",
                "parameters": weather_tool_params
            })
            
            print(f"Weather claim: Chỉ sử dụng OpenWeather API cho '{city}' (EN: '{city_en}'), days_ahead={days_ahead}, date={explicit_date}")
        elif city:
            # City không hợp lệ (từ đơn lẻ) → không tạo tool, log cảnh báo
            print(f"Cảnh báo: Địa danh '{city}' không hợp lệ (từ đơn lẻ), bỏ qua tạo weather tool.")

    # Tạo bộ câu truy vấn search (CHỈ cho các claim KHÔNG phải thời tiết)
    # Nếu là claim thời tiết, đã có tool "weather" rồi, không cần search
    is_weather = plan_struct.get("claim_type") == "Thời tiết"
    
    if not is_weather:
        # Chỉ tạo search tool cho các claim không phải thời tiết
        has_search = any(m.get('tool_name') == 'search' for m in plan_struct["required_tools"])
        if not has_search:
            default_queries = [q for m in plan_struct.get("required_tools", []) if m.get("tool_name") == "search" for q in m.get("parameters", {}).get("queries", [])]
            if not default_queries:
                default_queries = [text_input]
            if not flash_mode:
                default_queries = list(dict.fromkeys(default_queries))[:3]
            else:
                default_queries = list(dict.fromkeys(default_queries))
            plan_struct["required_tools"].append({
                "tool_name": "search",
                "parameters": {"queries": default_queries, "search_type": "broad"}
            })

        # Giới hạn queries khi cần
        for tool in plan_struct["required_tools"]:
            if tool.get("tool_name") == "search":
                queries = tool.get("parameters", {}).get("queries", [])
                if not flash_mode:
                    tool["parameters"]["queries"] = queries[:5]
                else:
                    tool["parameters"]["queries"] = list(dict.fromkeys(queries))
    else:
        print("Weather claim: Bỏ qua tạo search tool, chỉ dùng OpenWeather API")

    return plan_struct


async def create_action_plan(text_input: str, flash_mode: bool = False) -> dict:
    """
    Gọi Agent 1 (Gemini Flash) để phân tích tin và tạo Kế hoạch thực thi chi tiết.
    """
    if not PLANNER_PROMPT:
        raise ValueError("Planner prompt (prompt 1) chưa được tải.")
    
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY chưa được cấu hình.")
        
    genai.configure(api_key=GEMINI_API_KEY)
    
    # Tránh lỗi KeyError do dấu ngoặc nhọn trong prompt ví dụ JSON
    prompt = PLANNER_PROMPT.replace("{text_input}", text_input)

    # Flash mode: dùng gemini-2.5-flash. Normal: cũng dùng gemini-2.5-flash
    model_names = ['models/gemini-2.5-flash']

    last_err = None
    for model_name in model_names:
        try:
            print(f"Planner: thử model '{model_name}'")
            model = genai.GenerativeModel(model_name)
            if flash_mode:
                # Flash mode: không timeout
                response = await asyncio.to_thread(model.generate_content, prompt)
            else:
                # Normal mode: có timeout 30s
                response = await asyncio.wait_for(
                    asyncio.to_thread(model.generate_content, prompt),
                    timeout=30.0
                )
            text = getattr(response, 'text', None)
            if text is None and hasattr(response, 'candidates') and response.candidates:
                parts = getattr(response.candidates[0], 'content', None)
                text = str(parts)
            if not text:
                raise RuntimeError("LLM trả về rỗng")
            plan_json = _parse_json_from_text(text)
            plan_json = _normalize_plan(plan_json, text_input, flash_mode)
            if plan_json:
                return plan_json
        except asyncio.TimeoutError:
            print(f"Planner: Timeout khi gọi model '{model_name}'")
            last_err = "Timeout"
            continue
        except Exception as e:
            last_err = e
            print(f"Planner: Lỗi với model '{model_name}': {e}")
            continue

    print(f"Lỗi khi gọi Agent 1 (Planner): {last_err}")
    # Trả về kế hoạch dự phòng: tạo search + weather queries nếu có thể
    fallback = _normalize_plan({}, text_input, flash_mode)
    return fallback
