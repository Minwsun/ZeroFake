# app/tool_executor.py
import asyncio
from urllib.parse import urlparse
from datetime import datetime
import json

# Feature flags / diagnostics
USE_WEATHER_API = True  # Use OpenWeather API with precise date/location; CSE used as fallback when disabled

# Import các tool thực thi
from app.search import call_google_search
from app.weather import (
    get_current_weather,
    get_forecast_data,
    get_forecast_for_date,
    get_historical_weather,
    forecast_window_supported,
    relative_to_date,
    resolve_time_parameters,
)
from app.ranker import get_rank_from_url, _extract_date


# --- MODULE THỰC THI TOOL ---

async def _execute_search_tool(parameters: dict, site_query_string: str) -> dict:
    """
    Thực thi mô-đun "search".
    Phân loại kết quả vào các Lớp 2, 3, 4.
    """
    queries = parameters.get("queries", [])
    if not queries:
        return {"tool_name": "search", "status": "no_queries", "layer_2": [], "layer_3": [], "layer_4": []}

    all_items = []
    seen_urls = set()

    for query in queries:
        try:
            search_items = await asyncio.to_thread(call_google_search, query, site_query_string)
            for item in search_items:
                link = item.get('link')
                if link and link not in seen_urls:
                    all_items.append(item)
                    seen_urls.add(link)
        except Exception as e:
            print(f"Lỗi khi thực thi search query '{query}': {e}")

    # Phân loại kết quả vào các Lớp
    layer_2 = []
    layer_3 = []
    layer_4 = []

    for item in all_items:
        link = item.get('link', '')
        rank_score = get_rank_from_url(link)
        
        evidence_item = {
            "source": urlparse(link).netloc.replace('www.', ''),
            "url": link,
            "snippet": (item.get('snippet', '') or '').replace('\n', ' '),
            "rank_score": rank_score,
            "date": _extract_date(item)
        }
        
        # Phân loại dựa trên rank_score từ config.json
        if rank_score > 0.9:
            layer_2.append(evidence_item)
        elif rank_score > 0.5:
            layer_3.append(evidence_item)
        else:
            layer_4.append(evidence_item)

    layer_2.sort(key=lambda x: x.get('date') or '1970-01-01', reverse=True)
    layer_3.sort(key=lambda x: x.get('date') or '1970-01-01', reverse=True)

    return {
        "tool_name": "search", "status": "success",
        "layer_2_high_trust": layer_2,
        "layer_3_general": layer_3,
        "layer_4_social_low": layer_4
    }


async def _execute_weather_via_cse(parameters: dict, site_query_string: str) -> dict:
    """
    Weather via CSE only: xây dựng bộ truy vấn theo location + thời gian, thu thập bài báo/nguồn dữ liệu thời tiết.
    Trả về như một tool lớp 1 để Agent 2 ưu tiên.
    """
    location = (parameters.get("location") or '').strip()
    relative_time = parameters.get("relative_time")
    explicit_date = parameters.get("explicit_date")

    target_date, part_of_day = resolve_time_parameters(relative_time, explicit_date)

    # Tạo bộ query đa dạng, ưu tiên site uy tín (SITE_QUERY_STRING sẽ được nối trong call_google_search)
    queries = []
    base_terms = ["dự báo thời tiết", "mưa", "lượng mưa", "nhiệt độ", "độ ẩm", "gió"]
    date_term = (target_date or '').strip()
    pod_term = None
    if part_of_day == 'morning':
        pod_term = 'sáng'
    elif part_of_day == 'afternoon':
        pod_term = 'chiều'
    elif part_of_day == 'evening':
        pod_term = 'tối'

    if location:
        for t in base_terms:
            q = f"{t} {location}"
            if pod_term:
                q += f" {pod_term}"
            if date_term:
                q += f" {date_term}"
            queries.append(q)
    # thêm câu tổng quát từ text gốc nếu có
    original_text = parameters.get("original_text")
    if original_text:
        queries.append(original_text)

    # Loại trùng, giữ tối đa ~8 query
    seen = set()
    uniq_queries = []
    for q in queries:
        if q and q not in seen:
            uniq_queries.append(q)
            seen.add(q)
        if len(uniq_queries) >= 8:
            break

    # Gọi CSE và gom kết quả như lớp search, nhưng đóng gói trong lớp 1 để ưu tiên
    search_params = {"queries": uniq_queries, "search_type": "precise_data"}
    search_res = await _execute_search_tool(search_params, site_query_string)

    return {
        "tool_name": "weather_cse",
        "status": "success",
        "diagnostics": {"weather_api_used": False, "reason": "Configured to use CSE-only for weather."},
        "data": {
            "location": location,
            "target_date": target_date,
            "part_of_day": part_of_day,
            "layer_2_high_trust": search_res.get("layer_2_high_trust", []),
            "layer_3_general": search_res.get("layer_3_general", []),
            "layer_4_social_low": search_res.get("layer_4_social_low", [])
        }
    }


