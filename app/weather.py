"""
Module: Weather Verification & Classification
(ĐÃ SỬA ĐỔI - Chỉ còn chức năng phát hiện, không gọi API)
"""
import os
import re
from typing import Optional, Dict
from dotenv import load_dotenv

load_dotenv()

# --------------------
# Helpers (Giữ lại)
# --------------------

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

# Time-related stopwords to avoid mis-detection as cities
TIME_STOPWORDS = {
    "ngay", "hom", "qua", "mai", "sang", "chieu", "toi", "dem", "tuan", "nam", "thang",
    "today", "tomorrow", "yesterday", "morning", "afternoon", "evening", "night"
}

# --------------------
# Claim extraction & classification (Giữ lại)
# --------------------

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

    # Helper: validate candidate not time word/abbr
    def valid_candidate(s: str) -> bool:
        ns = _norm(s)
        if not ns:
            return False
        if len(ns) < 3:
            return False
        if ns in TIME_STOPWORDS:
            return False
        # reject all-uppercase short abbr like "CM"
        if len(s) <= 3 and s.isupper():
            return False
        # must contain alphabetic
        return any(c.isalpha() for c in s)

    location_name = None
    patterns = [r"(?:tại|ở|in|at)\s+([A-Za-zÀ-ỹà-ỹ\-\'\.\s]+?)(?:[,\.;:!\?\)\]\}]|\s|$)"]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            candidate = m.group(1).strip().strip('\"\'')
            candidate_clean = re.sub(r"\b(trong|vào|lúc|ngày|tháng|năm|buổi|sáng|chiều|tối)\b", "", candidate, flags=re.IGNORECASE).strip()
            if valid_candidate(candidate_clean):
                location_name = candidate_clean
                break

    if not location_name:
        tokens = re.findall(r"\b([A-ZÀ-Ý][A-Za-zÀ-ỹ\-']+(?:\s+[A-ZÀ-Ý][A-Za-zÀ-ỹ\-']+)*)\b", text)
        for t in tokens:
            if not valid_candidate(t):
                continue
            # Chỉ cần tên, không cần geocode
            location_name = t
            break

    if not location_name:
        return {"city": None, "original_text": text}

    return {
        "city": location_name, # Trả về tên (string)
        "original_text": text
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
        relative_time_str = "ngày mai" # Mặc định
        if "week" in text_lower or "tuan" in text_lower:
            days_ahead = 7
            relative_time_str = "tuần tới"
        elif "mai" in text_lower or "tomorrow" in text_lower:
            days_ahead = 1
            relative_time_str = "ngày mai"
        else:
            days_ahead = 3
            
    # Trích xuất chi tiết (sáng/chiều/tối)
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
        "city": city, # Trả về tên thành phố
        "time_scope": time_scope, 
        "days_ahead": days_ahead,
        "relative_time": relative_time_str # Trả về chuỗi thời gian tương đối
    }
