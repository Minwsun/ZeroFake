# Module: Weather Verification & Classification
# (MODIFIED - Added OpenWeather API to support weather queries)

import re
import os
import requests
from typing import Optional, Dict, List
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv


load_dotenv()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")


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
    (MODIFIED)
    Detect weather news and extract location NAME, no geocoding needed.
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
    
    # Common location list (only used as fallback, not limited)
    COMMON_CITIES = [
        "Thành phố Hồ Chí Minh", "Hồ Chí Minh", "Ho Chi Minh City",
        "Hà Nội", "Hanoi",
        "Đà Nẵng", "Da Nang",
        "Hải Phòng", "Hai Phong",
        "Cần Thơ", "Can Tho",
        "New York", "New York City", "Los Angeles", "San Francisco",
        "London", "Paris", "Tokyo", "Seoul", "Beijing", "Shanghai"
    ]
    
    # Global location keywords
    LOCATION_KEYWORDS = {
        "city", "province", "state", "county", "district", "region", "town", "village",
        "thành phố", "tỉnh", "quận", "huyện", "thị xã", "xã", "phường",
        "ville", "ciudad", "stadt", "shi", "ken", "市", "省", "시", "도"
    }
    
    # Prioritize finding common locations first (if any)
    text_lower_norm = _norm(text.lower())
    for city in COMMON_CITIES:
        city_norm = _norm(city.lower())
        if city_norm in text_lower_norm:
            location_name = city
            break
    
    # If not found, use extended pattern matching
    if not location_name:
        # Pattern 1: "tại/ở/in/at/city of/ville de + location" (multi-language support)
        patterns = [
            r"(?:tại|ở|in|at|thành phố|city of|ville de|ciudad de|stadt)\s+([A-ZÀ-ÝÁÉÍÓÚÝĂÂÊÔƠƯĐ][A-Za-zÀ-ỹáéíóúýăâêôơưđ\-'\.\s]+?)(?:[,\.;:!\?\)\]\}]|\s|$)",
            r"([A-ZÀ-ÝÁÉÍÓÚÝĂÂÊÔƠƯĐ][A-Za-zÀ-ỹáéíóúýăâêôơưđ\-'\.\s]+?)\s+(?:city|province|state|county|prefecture|shi|ken|市|省)",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            candidate = m.group(1).strip().strip('"\'')
            candidate_clean = re.sub(
                r"\b(trong|vào|lúc|ngày|tháng|năm|buổi|sáng|chiều|tối)\b",
                "",
                candidate,
                flags=re.IGNORECASE,
            ).strip()
            if valid_candidate(candidate_clean) and len(candidate_clean.split()) >= 2:
                location_name = candidate_clean
                break

    # Pattern 2: Find multi-word capitalized phrases (prioritize long phrases, Unicode support)
    if not location_name:
        # Extended pattern supporting many Unicode characters
        tokens = re.findall(r"\b([A-ZÀ-ÝÁÉÍÓÚÝĂÂÊÔƠƯĐ][A-Za-zÀ-ỹáéíóúýăâêôơưđ\-']+(?:\s+[A-ZÀ-ÝÁÉÍÓÚÝĂÂÊÔƠƯĐ][A-Za-zÀ-ỹáéíóúýăâêôơưđ\-']+)+)\b", text)
        tokens_sorted = sorted(tokens, key=lambda x: len(x.split()), reverse=True)
        for t in tokens_sorted:
            if not valid_candidate(t):
                continue
            # Prioritize phrases with 2+ words or location keywords
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

    # Check pattern "X ngày nữa/tới/sau" or "X days" first (IMPORTANT: Must check BEFORE other keywords)
    import re
    # Pattern 1: "X ngày nữa/tới/sau" or "X days ahead/later" (highest priority)
    days_pattern = re.search(r'(\d+)\s*(?:ngày|day|days)\s*(?:nữa|sau|tới|toi|ahead|later)', text_lower)
    # Pattern 2: "trong X ngày tới" or "in X days"
    days_pattern2 = re.search(r'(?:trong|in)\s+(\d+)\s*(?:ngày|day|days)\s*(?:tới|toi|ahead)', text_lower)
    
    if days_pattern:
        try:
            days_ahead = int(days_pattern.group(1))
            time_scope = 'present_future'
            relative_time_str = f"{days_ahead} ngày nữa"
            print(f"Classify: Detected '{days_ahead} ngày nữa/tới/sau' from input -> days_ahead={days_ahead}")
        except ValueError:
            pass
    elif days_pattern2:
        try:
            days_ahead = int(days_pattern2.group(1))
            time_scope = 'present_future'
            relative_time_str = f"trong {days_ahead} ngày tới"
            print(f"Classify: Detected 'trong {days_ahead} ngày tới' from input -> days_ahead={days_ahead}")
        except ValueError:
            pass
    
    # ONLY set days_ahead = 0 if NOT already set by pattern above
    if days_ahead is None:
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
        "relative_time": relative_time_str,
        "part_of_day": part_of_day  # "sáng", "chiều", "tối", or None
    }


