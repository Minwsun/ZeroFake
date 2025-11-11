"""
Module: Weather Verification & Classification (v3.10.2)
- Global geocoding (OpenWeather -> Open-Meteo fallback) with soft VN-bias only for ambiguous Vietnamese city names
- Robust OpenWeather calls with retry/backoff
- Precise future selection by date and part-of-day (morning/afternoon/evening)
- Historical via Open-Meteo ERA5
- Forecast day windows aggregation (morning/afternoon/evening)
- Restore classify_claim to avoid import errors in Agent 1
"""
import os
import re
import time
import requests
from typing import Optional, Dict, List, Tuple
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

# API keys & endpoints
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
GEOCODING_URL = "https://api.openweathermap.org/geo/1.0/direct"
CURRENT_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"  # 5-day / 3-hour steps
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/era5"
OPEN_METEO_GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"

# --------------------
# HTTP helper with retries
# --------------------

def _http_get_json(url: str, params: dict, timeout: float = 8.0, attempts: int = 3, backoff: float = 0.8) -> Optional[dict]:
    last_err = None
    for i in range(attempts):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(backoff * (i + 1))
            continue
    return None

# --------------------
# Helpers
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

# Common Vietnamese cities for soft VN bias when no country specified and name is ambiguous
VN_CITY_KEYS = {
    "ha noi", "hanoi", "ha noi viet nam", "hanoi vn",
    "ho chi minh", "tp ho chi minh", "sai gon", "saigon",
    "da nang", "danang",
    "hai phong", "haiphong",
    "can tho", "cantho",
    "hue", "thua thien hue",
    "nha trang", "nhatrang",
}

# Time-related stopwords to avoid mis-detection as cities
TIME_STOPWORDS = {
    "ngay", "hom", "qua", "mai", "sang", "chieu", "toi", "dem", "tuan", "nam", "thang",
    "today", "tomorrow", "yesterday", "morning", "afternoon", "evening", "night"
}

# --------------------
# Geocoding (GLOBAL) with exact-match preference and soft country bias for VN
# --------------------

def geocode_city(name: str, limit: int = 5) -> Optional[Dict]:
    """Global geocoding. Tries OpenWeather first (if API key), then Open-Meteo.
    For ambiguous Vietnamese names with no country specified, also tries q="<name>,VN".
    """
    if not name:
        return None
    target = _norm(name)

    # Try OpenWeather with optional VN bias
    if OPENWEATHER_API_KEY:
        query_variants = []
        if "," not in name and target in VN_CITY_KEYS:
            query_variants.append(f"{name},VN")
        query_variants.append(name)

        for q in query_variants:
            try:
                data = _http_get_json(GEOCODING_URL, {"q": q, "limit": limit, "appid": OPENWEATHER_API_KEY}) or []
                best = None
                # prefer exact normalized name match
                for item in data:
                    nm = _norm(item.get("name"))
                    if nm == target:
                        best = item
                        break
                if not best and data:
                    best = data[0]
                if best:
                    return {
                        "name": best.get("name"),
                        "country": best.get("country"),
                        "lat": best.get("lat"),
                        "lon": best.get("lon"),
                        "state": best.get("state")
                    }
            except Exception:
                continue

    # Fallback: Open-Meteo global geocoding
    try:
        data = _http_get_json(OPEN_METEO_GEOCODING, {"name": name, "count": limit, "language": "vi"}) or {}
        results = data.get("results") or []
        best = None
        for item in results:
            nm = _norm(item.get("name"))
            if nm == target:
                best = item
                break
        if not best and results:
            best = results[0]
        if best:
            return {
                "name": best.get("name"),
                "country": best.get("country_code") or best.get("country"),
                "lat": best.get("latitude"),
                "lon": best.get("longitude"),
                "state": best.get("admin1")
            }
    except Exception:
        pass
    return None

# --------------------
# Claim extraction & classification
# --------------------

