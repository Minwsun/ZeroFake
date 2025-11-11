"""
Module: Weather Verification & Classification (v3.9.1)
- Robust OpenWeather with retry/backoff + precise date/part-of-day selection
- Geocoding: add Vietnam country bias for common VN cities to avoid wrong country (e.g., Djohong)
- Historical via Open-Meteo ERA5
- Forecast day windows aggregation
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

VN_CITY_KEYS = {
    "ha noi", "hanoi", "ha noi viet nam", "hanoi vn",
    "ho chi minh", "tp ho chi minh", "sai gon", "saigon",
    "da nang", "danang",
    "hai phong", "haiphong",
    "can tho", "cantho",
    "hue", "thua thien hue",
    "nha trang", "nhatrang",
}

# --------------------
# Geocoding (GLOBAL) with exact-match preference and country bias for VN
# --------------------

def geocode_city(name: str, limit: int = 5) -> Optional[Dict]:
    if not name:
        return None
    target = _norm(name)

    # Try OpenWeather with VN bias for common VN cities
    query_variants = []
    if target in VN_CITY_KEYS:
        query_variants.append(f"{name},VN")
    query_variants.append(name)

    if OPENWEATHER_API_KEY:
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

    # Fallback: Open-Meteo
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

# (Phần còn lại giữ như v3.9: extract_weather_info, classify_claim, resolve_time_parameters,
# _get_current_weather_latlon, _parse_forecast_list, _get_forecast_latlon_slot,
# _aggregate_day_windows, get_forecast_day_windows, get_current_weather, get_forecast_data,
# get_forecast_for_date, get_historical_weather, forecast_window_supported, relative_to_date)
