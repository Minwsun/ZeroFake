# Module: Weather Verification & Classification
# (ĐÃ SỬA ĐỔI - Chỉ còn chức năng phát hiện, không gọi API)

import re
from typing import Optional, Dict
from dotenv import load_dotenv


load_dotenv()


def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    try:
        import unicodedata
        s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    except Exception:
        pass
    s = re.sub(r"[\s\-_.]+", " ", s).strip()
    return s


TIME_STOPWORDS = {
    "ngay", "hom", "qua", "mai", "sang", "chieu", "toi", "dem", "tuan", "nam", "thang",
    "today", "tomorrow", "yesterday", "morning", "afternoon", "evening", "night"
}


def extract_weather_info(text: str) -> Optional[Dict]:
    """
    (Sửa đổi)
    Phát hiện tin thời tiết và trích xuất TÊN địa danh, không cần geocoding.
    """
    text_lower = text.lower()
    weather_keywords = [
        "tuyet", "snow", "mua", "rain", "nang", "sunny", "nong", "hot",
        "lanh", "cold", "bao", "storm", "gio", "wind", "suong mu", "fog",
        "nhiet do", "temperature", "thoi tiet", "weather", "nhiệt độ", "thời tiết", "mưa", "gió", "bão"
    ]
    if not any(kw in _norm(text_lower) for kw in weather_keywords):
        return None

    def valid_candidate(s: str) -> bool:
        ns = _norm(s)
        if not ns:
            return False
        if len(ns) < 3:
            return False
        if ns in TIME_STOPWORDS:
            return False
        if len(s) <= 3 and s.isupper():
            return False
        return any(c.isalpha() for c in s)

    location_name = None
    
    # Danh sách địa danh phổ biến (chỉ dùng làm fallback, không giới hạn)
    COMMON_CITIES = [
        "Thành phố Hồ Chí Minh", "Hồ Chí Minh", "Ho Chi Minh City",
        "Hà Nội", "Hanoi",
        "Đà Nẵng", "Da Nang",
        "Hải Phòng", "Hai Phong",
        "Cần Thơ", "Can Tho",
        "New York", "New York City", "Los Angeles", "San Francisco",
        "London", "Paris", "Tokyo", "Seoul", "Beijing", "Shanghai"
    ]
    
    # Từ khóa địa điểm toàn cầu
    LOCATION_KEYWORDS = {
        "city", "province", "state", "county", "district", "region", "town", "village",
        "thành phố", "tỉnh", "quận", "huyện", "thị xã", "xã", "phường",
        "ville", "ciudad", "stadt", "shi", "ken", "市", "省", "시", "도"
    }
    
    # Ưu tiên tìm các địa danh phổ biến trước (nếu có)
    text_lower_norm = _norm(text.lower())
    for city in COMMON_CITIES:
        city_norm = _norm(city.lower())
        if city_norm in text_lower_norm:
            location_name = city
            break
    
    # Nếu chưa tìm thấy, dùng pattern matching mở rộng
    if not location_name:
        # Pattern 1: "tại/ở/in/at/city of/ville de + location" (hỗ trợ đa ngôn ngữ)
        patterns = [
            r"(?:tại|ở|in|at|thành phố|city of|ville de|ciudad de|stadt)\s+([A-ZÀ-ÝÁÉÍÓÚÝĂÂÊÔƠƯĐ][A-Za-zÀ-ỹáéíóúýăâêôơưđ\-'\.\s]+?)(?:[,\.;:!\?\)\]\}]|\s|$)",
            r"([A-ZÀ-ÝÁÉÍÓÚÝĂÂÊÔƠƯĐ][A-Za-zÀ-ỹáéíóúýăâêôơưđ\-'\.\s]+?)\s+(?:city|province|state|county|prefecture|shi|ken|市|省)",
        ]
        for p in patterns:
            m = re.search(p, text, flags=re.IGNORECASE)
            if m:
                candidate = m.group(1).strip().strip('"\'')
                candidate_clean = re.sub(r"\b(trong|vào|lúc|ngày|tháng|năm|buổi|sáng|chiều|tối)\b", "", candidate, flags=re.IGNORECASE).strip()
                if valid_candidate(candidate_clean) and len(candidate_clean.split()) >= 2:
                    location_name = candidate_clean
                    break
    
    # Pattern 2: Tìm các cụm từ viết hoa đa từ (ưu tiên cụm dài, hỗ trợ Unicode)
    if not location_name:
        # Pattern mở rộng hỗ trợ nhiều ký tự Unicode
        tokens = re.findall(r"\b([A-ZÀ-ÝÁÉÍÓÚÝĂÂÊÔƠƯĐ][A-Za-zÀ-ỹáéíóúýăâêôơưđ\-']+(?:\s+[A-ZÀ-ÝÁÉÍÓÚÝĂÂÊÔƠƯĐ][A-Za-zÀ-ỹáéíóúýăâêôơưđ\-']+)+)\b", text)
        tokens_sorted = sorted(tokens, key=lambda x: len(x.split()), reverse=True)
        for t in tokens_sorted:
            if not valid_candidate(t):
                continue
            # Ưu tiên cụm có 2+ từ hoặc có từ khóa địa điểm
            t_lower = t.lower()
            if len(t.split()) >= 2 or any(kw in t_lower for kw in LOCATION_KEYWORDS):
                location_name = t
                break

    if not location_name:
        return {"city": None, "original_text": text, "is_weather_keyword": True}

    return {
        "city": location_name,
        "original_text": text,
        "is_weather_keyword": True
    }


