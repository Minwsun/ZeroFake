# Module: Weather Verification & Classification
# (ĐÃ SỬA ĐỔI - Thêm OpenWeather API để hỗ trợ query thời tiết)

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

    # Kiểm tra pattern "X ngày nữa/tới/sau" hoặc "X days" trước (QUAN TRỌNG: Phải check TRƯỚC các keyword khác)
    import re
    # Pattern 1: "X ngày nữa/tới/sau" hoặc "X days ahead/later" (ưu tiên cao nhất)
    days_pattern = re.search(r'(\d+)\s*(?:ngày|day|days)\s*(?:nữa|sau|tới|toi|ahead|later)', text_lower)
    # Pattern 2: "trong X ngày tới" hoặc "in X days"
    days_pattern2 = re.search(r'(?:trong|in)\s+(\d+)\s*(?:ngày|day|days)\s*(?:tới|toi|ahead)', text_lower)
    
    if days_pattern:
        try:
            days_ahead = int(days_pattern.group(1))
            time_scope = 'present_future'
            relative_time_str = f"{days_ahead} ngày nữa"
            print(f"Classify: Phát hiện '{days_ahead} ngày nữa/tới/sau' từ input -> days_ahead={days_ahead}")
        except ValueError:
            pass
    elif days_pattern2:
        try:
            days_ahead = int(days_pattern2.group(1))
            time_scope = 'present_future'
            relative_time_str = f"trong {days_ahead} ngày tới"
            print(f"Classify: Phát hiện 'trong {days_ahead} ngày tới' từ input -> days_ahead={days_ahead}")
        except ValueError:
            pass
    
    # CHỈ set days_ahead = 0 nếu CHƯA được set bởi pattern ở trên
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
        "part_of_day": part_of_day  # "sáng", "chiều", "tối", hoặc None
    }