async def _execute_weather_tool(parameters: dict, site_query_string: str = "") -> dict:
    """
    Thực thi mô-đun "weather".
    Nếu USE_WEATHER_API=False, dùng CSE-only; ngược lại giữ luồng API (present/future/historical).
    """
    if not USE_WEATHER_API:
        return await _execute_weather_via_cse(parameters, site_query_string)

    tool_name = "weather"
    try:
        location = parameters.get("location")
        time_scope = parameters.get("time_scope", "present")
        relative_time = parameters.get("relative_time")
        explicit_date = parameters.get("explicit_date")

        if not location:
            return {"tool_name": tool_name, "status": "error", "reason": "Không thể xác định địa danh."}

        # 1. Giải quyết tham số thời gian
        target_date, part_of_day = resolve_time_parameters(relative_time, explicit_date)

        # 2. Gọi tool phù hợp
        data = None
        mode = "unknown"
        if time_scope == "historical":
            mode = "historical"
            if not target_date:
                return {"tool_name": tool_name, "status": "historical_date_required", "reason": "Thiếu ngày cụ thể cho dữ liệu lịch sử."}
            data = await asyncio.to_thread(get_historical_weather, location, target_date)

        elif time_scope == "future":
            mode = "future"
            data = await asyncio.to_thread(get_forecast_for_date, location, target_date, part_of_day)

        else:  # present
            mode = "present"
            data = await asyncio.to_thread(get_current_weather, location)

        # 3. Trả về kết quả
        if data:
            return {"tool_name": tool_name, "status": "success", "mode": mode, "data": data, "diagnostics": {"weather_api_used": True}}
        else:
            return {"tool_name": tool_name, "status": "api_error", "reason": f"Không gọi được API cho {location} với mode {mode}.", "diagnostics": {"weather_api_used": True}}

    except Exception as e:
        return {"tool_name": tool_name, "status": "error", "reason": str(e), "diagnostics": {"weather_api_used": True}}


# --- BỘ ĐIỀU PHỐI THỰC THI (Executor Orchestrator) ---