def extract_weather_info(text: str) -> Optional[Dict]:
    """Detect weather-related claim and extract a plausible city globally via geocoding."""
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

    location = None
    patterns = [r"(?:tại|ở|in|at)\s+([A-Za-zÀ-ỹà-ỹ\-\'\.\s]+?)(?:[,\.;:!\?\)\]\}]|\s|$)"]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            candidate = m.group(1).strip().strip('"\'')
            candidate_clean = re.sub(r"\b(trong|vào|lúc|ngày|tháng|năm|buổi|sáng|chiều|tối)\b", "", candidate, flags=re.IGNORECASE).strip()
            if valid_candidate(candidate_clean):
                loc = geocode_city(candidate_clean)
                if loc:
                    location = loc
                    break

    if not location:
        tokens = re.findall(r"\b([A-ZÀ-Ý][A-Za-zÀ-ỹ\-']+(?:\s+[A-ZÀ-Ý][A-Za-zÀ-ỹ\-']+)*)\b", text)
        for t in tokens:
            if not valid_candidate(t):
                continue
            loc = geocode_city(t)
            if loc:
                location = loc
                break

    if not location:
        return {"city": None, "country": None, "lat": None, "lon": None, "original_text": text}

    return {
        "city": location.get("name"),
        "country": location.get("country"),
        "lat": location.get("lat"),
        "lon": location.get("lon"),
        "original_text": text
    }


def classify_claim(text: str) -> Dict:
    """Classify time scope for weather claim based on common phrases (global)."""
    text_lower = _norm(text)
    is_weather = extract_weather_info(text) is not None

    historical_keywords = ["nam truoc", "10 nam truoc", "5 nam truoc", "hom qua", "ngay hom qua", "qua khu", "last year", "yesterday"]
    future_keywords = ["ngay mai", "mai", "sang mai", "chieu mai", "toi mai", "tuan toi", "tuan sau", "ngay toi", "tuong lai", "du bao", "forecast", "tomorrow", "next week"]
    present_keywords = ["hom nay", "hien tai", "bay gio", "ngay luc nay", "today", "now"]

    time_scope = 'unknown'
    days_ahead: Optional[int] = None

    if any(k in text_lower for k in historical_keywords):
        time_scope = 'historical'
    elif any(k in text_lower for k in present_keywords):
        time_scope = 'present_future'
        days_ahead = 0
    elif any(k in text_lower for k in future_keywords):
        time_scope = 'present_future'
        if "week" in text_lower or "tuan" in text_lower:
            days_ahead = 7
        elif "mai" in text_lower or "tomorrow" in text_lower:
            days_ahead = 1
        else:
            days_ahead = 3

    return {"is_weather": is_weather, "time_scope": time_scope, "days_ahead": days_ahead}

# --------------------
# Relative time resolution
# --------------------

def resolve_time_parameters(relative_time: Optional[str], explicit_date: Optional[str], now_utc: Optional[datetime] = None) -> Tuple[Optional[str], Optional[str]]:
    """Compute (target_date YYYY-MM-DD, part_of_day in {morning, afternoon, evening, None})."""
    if explicit_date:
        try:
            datetime.strptime(explicit_date, "%Y-%m-%d")
            pod = None
            if relative_time:
                rl = _norm(relative_time)
                if "sang" in rl or "morning" in rl:
                    pod = "morning"
                elif "chieu" in rl or "afternoon" in rl:
                    pod = "afternoon"
                elif "toi" in rl or "dem" in rl or "evening" in rl or "night" in rl:
                    pod = "evening"
            return explicit_date, pod
        except Exception:
            pass

    if not relative_time:
        return None, None

    rl = _norm(relative_time)
    if now_utc is None:
        now_utc = datetime.utcnow()
    base_date = now_utc.date()

    pod = None
    if "sang" in rl or "morning" in rl:
        pod = "morning"
    elif "chieu" in rl or "afternoon" in rl:
        pod = "afternoon"
    elif "toi" in rl or "dem" in rl or "evening" in rl or "night" in rl:
        pod = "evening"

    if "hom nay" in rl or "today" in rl:
        target = base_date
    elif "ngay mai" in rl or rl.endswith(" mai") or "tomorrow" in rl:
        target = base_date + timedelta(days=1)
    elif "tuan toi" in rl or "next week" in rl:
        target = base_date + timedelta(days=7)
    elif "hom qua" in rl or "yesterday" in rl:
        target = base_date - timedelta(days=1)
    else:
        target = base_date

    return target.strftime("%Y-%m-%d"), pod