def get_openweather_data(city_name: str, days_ahead: int = 0, part_of_day: Optional[str] = None) -> Optional[Dict]:
    """
    Gọi OpenWeather API để lấy dữ liệu thời tiết.
    Sử dụng geopy để geocoding trước, sau đó dùng OpenWeather API.
    
    Args:
        city_name: Tên thành phố (ví dụ: "Hanoi", "Ho Chi Minh City", "Thành phố Hồ Chí Minh")
        days_ahead: Số ngày sau hôm nay (0 = hôm nay, 1 = ngày mai, ...)
        part_of_day: Phần trong ngày ("sáng", "chiều", "tối") hoặc None
    
    Returns:
        dict: Dữ liệu thời tiết từ OpenWeather hoặc None nếu lỗi
    """
    if not OPENWEATHER_API_KEY:
        print("ERROR: OPENWEATHER_API_KEY chưa được cấu hình trong .env file.")
        print("Hướng dẫn: Thêm OPENWEATHER_API_KEY=your_api_key vào file .env")
        return None
    
    print(f"OpenWeather: Đang tìm kiếm địa điểm '{city_name}'...")
    
    # Bước 0: Sử dụng geopy để geocoding trước (nếu có) - hỗ trợ toàn cầu
    lat = None
    lon = None
    normalized_city_name = city_name
    
    try:
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut, GeocoderServiceError
        
        print(f"Geopy: Đang geocoding '{city_name}' (toàn cầu)...")
        geolocator = Nominatim(user_agent="ZeroFake-FactChecker/1.0")
        
        # Thử nhiều cách tìm kiếm để tăng độ chính xác cho địa danh toàn cầu
        location = None
        
        # Cách 1: Tìm kiếm trực tiếp với tên gốc
        try:
            location = geolocator.geocode(city_name, timeout=10, language='en', exactly_one=True)
        except Exception as e:
            print(f"Geopy: Lỗi khi geocode '{city_name}': {e}")
        
        # Cách 2: Nếu không tìm thấy, thử thêm "city" hoặc "thành phố" vào cuối
        if not location:
            try:
                if "city" not in city_name.lower() and "thành phố" not in city_name.lower():
                    location = geolocator.geocode(f"{city_name}, city", timeout=10, language='en', exactly_one=True)
            except Exception:
                pass
        
        # Cách 3: Nếu vẫn không tìm thấy, thử tìm kiếm rộng hơn
        if not location:
            try:
                results = geolocator.geocode(city_name, timeout=10, language='en', exactly_one=False)
                if results and len(results) > 0:
                    # Chọn kết quả đầu tiên (có thể cải thiện logic chọn sau)
                    location = results[0]
            except Exception:
                pass
        
        if location and location.latitude and location.longitude:
            lat = location.latitude
            lon = location.longitude
            # Lấy tên chuẩn hóa từ geopy (thường là tiếng Anh)
            address_parts = location.address.split(',')
            normalized_city_name = address_parts[0].strip()
            
            # Thử lấy tên tiếng Anh từ raw data nếu có
            if hasattr(location, 'raw') and location.raw:
                raw_data = location.raw
                if 'display_name' in raw_data:
                    display_name = raw_data['display_name']
                    normalized_city_name = display_name.split(',')[0].strip()
                elif 'name' in raw_data:
                    normalized_city_name = raw_data['name']
            
            print(f"Geopy: Tìm thấy '{normalized_city_name}' tại [{lat}, {lon}]")
        else:
            print(f"Geopy: Không tìm thấy '{city_name}', sẽ thử OpenWeather geocoding")
    except ImportError:
        print("Geopy: Không có geopy, bỏ qua geocoding bằng geopy")
    except GeocoderTimedOut:
        print(f"Geopy: Timeout khi geocoding '{city_name}', sẽ thử OpenWeather geocoding")
    except GeocoderServiceError as e:
        print(f"Geopy: Service error khi geocoding '{city_name}': {e}, sẽ thử OpenWeather geocoding")
    except Exception as e:
        print(f"Geopy: Lỗi khi geocoding '{city_name}': {type(e).__name__}: {e}, sẽ thử OpenWeather geocoding")
    
    # Nếu geopy không tìm thấy, dùng OpenWeather geocoding
    if lat is None or lon is None:
        # Mapping tên thành phố Việt Nam sang tiếng Anh (để geocoding tốt hơn)
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
        
        # Thử dùng tên tiếng Anh nếu có trong map
        query_city = CITY_NAME_MAP.get(city_name, city_name)
        if query_city != city_name:
            print(f"OpenWeather: Chuyển đổi '{city_name}' -> '{query_city}' để geocoding tốt hơn")
        else:
            query_city = normalized_city_name if normalized_city_name != city_name else city_name
        
        try:
            # Bước 1: Geocoding bằng OpenWeather API (đúng định dạng)
            geocode_url = "http://api.openweathermap.org/geo/1.0/direct"
            geocode_params = {
                "q": query_city,
                "limit": 1,  # Chỉ lấy 1 kết quả tốt nhất (theo yêu cầu)
                "appid": OPENWEATHER_API_KEY
            }
            
            print(f"OpenWeather: Gọi geocoding API với query: '{query_city}'")
            geocode_response = requests.get(geocode_url, params=geocode_params, timeout=10)
            
            # Kiểm tra status code
            if geocode_response.status_code == 401:
                print("ERROR: OpenWeather API key không hợp lệ hoặc đã hết hạn.")
                return None
            elif geocode_response.status_code == 429:
                print("ERROR: OpenWeather API rate limit đã vượt quá. Vui lòng thử lại sau.")
                return None
            elif geocode_response.status_code != 200:
                print(f"ERROR: OpenWeather geocoding API trả về status code {geocode_response.status_code}")
                print(f"Response: {geocode_response.text[:200]}")
                return None
            
            geocode_response.raise_for_status()
            geocode_data = geocode_response.json()
            
            if not geocode_data or len(geocode_data) == 0:
                print(f"ERROR: OpenWeather không tìm thấy địa điểm '{query_city}' (original: '{city_name}')")
                # Thử lại với tên gốc nếu đã dùng mapping
                if query_city != city_name:
                    print(f"OpenWeather: Thử lại với tên gốc '{city_name}'...")
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
                            print(f"OpenWeather: Thành công với tên gốc '{city_name}'")
                        else:
                            print(f"ERROR: Vẫn không tìm thấy với tên gốc '{city_name}'")
                            print(f"Gợi ý: Kiểm tra tên thành phố hoặc thử dùng tên tiếng Anh")
                            return None
                    else:
                        print(f"ERROR: Geocoding retry failed với status {geocode_response_retry.status_code}")
                        return None
                else:
                    print(f"Gợi ý: Thử dùng tên tiếng Anh (ví dụ: 'Ho Chi Minh City' thay vì 'Thành phố Hồ Chí Minh')")
                    return None
            
            # Chọn kết quả đầu tiên (có thể cải thiện logic chọn sau)
            selected = geocode_data[0]
            lat = selected["lat"]
            lon = selected["lon"]
            location_name = selected.get("name", city_name)
            country = selected.get("country", "")
            
            print(f"OpenWeather: Tìm thấy '{location_name}' ({country}) tại [{lat}, {lon}]")
        except Exception as e:
            print(f"ERROR: Lỗi khi geocoding bằng OpenWeather: {e}")
            return None
    
    # Bước 2: Lấy dữ liệu thời tiết (dùng lat, lon từ geopy hoặc OpenWeather)
    if lat is not None and lon is not None:
        try:
            # Đảm bảo days_ahead không None
            if days_ahead is None:
                days_ahead = 0
                print(f"OpenWeather: WARNING - days_ahead là None, sử dụng 0 (hôm nay)")
            
            print(f"OpenWeather: DEBUG - days_ahead = {days_ahead}, part_of_day = {part_of_day}")
            
            if days_ahead == 0:
                # Current weather (chỉ khi days_ahead = 0)
                weather_url = "https://api.openweathermap.org/data/2.5/weather"
                weather_params = {
                    "lat": lat,
                    "lon": lon,
                    "appid": OPENWEATHER_API_KEY,
                    "units": "metric",
                    "lang": "vi"
                }
                print(f"OpenWeather: Lấy thời tiết hiện tại cho [{lat}, {lon}]...")
                weather_response = requests.get(weather_url, params=weather_params, timeout=10)
                
                if weather_response.status_code == 401:
                    print("ERROR: OpenWeather API key không hợp lệ khi gọi weather API.")
                    return None
                elif weather_response.status_code == 429:
                    print("ERROR: OpenWeather API rate limit đã vượt quá khi gọi weather API.")
                    return None
                elif weather_response.status_code != 200:
                    print(f"ERROR: OpenWeather weather API trả về status code {weather_response.status_code}")
                    print(f"Response: {weather_response.text[:200]}")
                    return None
                
                weather_response.raise_for_status()
                weather_data = weather_response.json()
                
                if not weather_data or "main" not in weather_data:
                    print("ERROR: OpenWeather API trả về dữ liệu không hợp lệ (thiếu 'main' field)")
                    return None
                
                # Lấy thời gian cụ thể từ API (nếu có)
                current_time = datetime.now()
                time_str = current_time.strftime('%H:%M')
                
                # Sử dụng normalized_city_name từ geopy nếu có
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
                print(f"OpenWeather: Thành công - {result['location']}: {result['description']} ({result['temperature']}°C) vào {result['date']} {result['time']}")
                return result
            elif days_ahead > 0:
                # Forecast - Thử One Call API 3.0 trước, fallback về 2.5 nếu không có
                # One Call API 3.0: hourly forecast trong 48h, daily trong 7 ngày
                onecall_url = "https://api.openweathermap.org/data/3.0/onecall"
                onecall_params = {
                    "lat": lat,
                    "lon": lon,
                    "exclude": "current,minutely,daily,alerts",  # Chỉ lấy hourly
                    "units": "metric",
                    "lang": "vi",
                    "appid": OPENWEATHER_API_KEY
                }
                
                print(f"OpenWeather: Thử One Call API 3.0 cho dự báo {days_ahead} ngày tới tại [{lat}, {lon}]...")
                onecall_response = requests.get(onecall_url, params=onecall_params, timeout=10)
                
                # Nếu One Call API 3.0 không có (401, 403, hoặc không có subscription), fallback về 2.5
                use_onecall = False
                if onecall_response.status_code == 200:
                    try:
                        onecall_data = onecall_response.json()
                        if "hourly" in onecall_data:
                            use_onecall = True
                            forecast_data = {"list": onecall_data["hourly"], "source": "onecall3"}
                            print(f"OpenWeather: Sử dụng One Call API 3.0 (hourly forecast)")
                    except Exception as e:
                        print(f"OpenWeather: Lỗi khi parse One Call API 3.0: {e}, fallback về 2.5")
                
                if not use_onecall:
                    # Fallback về Forecast API 2.5
                    forecast_url = "https://api.openweathermap.org/data/2.5/forecast"
                    forecast_params = {
                        "lat": lat,
                        "lon": lon,
                        "appid": OPENWEATHER_API_KEY,
                        "units": "metric",
                        "lang": "vi"
                    }
                    print(f"OpenWeather: Fallback về Forecast API 2.5 cho dự báo {days_ahead} ngày tới...")
                    forecast_response = requests.get(forecast_url, params=forecast_params, timeout=10)
                    
                    if forecast_response.status_code == 401:
                        print("ERROR: OpenWeather API key không hợp lệ khi gọi forecast API.")
                        return None
                    elif forecast_response.status_code == 429:
                        print("ERROR: OpenWeather API rate limit đã vượt quá khi gọi forecast API.")
                        return None
                    elif forecast_response.status_code != 200:
                        print(f"ERROR: OpenWeather forecast API trả về status code {forecast_response.status_code}")
                        print(f"Response: {forecast_response.text[:200]}")
                        return None
                    
                    forecast_response.raise_for_status()
                    forecast_data_raw = forecast_response.json()
                    forecast_data = {"list": forecast_data_raw.get("list", []), "source": "forecast25"}
                    
                    if not forecast_data["list"]:
                        print("ERROR: OpenWeather forecast API trả về dữ liệu không hợp lệ (thiếu 'list' field)")
                        return None
                
                # Tìm forecast cho ngày cụ thể
                # Đảm bảo days_ahead không None
                if days_ahead is None:
                    days_ahead = 0
                    print(f"OpenWeather: WARNING - days_ahead là None trong forecast, sử dụng 0")
                
                target_date = (datetime.now() + timedelta(days=days_ahead)).date()
                target_forecasts = []
                
                print(f"OpenWeather: Tìm forecast cho ngày {target_date} (days_ahead={days_ahead})...")
                
                # Lấy tất cả forecast cho ngày target
                # Chuyển đổi timestamp sang timezone địa phương (UTC+7 cho Việt Nam)
                vietnam_tz = timezone(timedelta(hours=7))  # UTC+7
                
                forecast_list = forecast_data.get("list", [])
                print(f"OpenWeather: Có {len(forecast_list)} forecast items để tìm kiếm...")
                
                for item in forecast_list:
                    # Chuyển đổi timestamp sang datetime với timezone
                    item_dt_utc = datetime.fromtimestamp(item["dt"], tz=timezone.utc)
                    item_dt_local = item_dt_utc.astimezone(vietnam_tz)
                    item_date = item_dt_local.date()
                    
                    if item_date == target_date:
                        target_forecasts.append(item)
                        print(f"OpenWeather: Tìm thấy forecast cho {target_date} lúc {item_dt_local.strftime('%H:%M')} (local time)")
                
                # Nếu không tìm thấy forecast cho ngày chính xác, tìm forecast gần nhất trong tương lai
                if not target_forecasts:
                    print(f"WARNING: Không tìm thấy forecast cho ngày {target_date}, tìm forecast gần nhất trong tương lai...")
                    # Sắp xếp tất cả forecast theo thời gian (với timezone địa phương)
                    all_forecasts = []
                    for item in forecast_list:
                        item_dt_utc = datetime.fromtimestamp(item["dt"], tz=timezone.utc)
                        item_dt_local = item_dt_utc.astimezone(vietnam_tz)
                        item_date = item_dt_local.date()
                        if item_date >= target_date:  # Chỉ lấy forecast từ target_date trở đi
                            all_forecasts.append((item_date, item_dt_local, item))
                    
                    if all_forecasts:
                        # Sắp xếp theo ngày và giờ (gần nhất trước)
                        all_forecasts.sort(key=lambda x: (x[0], x[1]))
                        # Lấy forecast đầu tiên (gần nhất)
                        closest_date, closest_time_local, closest_item = all_forecasts[0]
                        target_forecasts = [closest_item]
                        print(f"OpenWeather: Sử dụng forecast gần nhất cho ngày {closest_date} lúc {closest_time_local.strftime('%H:%M')} (local time, thay vì {target_date})")
                    else:
                        # Nếu vẫn không có, lấy forecast cuối cùng (xa nhất trong tương lai)
                        if forecast_list:
                            last_item = forecast_list[-1]
                            target_forecasts = [last_item]
                            last_dt_utc = datetime.fromtimestamp(last_item["dt"], tz=timezone.utc)
                            last_dt_local = last_dt_utc.astimezone(vietnam_tz)
                            last_date = last_dt_local.date()
                            print(f"OpenWeather: WARNING - Sử dụng forecast cuối cùng cho ngày {last_date} lúc {last_dt_local.strftime('%H:%M')} (local time, thay vì {target_date})")
                
                if target_forecasts:
                    # Chọn forecast đúng thời điểm trong ngày (nếu có yêu cầu)
                    forecast = None
                    if part_of_day:
                        # Xác định khoảng thời gian dựa trên part_of_day (theo giờ địa phương UTC+7)
                        time_ranges = {
                            "sáng": (3, 10),   # 6h-12h (local time)
                            "chiều": (10, 17),  # 12h-18h (local time)
                            "tối": (17, 23),    # 18h-24h (local time)
                            "đêm": (23, 3)     # 20h-24h (local time)
                        }
                        target_range = time_ranges.get(part_of_day.lower())
                        
                        if target_range:
                            start_hour, end_hour = target_range
                            print(f"OpenWeather: Tìm forecast cho {part_of_day} ({start_hour}h-{end_hour}h local time)...")
                            
                            # Tìm forecast trong khoảng thời gian yêu cầu (theo giờ địa phương)
                            for item in target_forecasts:
                                item_dt_utc = datetime.fromtimestamp(item["dt"], tz=timezone.utc)
                                item_dt_local = item_dt_utc.astimezone(vietnam_tz)
                                hour = item_dt_local.hour
                                if start_hour <= hour < end_hour:
                                    forecast = item
                                    print(f"OpenWeather: Tìm thấy forecast cho {part_of_day} lúc {item_dt_local.strftime('%H:%M')} (local time)")
                                    break
                            
                            # Nếu không tìm thấy trong khoảng, lấy forecast gần nhất
                            if not forecast:
                                best_forecast = None
                                min_diff = float('inf')
                                for item in target_forecasts:
                                    item_dt_utc = datetime.fromtimestamp(item["dt"], tz=timezone.utc)
                                    item_dt_local = item_dt_utc.astimezone(vietnam_tz)
                                    hour = item_dt_local.hour
                                    # Tính khoảng cách đến giữa khoảng thời gian
                                    mid_hour = (start_hour + end_hour) / 2
                                    diff = abs(hour - mid_hour)
                                    if diff < min_diff:
                                        min_diff = diff
                                        best_forecast = item
                                if best_forecast:
                                    forecast = best_forecast
                                    forecast_dt_utc = datetime.fromtimestamp(forecast["dt"], tz=timezone.utc)
                                    forecast_dt_local = forecast_dt_utc.astimezone(vietnam_tz)
                                    print(f"OpenWeather: Sử dụng forecast gần nhất cho {part_of_day} lúc {forecast_dt_local.strftime('%H:%M')} (local time)")
                    
                    # Nếu không có part_of_day hoặc không tìm thấy, lấy forecast đầu tiên
                    if not forecast:
                        forecast = target_forecasts[0]
                    
                    # Lấy thời gian từ forecast (chuyển đổi sang timezone địa phương)
                    forecast_dt_utc = datetime.fromtimestamp(forecast["dt"], tz=timezone.utc)
                    forecast_dt_local = forecast_dt_utc.astimezone(vietnam_tz)
                    time_str = forecast_dt_local.strftime('%H:%M')
                    
                    # Sử dụng normalized_city_name từ geopy nếu có
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
                        "source": "openweathermap.org"
                    }
                    print(f"OpenWeather: Thành công - {result['location']} ngày {target_date} {time_str}: {result['description']} ({result['temperature']}°C)")
                    return result
                
                print(f"ERROR: Không tìm thấy forecast nào cho '{normalized_city_name}' ngày {target_date}")
                return None
        except Exception as e:
            print(f"ERROR: Lỗi khi lấy dữ liệu thời tiết: {e}")
            return None
    else:
        print(f"ERROR: Không có lat/lon để lấy dữ liệu thời tiết cho '{city_name}'")
        return None


def format_openweather_snippet(weather_data: Dict) -> str:
    """
    Format dữ liệu OpenWeather thành snippet chi tiết theo format: date-time-thời tiết.
    Snippet này sẽ được Agent 2 sử dụng để so sánh với input.
    
    Format: [DATE] [TIME] - [THỜI TIẾT] tại [LOCATION]
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
    wind = round(weather_data.get("wind_speed", 0) * 3.6, 1)  # Chuyển m/s sang km/h
    
    # Format theo yêu cầu: date-time-thời tiết
    # Chuyển đổi date từ YYYY-MM-DD sang DD/MM/YYYY cho dễ đọc
    try:
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        date_formatted = date_obj.strftime('%d/%m/%Y')
    except:
        date_formatted = date
    
    # Format chính: DATE TIME - THỜI TIẾT tại LOCATION
    snippet = f"[{date_formatted}] [{time}] - {description} ({main}) tại {location}. Nhiệt độ {temp}°C (cảm giác như {feels_like}°C). Độ ẩm {humidity}%, gió {wind} km/h. Nguồn: OpenWeatherMap API."
    
    # Thêm thông tin chi tiết về điều kiện thời tiết
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