def classify_claim(text: str) -> Dict:
    """Classify time scope for weather claim based on common phrases (global)."""
    text_lower = _norm(text)
    weather_info = extract_weather_info(text)
    is_weather = weather_info is not None
    city = weather_info.get("city") if weather_info else None

    historical_keywords = ["nam truoc", "10 nam truoc", "5 nam truoc", "hom qua", "ngay hom qua", "qua khu", "last year", "yesterday"]
    future_keywords = ["ngay mai", "mai", "sang mai", "chieu mai", "toi mai", "tuan toi", "tuan sau", "ngay toi", "tuong lai", "du bao", "forecast", "tomorrow", "next week"]
    present_keywords = ["hom nay", "hien tai", "bay gio", "ngay luc nay", "today", "now"]

    time_scope = 'unknown'
    days_ahead: Optional[int] = None
    relative_time_str: Optional[str] = None

    if any(k in text_lower for k in historical_keywords):
        time_scope = 'historical'
        if "hom qua" in text_lower or "yesterday" in text_lower:
            relative_time_str = "hôm qua"
    elif any(k in text_lower for k in present_keywords):
        time_scope = 'present_future'
        days_ahead = 0
        relative_time_str = "hôm nay"
    elif any(k in text_lower for k in future_keywords):
        time_scope = 'present_future'
        relative_time_str = "ngày mai"
        if "week" in text_lower or "tuan" in text_lower:
            days_ahead = 7
            relative_time_str = "tuần tới"
        elif "mai" in text_lower or "tomorrow" in text_lower:
            days_ahead = 1
            relative_time_str = "ngày mai"
        else:
            days_ahead = 3

    part_of_day = None
    if any(k in text_lower for k in ["sáng", "morning"]):
        part_of_day = "sáng"
    elif any(k in text_lower for k in ["chiều", "afternoon"]):
        part_of_day = "chiều"
    elif any(k in text_lower for k in ["tối", "đêm", "evening", "night"]):
        part_of_day = "tối"

    if relative_time_str and part_of_day:
        relative_time_str = f"{part_of_day} {relative_time_str}"

    return {
        "is_weather": is_weather,
        "city": city,
        "time_scope": time_scope,
        "days_ahead": days_ahead,
        "relative_time": relative_time_str
    }