# --------------------
# Weather data fetchers (with retries)
# --------------------

def _get_current_weather_latlon(lat: float, lon: float) -> Optional[Dict]:
    if not OPENWEATHER_API_KEY:
        return None
    data = _http_get_json(CURRENT_WEATHER_URL, {"lat": lat, "lon": lon, "appid": OPENWEATHER_API_KEY, "units": "metric", "lang": "vi"})
    if not data:
        return None
    try:
        return {
            "city": (data.get("name") or ""),
            "country": (data.get("sys", {}) or {}).get("country"),
            "temperature": (data.get("main", {}) or {}).get("temp"),
            "feels_like": (data.get("main", {}) or {}).get("feels_like"),
            "humidity": (data.get("main", {}) or {}).get("humidity"),
            "description": ((data.get("weather", [{}])[0] or {}).get("description") or ""),
            "main_weather": ((data.get("weather", [{}])[0] or {}).get("main") or ""),
            "wind_speed": (data.get("wind", {}) or {}).get("speed"),
            "visibility": data.get("visibility"),
            "timestamp": data.get("dt")
        }
    except Exception:
        return None


def _parse_forecast_list(lat: float, lon: float) -> Optional[Dict]:
    if not OPENWEATHER_API_KEY:
        return None
    return _http_get_json(FORECAST_URL, {"lat": lat, "lon": lon, "appid": OPENWEATHER_API_KEY, "units": "metric", "lang": "vi"})


def _get_forecast_latlon_slot(lat: float, lon: float, target_date: Optional[str], part_of_day: Optional[str]) -> Optional[Dict]:
    data = _parse_forecast_list(lat, lon)
    if not data:
        return None
    lst = data.get("list", [])
    if not lst:
        return None

    def parse_dt(dt_txt: str) -> datetime:
        return datetime.strptime(dt_txt, "%Y-%m-%d %H:%M:%S")

    candidates = []
    for item in lst:
        dt_txt = item.get("dt_txt")
        if not dt_txt:
            continue
        dt = parse_dt(dt_txt)
        if (not target_date) or dt.strftime("%Y-%m-%d") == target_date:
            candidates.append((dt, item))
    if not candidates:
        return None

    if part_of_day == "morning":
        target_hour = 9; valid_hours = range(6, 12)
    elif part_of_day == "afternoon":
        target_hour = 15; valid_hours = range(12, 18)
    elif part_of_day == "evening":
        target_hour = 20; valid_hours = range(18, 24)
    else:
        target_hour = 12; valid_hours = range(0, 24)

    def score(dt: datetime) -> Tuple[int, int]:
        in_window = 0 if dt.hour in valid_hours else 1
        return (in_window, abs(dt.hour - target_hour))

    candidates.sort(key=lambda x: score(x[0]))
    _, best = candidates[0]
    weather = (best.get("weather", [{}])[0] or {})
    main = (best.get("main", {}) or {})
    wind = (best.get("wind", {}) or {})
    return {
        "city": ((data.get("city", {}) or {}).get("name") or ""),
        "dt_txt": best.get("dt_txt"),
        "temperature": main.get("temp"),
        "humidity": main.get("humidity"),
        "description": weather.get("description", ""),
        "main_weather": weather.get("main", ""),
        "wind_speed": wind.get("speed")
    }


