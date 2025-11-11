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
        relative_time = claim.get("relative_time")
        # Lưu city thô vào entities
        if city and city not in (plan_struct["entities_and_values"].get("locations") or []):
            plan_struct["entities_and_values"].setdefault("locations", []).append(city)
        # Tạo query ngôn ngữ tự nhiên
        if city and relative_time:
            weather_queries.append(f"thời tiết {city} {relative_time}")
            weather_queries.append(f"dự báo thời tiết {city} {relative_time}")
            plan_struct["time_references"]["relative_time"] = relative_time
        elif city:
            weather_queries.append(f"thời tiết {city}")

    # Tạo bộ câu truy vấn search
    has_search = any(m.get('tool_name') == 'search' for m in plan_struct["required_tools"])
    if not has_search:
        default_queries = [q for m in plan_struct.get("required_tools", []) if m.get("tool_name") == "search" for q in m.get("parameters", {}).get("queries", [])]
        if not default_queries:
            default_queries = [text_input]
        final_queries = weather_queries + default_queries
        plan_struct["required_tools"].append({
            "tool_name": "search",
            "parameters": {"queries": list(dict.fromkeys(final_queries)), "search_type": "broad"}
        })

    # Xóa bất kỳ tool "weather" nào nếu có
    plan_struct["required_tools"] = [t for t in plan_struct["required_tools"] if t.get("tool_name") == "search"]

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

    # Bắt buộc dùng gemini-2.5-flash
    model_names = ['models/gemini-2.5-flash']

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
    # Trả về kế hoạch dự phòng: tạo search + weather queries nếu có thể
    fallback = _normalize_plan({}, text_input)
    return fallback