def get_openweather_data(city_name: str, days_ahead: int = 0, part_of_day: Optional[str] = None) -> Optional[Dict]:
    """
    Call OpenWeather API to get weather data.
    Use geopy for geocoding first, then use OpenWeather API.
    
    Args:
        city_name: City name (e.g., "Hanoi", "Ho Chi Minh City", "Thành phố Hồ Chí Minh")
        days_ahead: Days after today (0 = today, 1 = tomorrow, ...)
        part_of_day: Part of day ("sáng", "chiều", "tối") or None
    
    Returns:
        dict: Weather data from OpenWeather or None if error
    """
    if not OPENWEATHER_API_KEY:
        print("ERROR: OPENWEATHER_API_KEY not configured in .env file.")
        print("Instructions: Add OPENWEATHER_API_KEY=your_api_key to .env file")
        return None
    
    print(f"OpenWeather: Searching for location '{city_name}'...")
    
    # Step 0: Use geopy for geocoding first (if available) - global support
    lat = None
    lon = None
    normalized_city_name = city_name
    
    try:
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut, GeocoderServiceError
        
        print(f"Geopy: Geocoding '{city_name}' (global)...")
        geolocator = Nominatim(user_agent="ZeroFake-FactChecker/1.1")
        
        # Try multiple search methods to improve accuracy for global locations
        location = None
        
        # Method 1: Direct search with original name
        try:
            location = geolocator.geocode(city_name, timeout=10, language='en', exactly_one=True)
        except Exception as e:
            print(f"Geopy: Error geocoding '{city_name}': {e}")
        
        # Method 2: If not found, try adding "city" or "thành phố" at the end
        if not location:
            try:
                if "city" not in city_name.lower() and "thành phố" not in city_name.lower():
                    location = geolocator.geocode(f"{city_name}, city", timeout=10, language='en', exactly_one=True)
            except Exception:
                pass
        
        # Method 3: If still not found, try broader search
        if not location:
            try:
                results = geolocator.geocode(city_name, timeout=10, language='en', exactly_one=False)
                if results and len(results) > 0:
                    # Select first result (can improve selection logic later)
                    location = results[0]
            except Exception:
                pass
        
        if location and location.latitude and location.longitude:
            lat = location.latitude
            lon = location.longitude
            # Get normalized name from geopy (usually English)
            address_parts = location.address.split(',')
            normalized_city_name = address_parts[0].strip()
            
            # Try to get English name from raw data if available
            if hasattr(location, 'raw') and location.raw:
                raw_data = location.raw
                if 'display_name' in raw_data:
                    display_name = raw_data['display_name']
                    normalized_city_name = display_name.split(',')[0].strip()
                elif 'name' in raw_data:
                    normalized_city_name = raw_data['name']
            
            print(f"Geopy: Found '{normalized_city_name}' at [{lat}, {lon}]")
        else:
            print(f"Geopy: Not found '{city_name}', will try OpenWeather geocoding")
    except ImportError:
        print("Geopy: geopy not available, skipping geocoding with geopy")
    except GeocoderTimedOut:
        print(f"Geopy: Timeout geocoding '{city_name}', will try OpenWeather geocoding")
    except GeocoderServiceError as e:
        print(f"Geopy: Service error geocoding '{city_name}': {e}, will try OpenWeather geocoding")
    except Exception as e:
        print(f"Geopy: Error geocoding '{city_name}': {type(e).__name__}: {e}, will try OpenWeather geocoding")
    
    # If geopy didn't find, use OpenWeather geocoding
    if lat is None or lon is None:
        # Map Vietnamese city names to English (for better geocoding)
        CITY_NAME_MAP = {
            "Thành phố Hồ Chí Minh": "Ho Chi Minh City",
            "Hồ Chí Minh": "Ho Chi Minh City",
            "Hà Nội": "Hanoi",
            "Đà Nẵng": "Da Nang",
            "Hải Phòng": "Hai Phong",
            "Cần Thơ": "Can Tho",
            "Nha Trang": "Nha Trang",
            "Huế": "Hue",
            "Vũng Tàu": "Vung Tau",
        }
        
        # Try using English name if available in map
        query_city = CITY_NAME_MAP.get(city_name, city_name)
        if query_city != city_name:
            print(f"OpenWeather: Converting '{city_name}' -> '{query_city}' for better geocoding")
        else:
            query_city = normalized_city_name if normalized_city_name != city_name else city_name
        
        try:
            # Step 1: Geocoding with OpenWeather API (correct format)
            geocode_url = "http://api.openweathermap.org/geo/1.0/direct"
            geocode_params = {
                "q": query_city,
                "limit": 1,  # Only get 1 best result (as requested)
                "appid": OPENWEATHER_API_KEY
            }
            
            print(f"OpenWeather: Calling geocoding API with query: '{query_city}'")
            geocode_response = requests.get(geocode_url, params=geocode_params, timeout=10)
            
            # Check status code
            if geocode_response.status_code == 401:
                print("ERROR: OpenWeather API key invalid or expired.")
                return None
            elif geocode_response.status_code == 429:
                print("ERROR: OpenWeather API rate limit exceeded. Please try again later.")
                return None
            elif geocode_response.status_code != 200:
                print(f"ERROR: OpenWeather geocoding API returned status code {geocode_response.status_code}")
                print(f"Response: {geocode_response.text[:200]}")
                return None

            geocode_response.raise_for_status()
            geocode_data = geocode_response.json()
            
            if not geocode_data or len(geocode_data) == 0:
                print(f"ERROR: OpenWeather did not find location '{query_city}' (original: '{city_name}')")
                # Retry with original name if mapping was used
                if query_city != city_name:
                    print(f"OpenWeather: Retrying with original name '{city_name}'...")
                    geocode_params_retry = {
                        "q": city_name,
                        "limit": 5,
                        "appid": OPENWEATHER_API_KEY
                    }
                    geocode_response_retry = requests.get(geocode_url, params=geocode_params_retry, timeout=10)
                    if geocode_response_retry.status_code == 200:
                        geocode_data_retry = geocode_response_retry.json()
                        if geocode_data_retry and len(geocode_data_retry) > 0:
                            geocode_data = geocode_data_retry
                            print(f"OpenWeather: Success with original name '{city_name}'")
                        else:
                            print(f"ERROR: Still not found with original name '{city_name}'")
                            print(f"Suggestion: Check city name or try using English name")
                            return None
                    else:
                        print(f"ERROR: Geocoding retry failed with status {geocode_response_retry.status_code}")
                        return None
                else:
                    print(f"Suggestion: Try using English name (e.g., 'Ho Chi Minh City' instead of 'Thành phố Hồ Chí Minh')")
                    return None
            
            # Select first result (can improve selection logic later)
            selected = geocode_data[0]
            lat = selected["lat"]
            lon = selected["lon"]
            location_name = selected.get("name", city_name)
            country = selected.get("country", "")
            
            print(f"OpenWeather: Found '{location_name}' ({country}) at [{lat}, {lon}]")
        except Exception as e:
            print(f"ERROR: Error geocoding with OpenWeather: {e}")
            return None
    
    # Step 2: Get weather data (use lat, lon from geopy or OpenWeather)
    if lat is not None and lon is not None:
        try:
            # Ensure days_ahead is not None
            if days_ahead is None:
                days_ahead = 0
                print(f"OpenWeather: WARNING - days_ahead is None, using 0 (today)")
            
            print(f"OpenWeather: DEBUG - days_ahead = {days_ahead}, part_of_day = {part_of_day}")
            
            if days_ahead == 0:
                # Current weather (only when days_ahead = 0)
                weather_url = "https://api.openweathermap.org/data/2.5/weather"
                weather_params = {
                    "lat": lat,
                    "lon": lon,
                    "appid": OPENWEATHER_API_KEY,
                    "units": "metric",
                    "lang": "vi"
                }
                print(f"OpenWeather: Getting current weather for [{lat}, {lon}]...")
                weather_response = requests.get(weather_url, params=weather_params, timeout=10)
                
                if weather_response.status_code == 401:
                    print("ERROR: OpenWeather API key invalid when calling weather API.")
                    return None
                elif weather_response.status_code == 429:
                    print("ERROR: OpenWeather API rate limit exceeded when calling weather API.")
                    return None
                elif weather_response.status_code != 200:
                    print(f"ERROR: OpenWeather weather API returned status code {weather_response.status_code}")
                    print(f"Response: {weather_response.text[:200]}")
                    return None

                weather_response.raise_for_status()
                weather_data = weather_response.json()
                
                if not weather_data or "main" not in weather_data:
                    print("ERROR: OpenWeather API returned invalid data (missing 'main' field)")
                    return None

                # Get specific time from API (if available)
                current_time = datetime.now()
                time_str = current_time.strftime('%H:%M')
                
                # Use normalized_city_name from geopy if available
                final_location_name = normalized_city_name
                
                result = {
                    "location": final_location_name,
                    "date": current_time.strftime('%Y-%m-%d'),
                    "time": time_str,
                    "temperature": weather_data["main"]["temp"],
                    "feels_like": weather_data["main"]["feels_like"],
                    "description": weather_data["weather"][0]["description"],
                    "main": weather_data["weather"][0]["main"],  # Rain, Clear, Clouds, etc.
                    "humidity": weather_data["main"]["humidity"],
                    "wind_speed": weather_data.get("wind", {}).get("speed", 0),
                    "source": "openweathermap.org"
                }
                print(f"OpenWeather: Success - {result['location']}: {result['description']} ({result['temperature']}°C) on {result['date']} {result['time']}")
                return result
            elif days_ahead > 0:
                # Forecast - Try One Call API 3.0 first, fallback to 2.5 if not available
                # One Call API 3.0: hourly forecast within 48h, daily within 7 days
                onecall_url = "https://api.openweathermap.org/data/3.0/onecall"
                onecall_params = {
                    "lat": lat,
                    "lon": lon,
                    "exclude": "current,minutely,daily,alerts",  # Only get hourly
                    "units": "metric",
                    "lang": "vi",
                    "appid": OPENWEATHER_API_KEY
                }
                
                print(f"OpenWeather: Trying One Call API 3.0 for forecast {days_ahead} days ahead at [{lat}, {lon}]...")
                onecall_response = requests.get(onecall_url, params=onecall_params, timeout=10)
                
                # If One Call API 3.0 not available (401, 403, or no subscription), fallback to 2.5
                use_onecall = False
                if onecall_response.status_code == 200:
                    try:
                        onecall_data = onecall_response.json()
                        if "hourly" in onecall_data:
                            use_onecall = True
                            forecast_data = {"list": onecall_data["hourly"], "source": "onecall3"}
                            print(f"OpenWeather: Using One Call API 3.0 (hourly forecast)")
                    except Exception as e:
                        print(f"OpenWeather: Error parsing One Call API 3.0: {e}, fallback to 2.5")
                
                if not use_onecall:
                    # Fallback to Forecast API 2.5
                    forecast_url = "https://api.openweathermap.org/data/2.5/forecast"
                    forecast_params = {
                        "lat": lat,
                        "lon": lon,
                        "appid": OPENWEATHER_API_KEY,
                        "units": "metric",
                        "lang": "vi"
                    }
                    print(f"OpenWeather: Fallback to Forecast API 2.5 for forecast {days_ahead} days ahead...")
                    forecast_response = requests.get(forecast_url, params=forecast_params, timeout=10)
                    
                    if forecast_response.status_code == 401:
                        print("ERROR: OpenWeather API key invalid when calling forecast API.")
                        return None
                    elif forecast_response.status_code == 429:
                        print("ERROR: OpenWeather API rate limit exceeded when calling forecast API.")
                        return None
                    elif forecast_response.status_code != 200:
                        print(f"ERROR: OpenWeather forecast API returned status code {forecast_response.status_code}")
                        print(f"Response: {forecast_response.text[:200]}")
                        return None

                    forecast_response.raise_for_status()
                    forecast_data_raw = forecast_response.json()
                    forecast_data = {"list": forecast_data_raw.get("list", []), "source": "forecast25"}
                    
                    if not forecast_data["list"]:
                        print("ERROR: OpenWeather forecast API returned invalid data (missing 'list' field)")
                        return None

                    # Find forecast for specific date
                    # Ensure days_ahead is not None
                    if days_ahead is None:
                        days_ahead = 0
                        print(f"OpenWeather: WARNING - days_ahead is None in forecast, using 0")
                
                target_date = (datetime.now() + timedelta(days=days_ahead)).date()
                target_forecasts = []
                
                print(f"OpenWeather: Finding forecast for date {target_date} (days_ahead={days_ahead})...")
                
                # Get all forecasts for target date
                # Convert timestamp to local timezone (UTC+7 for Vietnam)
                vietnam_tz = timezone(timedelta(hours=7))  # UTC+7
                
                forecast_list = forecast_data.get("list", [])
                print(f"OpenWeather: Found {len(forecast_list)} forecast items to search...")
                
                for item in forecast_list:
                    # Convert timestamp to datetime with timezone
                    item_dt_utc = datetime.fromtimestamp(item["dt"], tz=timezone.utc)
                    item_dt_local = item_dt_utc.astimezone(vietnam_tz)
                    item_date = item_dt_local.date()
                    
                    if item_date == target_date:
                        target_forecasts.append(item)
                        print(f"OpenWeather: Found forecast for {target_date} at {item_dt_local.strftime('%H:%M')} (local time)")
                
                # If no forecast found for exact date, find nearest forecast in future
                if not target_forecasts:
                    print(f"WARNING: No forecast found for date {target_date}, finding nearest forecast in future...")
                    # Sort all forecasts by time (with local timezone)
                    all_forecasts = []
                    for item in forecast_list:
                        item_dt_utc = datetime.fromtimestamp(item["dt"], tz=timezone.utc)
                        item_dt_local = item_dt_utc.astimezone(vietnam_tz)
                        item_date = item_dt_local.date()
                        if item_date >= target_date:  # Only get forecasts from target_date onwards
                            all_forecasts.append((item_date, item_dt_local, item))
                    
                    if all_forecasts:
                        # Sort by date and time (nearest first)
                        all_forecasts.sort(key=lambda x: (x[0], x[1]))
                        # Get first forecast (nearest)
                        closest_date, closest_time_local, closest_item = all_forecasts[0]
                        target_forecasts = [closest_item]
                        print(f"OpenWeather: Using nearest forecast for date {closest_date} at {closest_time_local.strftime('%H:%M')} (local time, instead of {target_date})")
                    else:
                        # If still none, get last forecast (furthest in future)
                        if forecast_list:
                            last_item = forecast_list[-1]
                            target_forecasts = [last_item]
                            last_dt_utc = datetime.fromtimestamp(last_item["dt"], tz=timezone.utc)
                            last_dt_local = last_dt_utc.astimezone(vietnam_tz)
                            last_date = last_dt_local.date()
                            print(f"OpenWeather: WARNING - Using last forecast for date {last_date} at {last_dt_local.strftime('%H:%M')} (local time, instead of {target_date})")
                
                if target_forecasts:
                    # Select forecast for correct time of day (if requested)
                    forecast = None
                    if part_of_day:
                        # CÓ KHUNG GIỜ: Tìm forecast trong khung giờ cụ thể
                        # Determine time range based on part_of_day (according to local time UTC+7)
                        time_ranges = {
                            "sáng": (3, 10),  
                            "chiều": (10, 17),  
                            "tối": (17, 23),    
                            "đêm": (23, 3)     
                        }
                        target_range = time_ranges.get(part_of_day.lower())
                        
                        if target_range:
                            start_hour, end_hour = target_range
                            print(f"OpenWeather: Finding forecast for {part_of_day} ({start_hour}h-{end_hour}h local time)...")
                            
                            # Find forecast within requested time range (according to local time)
                            for item in target_forecasts:
                                item_dt_utc = datetime.fromtimestamp(item["dt"], tz=timezone.utc)
                                item_dt_local = item_dt_utc.astimezone(vietnam_tz)
                                hour = item_dt_local.hour
                                # Handle night range (23-3) which crosses midnight
                                if start_hour > end_hour:  # Night range
                                    if hour >= start_hour or hour < end_hour:
                                        forecast = item
                                        print(f"OpenWeather: Found forecast for {part_of_day} at {item_dt_local.strftime('%H:%M')} (local time)")
                                        break
                                elif start_hour <= hour < end_hour:
                                    forecast = item
                                    print(f"OpenWeather: Found forecast for {part_of_day} at {item_dt_local.strftime('%H:%M')} (local time)")
                                    break
                            
                            # If not found in range, get nearest forecast
                            if not forecast:
                                best_forecast = None
                                min_diff = float('inf')
                                for item in target_forecasts:
                                    item_dt_utc = datetime.fromtimestamp(item["dt"], tz=timezone.utc)
                                    item_dt_local = item_dt_utc.astimezone(vietnam_tz)
                                    hour = item_dt_local.hour
                                    # Calculate distance to middle of time range
                                    if start_hour > end_hour:  # Night range
                                        mid_hour = (start_hour + 24 + end_hour) / 2 % 24
                                    else:
                                        mid_hour = (start_hour + end_hour) / 2
                                    diff = abs(hour - mid_hour)
                                    if diff < min_diff:
                                        min_diff = diff
                                        best_forecast = item
                                if best_forecast:
                                    forecast = best_forecast
                                    forecast_dt_utc = datetime.fromtimestamp(forecast["dt"], tz=timezone.utc)
                                    forecast_dt_local = forecast_dt_utc.astimezone(vietnam_tz)
                                    print(f"OpenWeather: Using nearest forecast for {part_of_day} at {forecast_dt_local.strftime('%H:%M')} (local time)")
                    else:
                        # KHÔNG CÓ KHUNG GIỜ: Tổng hợp dữ liệu cho cả ngày (không lấy 1 thời điểm cụ thể)
                        print(f"OpenWeather: No specific time requested - aggregating data for entire day {target_date}...")
                        
                        # Tính toán tổng hợp từ tất cả forecasts trong ngày
                        if len(target_forecasts) > 1:
                            # Tổng hợp: lấy giá trị trung bình và điều kiện thời tiết phổ biến nhất
                            temps = []
                            descriptions = []
                            mains = []
                            humidities = []
                            wind_speeds = []
                            
                            for item in target_forecasts:
                                temps.append(item["main"]["temp"])
                                descriptions.append(item["weather"][0]["description"])
                                mains.append(item["weather"][0]["main"])
                                humidities.append(item["main"]["humidity"])
                                wind_speeds.append(item.get("wind", {}).get("speed", 0))
                            
                            # Tính trung bình
                            avg_temp = sum(temps) / len(temps)
                            avg_feels_like = sum([item["main"]["feels_like"] for item in target_forecasts]) / len(target_forecasts)
                            avg_humidity = sum(humidities) / len(humidities)
                            avg_wind = sum(wind_speeds) / len(wind_speeds)
                            
                            # Tìm điều kiện thời tiết phổ biến nhất (mode)
                            from collections import Counter
                            main_counter = Counter(mains)
                            most_common_main = main_counter.most_common(1)[0][0]
                            
                            # Tìm description phổ biến nhất, nhưng ưu tiên mức độ nghiêm trọng cao hơn
                            # Ví dụ: nếu có "mưa to" ở bất kỳ thời điểm nào, ưu tiên "mưa to" hơn "mưa nhẹ"
                            desc_counter = Counter(descriptions)
                            
                            # Ưu tiên mức độ nghiêm trọng: Thunderstorm > Heavy Rain > Rain > Light Rain > Drizzle
                            severity_order = {
                                "thunderstorm": 5,
                                "heavy": 4,
                                "torrential": 4,
                                "rain": 3,
                                "light": 2,
                                "drizzle": 1
                            }
                            
                            def get_severity(desc: str) -> int:
                                desc_lower = desc.lower()
                                for keyword, score in severity_order.items():
                                    if keyword in desc_lower:
                                        return score
                                return 0
                            
                            # Tìm description có mức độ nghiêm trọng cao nhất
                            most_severe_desc = max(descriptions, key=get_severity)
                            # Nếu có nhiều description cùng mức độ, chọn phổ biến nhất
                            if get_severity(most_severe_desc) == get_severity(desc_counter.most_common(1)[0][0]):
                                most_common_desc = desc_counter.most_common(1)[0][0]
                            else:
                                most_common_desc = most_severe_desc
                            
                            # Tạo forecast tổng hợp
                            forecast = {
                                "main": {"temp": avg_temp, "feels_like": avg_feels_like, "humidity": round(avg_humidity)},
                                "weather": [{"main": most_common_main, "description": most_common_desc}],
                                "wind": {"speed": avg_wind},
                                "dt": target_forecasts[0]["dt"]  # Dùng timestamp của forecast đầu tiên
                            }
                            print(f"OpenWeather: Aggregated data for entire day - {most_common_desc} ({most_common_main}), avg temp {round(avg_temp)}°C")
                        else:
                            # Chỉ có 1 forecast, dùng nó
                            forecast = target_forecasts[0]
                            print(f"OpenWeather: Using single forecast for entire day")
                    
                    # Ensure forecast is set
                    if not forecast:
                        forecast = target_forecasts[0]
                    
                    # Get time from forecast (convert to local timezone)
                    # Nếu không có part_of_day, hiển thị "cả ngày" thay vì thời gian cụ thể
                    if part_of_day:
                        forecast_dt_utc = datetime.fromtimestamp(forecast["dt"], tz=timezone.utc)
                        forecast_dt_local = forecast_dt_utc.astimezone(vietnam_tz)
                        time_str = forecast_dt_local.strftime('%H:%M')
                    else:
                        # Không có thời gian cụ thể → hiển thị "cả ngày"
                        time_str = "cả ngày"
                    
                    # Use normalized_city_name from geopy if available
                    final_location_name = normalized_city_name
                    
                    result = {
                        "location": final_location_name,
                        "date": target_date.strftime('%Y-%m-%d'),
                        "time": time_str,
                        "temperature": forecast["main"]["temp"],
                        "feels_like": forecast["main"]["feels_like"],
                        "description": forecast["weather"][0]["description"],
                        "main": forecast["weather"][0]["main"],
                        "humidity": forecast["main"]["humidity"],
                        "wind_speed": forecast.get("wind", {}).get("speed", 0),
                        "source": "openweathermap.org",
                        "part_of_day": part_of_day  # Lưu thông tin part_of_day để format snippet
                    }
                    if part_of_day:
                        print(f"OpenWeather: Success - {result['location']} on {target_date} {time_str} ({part_of_day}): {result['description']} ({result['temperature']}°C)")
                    else:
                        print(f"OpenWeather: Success - {result['location']} on {target_date} (cả ngày): {result['description']} ({result['temperature']}°C)")
                    return result
                
                print(f"ERROR: No forecast found for '{normalized_city_name}' on date {target_date}")
                return None
        except Exception as e:
            print(f"ERROR: Error getting weather data: {e}")
            return None
    else:
        print(f"ERROR: No lat/lon to get weather data for '{city_name}'")
        return None


