# app/agent_planner.py
import os
import json
import google.generativeai as genai
import re
import asyncio
from dotenv import load_dotenv
from typing import List, Optional

from app.weather import extract_weather_info, classify_claim

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PLANNER_PROMPT = ""


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


def _normalize_plan(plan: dict, text_input: str) -> dict:
    """Đảm bảo plan đủ schema, điền đúng mục thông tin, và tạo search/weather module phù hợp."""
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

    # Helper: trích relative_time (sáng/chiều/tối + hôm nay/mai)
    tl = text_input.lower()
    part_of_day = None
    if any(k in tl for k in ["sáng", "morning"]):
        part_of_day = "sáng"
    elif any(k in tl for k in ["chiều", "afternoon"]):
        part_of_day = "chiều"
    elif any(k in tl for k in ["tối", "đêm", "evening", "night"]):
        part_of_day = "tối"
    base_rel = None
    if "hôm nay" in tl or "today" in tl:
        base_rel = "hôm nay"
        plan_struct["time_references"]["time_scope"] = "present"
    elif "ngày mai" in tl or "mai" in tl or "tomorrow" in tl:
        base_rel = "ngày mai"
        plan_struct["time_references"]["time_scope"] = "future"
    elif any(k in tl for k in ["hôm qua", "yesterday", "năm trước", "tuần trước"]):
        base_rel = "hôm qua"
        plan_struct["time_references"]["time_scope"] = "historical"
    # Kết hợp relative_time chi tiết
    if base_rel and part_of_day:
        plan_struct["time_references"]["relative_time"] = f"{part_of_day} {base_rel}"
    elif base_rel:
        plan_struct["time_references"]["relative_time"] = base_rel

    # Trích data_points (ví dụ 40°C, mm mưa, %)
    data_points = set(plan_struct["entities_and_values"]["data_points"] or [])
    for m in re.findall(r"\b\d{1,3}\s?(?:°C|mm|%)\b", text_input):
        data_points.add(m.strip())
    plan_struct["entities_and_values"]["data_points"] = list(data_points)

    # Phát hiện claim thời tiết và thành phố
    try:
        info = extract_weather_info(text_input)
        claim = classify_claim(text_input)
    except Exception:
        info, claim = None, {"is_weather": False}

    if claim.get("is_weather"):
        city = (info or {}).get("city")
        if city and city not in plan_struct["entities_and_values"]["locations"]:
            plan_struct["entities_and_values"]["locations"].append(city)
        plan_struct["claim_type"] = "Thời tiết"
        plan_struct["volatility"] = "high"

        # Thêm weather module với tham số phù hợp
        time_scope_norm = plan_struct["time_references"]["time_scope"]
        weather_module = {
            "tool_name": "weather",
            "parameters": {
                "location": city or "",
                "time_scope": time_scope_norm,
                "relative_time": plan_struct["time_references"].get("relative_time"),
                "explicit_date": plan_struct["time_references"].get("explicit_date")
            }
        }
        plan_struct["required_tools"].append(weather_module)

    # Tạo bộ câu truy vấn search tốt hơn
    has_search = any(m.get('tool_name') == 'search' for m in plan_struct["required_tools"])
    if not has_search:
        queries = [text_input]
        # mở rộng nếu có thành phố và relative_time
        city = (info or {}).get("city") if info else None
        rel = plan_struct["time_references"].get("relative_time")
        if city:
            base_kw = ["dự báo thời tiết", "mưa", "nhiệt độ", "cảnh báo"]
            for kw in base_kw:
                q = f"{kw} {city}"
                if rel:
                    q = f"{q} {rel}"
                queries.append(q)
        plan_struct["required_tools"].append({
            "tool_name": "search",
            "parameters": {"queries": list(dict.fromkeys(queries)), "search_type": "precise_data" if city else "broad"}
        })

    return plan_struct


async def create_action_plan(text_input: str) -> dict:
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

    model_names = [
        'gemini-1.5-flash-002',
        'models/gemini-1.5-flash-002',
        'gemini-1.5-flash-latest',
        'models/gemini-1.5-flash-latest',
        'gemini-1.5-flash-8b',
        'models/gemini-1.5-flash-8b',
        'gemini-1.5-flash'
    ]

    # Cố gắng lấy danh sách model khả dụng và ưu tiên cái phù hợp
    try:
        available = list(genai.list_models())
        available_names = {m.name: m for m in available}
        supported = []
        for name in model_names:
            m = available_names.get(name)
            if m and ('generateContent' in (getattr(m, 'supported_generation_methods', []) or [])):
                supported.append(name)
        if supported:
            model_names = supported
        else:
            flash_fallback = [m.name for m in available if 'generateContent' in (getattr(m, 'supported_generation_methods', []) or []) and 'flash' in m.name]
            if flash_fallback:
                model_names = flash_fallback
    except Exception:
        pass

    last_err = None
    for model_name in model_names:
        try:
            print(f"Planner: thử model '{model_name}'")
            model = genai.GenerativeModel(model_name)
            # Dùng sync API để tránh khác biệt async giữa các phiên bản SDK
            response = await asyncio.to_thread(model.generate_content, prompt)
            text = getattr(response, 'text', None)
            if text is None and hasattr(response, 'candidates') and response.candidates:
                parts = getattr(response.candidates[0], 'content', None)
                text = str(parts)
            if not text:
                raise RuntimeError("LLM trả về rỗng")
            plan_json = _parse_json_from_text(text)
            plan_json = _normalize_plan(plan_json, text_input)
            if plan_json:
                return plan_json
        except Exception as e:
            last_err = e
            continue

    print(f"Lỗi khi gọi Agent 1 (Planner): {last_err}")
    # Trả về kế hoạch dự phòng: có search + auto suy luận weather nếu có thể
    fallback = _normalize_plan({}, text_input)
    return fallback