def enrich_plan_with_evidence(plan: dict, evidence_bundle: dict) -> dict:
    """Làm giàu kế hoạch: điền thông tin đúng mục, theo ưu tiên Lớp 1 -> Lớp 2 -> Lớp 3.
    - Tập trung tốt cho case thời tiết: city, nhiệt độ, độ ẩm, gió.
    - Trích data_points bổ sung từ snippet báo chí (°C, mm, %).
    """
    import re
    enriched = json.loads(json.dumps(plan))  # deep copy đơn giản
    ev = enriched.get("entities_and_values") or {"locations": [], "persons": [], "organizations": [], "events": [], "data_points": []}

    # 1) Ưu tiên Lớp 1: weather (API hoặc CSE)
    for item in evidence_bundle.get("layer_1_tools", []):
        if item.get("tool_name") in ("weather", "weather_cse") and item.get("status") == "success":
            data = item.get("data") or {}
            city = (data.get("city") or data.get("location") or '').strip()
            if city and city not in ev.get("locations", []):
                ev.setdefault("locations", []).append(city)
            # data points từ API nếu có
            for key, suffix in [("temperature", "°C"), ("humidity", "%"), ("wind_speed", "m/s")]:
                val = data.get(key)
                if isinstance(val, (int, float)):
                    ev.setdefault("data_points", []).append(f"{val}{suffix}")
            enriched["entities_and_values"] = ev
            break

    # 2) Trích thêm data_points từ snippets Lớp 2, sau đó Lớp 3
    def snippets(lvl: str):
        return [x.get("snippet") or "" for x in evidence_bundle.get(lvl, [])]

    import re as _re
    pattern = _re.compile(r"\b\d{1,3}\s?(?:°C|mm|%)\b")
    for lvl in ["layer_2_high_trust", "layer_3_general"]:
        for sn in snippets(lvl):
            for m in pattern.findall(sn):
                if m not in ev.setdefault("data_points", []):
                    ev["data_points"].append(m)
    enriched["entities_and_values"] = ev

    return enriched


async def execute_tool_plan(plan: dict, site_query_string: str) -> dict:
    """
    Điều phối việc gọi các tool dựa trên Kế hoạch thực thi (mô-đun) và tập hợp Gói Bằng Chứng 4 Lớp.
    """
    required_tools = plan.get("required_tools", [])
    
    evidence_bundle = {
        "layer_1_tools": [],
        "layer_2_high_trust": [],
        "layer_3_general": [],
        "layer_4_social_low": []
    }
    
    tasks = []
    
    # Tạo các task bất đồng bộ cho từng mô-đun
    for module in required_tools:
        tool_name = module.get("tool_name")
        parameters = module.get("parameters", {})
        
        if tool_name == "search":
            tasks.append(_execute_search_tool(parameters, site_query_string))
        elif tool_name == "weather":
            tasks.append(_execute_weather_tool(parameters, site_query_string))
        # (Có thể bổ sung: econ_data, sports_results ...)
    
    if not tasks:
        print("Cảnh báo: Không có tool nào được lập kế hoạch.")
        return evidence_bundle

    # Chạy song song các tool
    results = await asyncio.gather(*tasks)
    
    # Tập hợp kết quả vào Gói Bằng Chứng
    has_weather_success = False
    for res in results:
        if not res:
            continue
        tn = res.get("tool_name")
        if tn == "search":
            evidence_bundle["layer_2_high_trust"].extend(res.get("layer_2_high_trust", []))
            evidence_bundle["layer_3_general"].extend(res.get("layer_3_general", []))
            evidence_bundle["layer_4_social_low"].extend(res.get("layer_4_social_low", []))
        elif tn in ["weather", "weather_cse", "econ_data", "sports_results"]:
            evidence_bundle["layer_1_tools"].append(res)
            if tn in ("weather", "weather_cse") and res.get("status") == "success":
                has_weather_success = True

    # Fallback: nếu chưa có dữ liệu lớp 1 cho thời tiết, thử gọi lại (chỉ áp dụng khi có city)
    if not has_weather_success:
        tr = plan.get("time_references", {})
        city = None
        try:
            city = (plan.get("entities_and_values", {}) or {}).get("locations", [None])[0]
        except Exception:
            city = None
        time_scope = tr.get("time_scope") or "present"
        rel = tr.get("relative_time")
        explicit = tr.get("explicit_date")
        if city:
            extra_res = await _execute_weather_tool({
                "location": city,
                "time_scope": time_scope,
                "relative_time": rel,
                "explicit_date": explicit,
                "original_text": plan.get("main_claim")
            }, site_query_string)
            evidence_bundle["layer_1_tools"].append(extra_res)

    return evidence_bundle