def format_openweather_snippet(weather_data: Dict) -> str:
    """
    Format OpenWeather data into detailed snippet in format: date-time-weather.
    This snippet will be used by Agent 2 to compare with input.
    
    Format: [DATE] [TIME] - [WEATHER] at [LOCATION]
    - Nếu có part_of_day: hiển thị thời gian cụ thể
    - Nếu không có part_of_day: hiển thị "cả ngày" (tổng hợp dữ liệu cho cả ngày)
    """
    if not weather_data:
        return ""
    
    location = weather_data.get("location", "N/A")
    date = weather_data.get("date", "N/A")
    time = weather_data.get("time", "N/A")
    temp = round(weather_data.get("temperature", 0))
    feels_like = round(weather_data.get("feels_like", 0))
    description = weather_data.get("description", "N/A")
    main = weather_data.get("main", "N/A")  # Rain, Clear, Clouds, Thunderstorm, etc.
    humidity = weather_data.get("humidity", 0)
    wind = round(weather_data.get("wind_speed", 0) * 3.6, 1)  # Convert m/s to km/h
    part_of_day = weather_data.get("part_of_day")  # "sáng", "chiều", "tối", or None
    
    # Format as requested: date-time-weather
    # Convert date from YYYY-MM-DD to DD/MM/YYYY for readability
    try:
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        date_formatted = date_obj.strftime('%d/%m/%Y')
    except:
        date_formatted = date
    
    # Format time display
    if time == "cả ngày" or not part_of_day:
        # Không có thời gian cụ thể → hiển thị "cả ngày"
        time_display = "cả ngày"
        time_info = f"trong ngày {date_formatted}"
    else:
        # Có khung giờ cụ thể → hiển thị thời gian và khung giờ
        time_display = f"{time} ({part_of_day})"
        time_info = f"vào {part_of_day} ngày {date_formatted} lúc {time}"
    
    # Main format: DATE TIME - WEATHER at LOCATION
    snippet = f"[{date_formatted}] [{time_display}] - {description} ({main}) tại {location} {time_info}. Nhiệt độ {temp}°C (cảm giác như {feels_like}°C). Độ ẩm {humidity}%, gió {wind} km/h. Nguồn: OpenWeatherMap API."
    
    # Add detailed information about weather conditions
    if main == "Rain":
        if "heavy" in description.lower() or "torrential" in description.lower():
            snippet += " [MƯA LỚN/MƯA TO]"
        elif "light" in description.lower() or "drizzle" in description.lower():
            snippet += " [MƯA NHẸ]"
        else:
            snippet += " [MƯA]"
    elif main == "Clear":
        snippet += " [NẮNG/TRỜI QUANG]"
    elif main == "Thunderstorm":
        snippet += " [DÔNG/THUNDERSTORM]"
    elif main == "Clouds":
        snippet += " [CÓ MÂY]"
    
    return snippet