def _aggregate_day_windows(lst: List[Dict], target_date: str) -> Dict:
    def parse_dt(dt_txt: str) -> datetime:
        return datetime.strptime(dt_txt, "%Y-%m-%d %H:%M:%S")

    windows = {
        "morning": {"hours": range(6, 12), "slots": [], "precip": [], "temps": []},
        "afternoon": {"hours": range(12, 18), "slots": [], "precip": [], "temps": []},
        "evening": {"hours": range(18, 24), "slots": [], "precip": [], "temps": []},
    }

    for item in lst:
        dt_txt = item.get("dt_txt")
        if not dt_txt:
            continue
        dt = parse_dt(dt_txt)
        if dt.strftime("%Y-%m-%d") != target_date:
            continue
        rain = 0.0
        try:
            rain = float(((item.get("rain") or {}).get("3h") or 0.0))
        except Exception:
            rain = 0.0
        temp = None
        try:
            temp = float(((item.get("main") or {}).get("temp")))
        except Exception:
            temp = None
        for key, w in windows.items():
            if dt.hour in w["hours"]:
                w["slots"].append(dt_txt)
                w["precip"].append(rain)
                if temp is not None:
                    w["temps"].append(temp)
                break

    result = {}
    for key, w in windows.items():
        precip_total = sum([x for x in w["precip"] if isinstance(x, (int, float))]) if w["precip"] else 0.0
        temp_mean = (sum(w["temps"]) / len(w["temps"])) if w["temps"] else None
        result[key] = {
            "has_rain": precip_total > 0.0,
            "precip_total_mm": round(precip_total, 2),
            "temp_mean_c": round(temp_mean, 1) if isinstance(temp_mean, (int, float)) else None,
            "slots": w["slots"],
        }
    return result


def get_forecast_day_windows(city: str, target_date: str) -> Optional[Dict]:
    loc = geocode_city(city)
    if not loc:
        return None
    data = _parse_forecast_list(loc["lat"], loc["lon"])
    if not data:
        return None
    lst = data.get("list", []) or []
    return _aggregate_day_windows(lst, target_date)

# --------------------
# Public APIs (string city input)
# --------------------

def get_current_weather(city: str) -> Optional[Dict]:
    loc = geocode_city(city)
    if not loc:
        return None
    return _get_current_weather_latlon(loc["lat"], loc["lon"])


def get_forecast_data(city: str) -> Optional[Dict]:
    loc = geocode_city(city)
    if not loc:
        return None
    return _get_forecast_latlon_slot(loc["lat"], loc["lon"], None, None)


def get_forecast_for_date(city: str, target_date: Optional[str], part_of_day: Optional[str]) -> Optional[Dict]:
    loc = geocode_city(city)
    if not loc:
        return None
    return _get_forecast_latlon_slot(loc["lat"], loc["lon"], target_date, part_of_day)


def get_historical_weather(city: str, date_str: str) -> Optional[Dict]:
    loc = geocode_city(city)
    if not loc:
        return None
    return _get_historical_latlon(loc["lat"], loc["lon"], date_str)


def forecast_window_supported(days_ahead: Optional[int]) -> bool:
    if days_ahead is None:
        return True
    try:
        return days_ahead <= 5
    except Exception:
        return True

# --------------------
# Relative helpers used by executor
# --------------------

def relative_to_date(relative_time: Optional[str]) -> Optional[str]:
    if not relative_time:
        return None
    rt = _norm(relative_time)
    today = datetime.utcnow().date()
    if rt in ["hom qua", "ngay hom qua", "yesterday"]:
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if rt in ["hom nay", "today"]:
        return today.strftime("%Y-%m-%d")
    if rt in ["tuan truoc", "last week"]:
        return (today - timedelta(days=7)).strftime("%Y-%m-%d")
    if "ngay mai" in rt or rt.endswith(" mai") or "tomorrow" in rt:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    return None
