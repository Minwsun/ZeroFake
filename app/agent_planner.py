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
    Sử dụng geopy/Nominatim để tìm kiếm địa danh online.
    Trả về (tên chuẩn hóa, tên tiếng Anh) hoặc None nếu không tìm thấy.
    
    Args:
        location_name: Tên địa danh cần tìm
        
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
        # Sử dụng Nominatim (OpenStreetMap) - free, không cần API key
        geolocator = Nominatim(user_agent="ZeroFake-FactChecker/1.0")
        
        # Tìm kiếm địa danh
        location = geolocator.geocode(location_name, timeout=5, language='en')
        
        if location:
            # Lấy tên chuẩn hóa và tên tiếng Anh
            normalized_name = location.address.split(',')[0]  # Tên chính
            english_name = location.address.split(',')[0]  # Có thể cải thiện sau
            
            # Lưu vào cache
            result = (normalized_name, english_name)
            _location_cache[location_key] = result
            return result
    except (GeocoderTimedOut, GeocoderServiceError, Exception) as e:
        print(f"Geocoding error cho '{location_name}': {e}")
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

    weather_queries = []
    if claim.get("is_weather"):
        plan_struct["claim_type"] = "Thời tiết"
        plan_struct["volatility"] = "high"
        city = claim.get("city")
        city = _refine_city_name(city, text_input)
        relative_time = claim.get("relative_time")
        explicit_date = plan_struct.get("time_references", {}).get("explicit_date")
        
        # Lưu city thô vào entities
        if city and city not in (plan_struct["entities_and_values"].get("locations") or []):
            plan_struct["entities_and_values"].setdefault("locations", []).append(city)
        
        # Tạo query theo format chuẩn: "thời tiết của + location + time + date"
        # CHỈ tạo query nếu city hợp lệ (không phải từ đơn lẻ, có ít nhất 2 từ)
        if city and len(city.split()) >= 2:
            # Lấy tên tiếng Anh sử dụng hàm helper (có geopy)
            city_en = _get_english_location_name(city)
            
            # Trích xuất điều kiện thời tiết từ input (nếu có)
            weather_condition = None
            weather_condition_en = None
            text_lower = text_input.lower()
            
            # Tìm điều kiện thời tiết trong input (ưu tiên cụm từ dài hơn trước)
            weather_keywords = [
                ("mưa rất lớn", "mưa rất lớn", "torrential rain"),
                ("mưa to", "mưa to", "heavy rain"),
                ("mưa lớn", "mưa lớn", "heavy rain"),
                ("mưa nhẹ", "mưa nhẹ", "light rain"),
                ("gió mạnh", "gió mạnh", "strong wind"),
                ("nắng to", "nắng to", "sunny"),
                ("thunderstorm", "thunderstorm", "thunderstorm"),
                ("dông", "dông", "thunderstorm"),
                ("bão", "bão", "storm"),
                ("mưa", "mưa", "rain"),
                ("nắng", "nắng", "sunny"),
                ("gió", "gió", "wind"),
            ]
            
            # Tìm từ dài nhất trước (để tránh nhầm "mưa to" với "mưa")
            for keyword, vn, en in weather_keywords:
                if keyword in text_lower:
                    weather_condition = vn
                    weather_condition_en = en
                    break
            
            # Format chính: "thời tiết của [location] [time/date]"
            if relative_time:
                # Có relative_time (ví dụ: "ngày mai", "hôm nay")
                weather_queries.append(f"thời tiết của {city} {relative_time}")
                weather_queries.append(f"dự báo thời tiết của {city} {relative_time}")
                # Query tiếng Anh
                weather_queries.append(f"{city_en} weather {relative_time}")
                weather_queries.append(f"{city_en} weather forecast {relative_time}")
                
                # Nếu có điều kiện thời tiết cụ thể, thêm query chi tiết
                if weather_condition:
                    weather_queries.append(f"thời tiết {city} {relative_time} {weather_condition}")
                    weather_queries.append(f"dự báo {weather_condition} {city} {relative_time}")
                    if weather_condition_en:
                        weather_queries.append(f"{weather_condition_en} forecast {city_en} {relative_time}")
                        weather_queries.append(f"{city_en} {weather_condition_en} {relative_time}")
            elif explicit_date:
                # Có explicit_date (ví dụ: "2025-11-12")
                weather_queries.append(f"thời tiết của {city} {explicit_date}")
                weather_queries.append(f"dự báo thời tiết của {city} {explicit_date}")
                weather_queries.append(f"{city_en} weather {explicit_date}")
                
                # Nếu có điều kiện thời tiết cụ thể
                if weather_condition:
                    weather_queries.append(f"thời tiết {city} {explicit_date} {weather_condition}")
                    weather_queries.append(f"dự báo {weather_condition} {city} {explicit_date}")
                    if weather_condition_en:
                        weather_queries.append(f"{weather_condition_en} forecast {city_en} {explicit_date}")
            else:
                # Chỉ có location
                weather_queries.append(f"thời tiết của {city}")
                weather_queries.append(f"dự báo thời tiết của {city}")
                weather_queries.append(f"{city_en} weather forecast")
                
                # Nếu có điều kiện thời tiết cụ thể
                if weather_condition:
                    weather_queries.append(f"thời tiết {city} {weather_condition}")
                    weather_queries.append(f"dự báo {weather_condition} {city}")
                    if weather_condition_en:
                        weather_queries.append(f"{weather_condition_en} forecast {city_en}")
        elif city:
            # City không hợp lệ (từ đơn lẻ) → không tạo query, log cảnh báo
            print(f"Cảnh báo: Địa danh '{city}' không hợp lệ (từ đơn lẻ), bỏ qua tạo query thời tiết.")

    # Tạo bộ câu truy vấn search
    has_search = any(m.get('tool_name') == 'search' for m in plan_struct["required_tools"])
    if not has_search:
        default_queries = [q for m in plan_struct.get("required_tools", []) if m.get("tool_name") == "search" for q in m.get("parameters", {}).get("queries", [])]
        if not default_queries:
            default_queries = [text_input]
        final_queries = weather_queries + default_queries
        if not flash_mode:
            final_queries = list(dict.fromkeys(final_queries))[:3]
        else:
            final_queries = list(dict.fromkeys(final_queries))
        plan_struct["required_tools"].append({
            "tool_name": "search",
            "parameters": {"queries": final_queries, "search_type": "broad"}
        })

    # Xóa bất kỳ tool "weather" nào nếu có và giới hạn queries khi cần
    for tool in plan_struct["required_tools"]:
        if tool.get("tool_name") == "search":
            queries = tool.get("parameters", {}).get("queries", [])
            if not flash_mode:
                tool["parameters"]["queries"] = queries[:3]
            else:
                tool["parameters"]["queries"] = list(dict.fromkeys(queries))

    plan_struct["required_tools"] = [t for t in plan_struct["required_tools"] if t.get("tool_name") == "search"]

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
