# app/agent_synthesizer.py

import os
import json
import google.generativeai as genai
import re
import asyncio
from dotenv import load_dotenv
from typing import Dict, Any, List

from app.weather import classify_claim


load_dotenv()


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SYNTHESIS_PROMPT = ""


# Cài đặt an toàn
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


WEATHER_SOURCE_KEYWORDS = [
    "weather",
    "forecast",
    "accuweather",
    "windy",
    "meteoblue",
    "ventusky",
    "nchmf",
    "thoitiet",
    "openweathermap",
    "wunderground",
    "metoffice",
    "bom.gov",
]


def _is_weather_source(item: Dict[str, Any]) -> bool:
    source = (item.get("source") or item.get("url") or "").lower()
    if not source:
        return False
    return any(keyword in source for keyword in WEATHER_SOURCE_KEYWORDS)


def load_synthesis_prompt(prompt_path="synthesis_prompt.txt"):
    """Tải prompt cho Agent 2 (Synthesizer)"""
    global SYNTHESIS_PROMPT
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            SYNTHESIS_PROMPT = f.read()
        print("INFO: Tải Synthesis Prompt thành công.")
    except Exception as e:
        print(f"LỖI: không thể tải {prompt_path}: {e}")
        raise



def _parse_json_from_text(text: str) -> dict:
    """Trích xuất JSON an toàn từ text trả về của LLM"""
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text or "", re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            print(f"LỖI: Agent 2 (Synthesizer) trả về JSON không hợp lệ. Text: {text[:300]}...")
            return {}
    print("LỖI: Agent 2 (Synthesizer) không tìm thấy JSON.")
    return {}



def _trim_snippet(s: str, max_len: int = 280) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").strip()
    return s[:max_len]



def _trim_evidence_bundle(bundle: Dict[str, Any], cap_l2: int = 5, cap_l3: int = 5, cap_l4: int = 2) -> Dict[str, Any]:
    """Cắt gọn gói bằng chứng để giảm kích thước prompt gửi sang LLM"""
    if not bundle:
        return {"layer_1_tools": [], "layer_2_high_trust": [], "layer_3_general": [], "layer_4_social_low": []}
    out = {
        "layer_1_tools": [], # OpenWeather API data
        "layer_2_high_trust": [],
        "layer_3_general": [],
        "layer_4_social_low": []
    }
    
    # Lớp 1: OpenWeather API data (quan trọng cho tin thời tiết)
    for it in (bundle.get("layer_1_tools") or []):
        out["layer_1_tools"].append({
            "source": it.get("source"),
            "url": it.get("url"),
            "snippet": _trim_snippet(it.get("snippet")),
            "rank_score": it.get("rank_score"),
            "date": it.get("date"),
            "weather_data": it.get("weather_data")  # Giữ nguyên dữ liệu gốc từ OpenWeather
        })
    
    # Lớp 2
    for it in (bundle.get("layer_2_high_trust") or [])[:cap_l2]:
        out["layer_2_high_trust"].append({
            "source": it.get("source"),
            "url": it.get("url"),
            "snippet": _trim_snippet(it.get("snippet")),
            "rank_score": it.get("rank_score"),
            "date": it.get("date")
        })
    # Lớp 3
    for it in (bundle.get("layer_3_general") or [])[:cap_l3]:
        out["layer_3_general"].append({
            "source": it.get("source"),
            "url": it.get("url"),
            "snippet": _trim_snippet(it.get("snippet")),
            "rank_score": it.get("rank_score"),
            "date": it.get("date")
        })
    # Lớp 4
    for it in (bundle.get("layer_4_social_low") or [])[:cap_l4]:
        out["layer_4_social_low"].append({
            "source": it.get("source"),
            "url": it.get("url"),
            "snippet": _trim_snippet(it.get("snippet")),
            "rank_score": it.get("rank_score"),
            "date": it.get("date")
        })
    return out



def _as_str(x: Any) -> str:
    try:
        return x if isinstance(x, str) else ("" if x is None else str(x))
    except Exception:
        return ""



def _heuristic_summarize(text_input: str, bundle: Dict[str, Any], current_date: str) -> Dict[str, Any]:
    """
    (ĐÃ SỬA ĐỔI)
    Logic dự phòng khi LLM thất bại, sử dụng Lớp 1 (OpenWeather API) cho tin thời tiết.
    """
    l1 = bundle.get("layer_1_tools") or []
    l2 = bundle.get("layer_2_high_trust") or []

    try:
        claim = classify_claim(text_input)
    except Exception:
        claim = {"is_weather": False}

    is_weather_claim = claim.get("is_weather", False)

    # Ưu tiên Lớp 1 (OpenWeather API) cho tin thời tiết
    if is_weather_claim and l1:
        weather_item = l1[0]
        weather_data = weather_item.get("weather_data", {})
        if weather_data:
            # So sánh điều kiện thời tiết
            main_condition = weather_data.get("main", "").lower()
            description = weather_data.get("description", "").lower()
            text_lower = text_input.lower()
            
            # Kiểm tra mưa
            if "mưa" in text_lower or "rain" in text_lower:
                if "rain" in main_condition or "rain" in description:
                    # Kiểm tra mức độ mưa
                    if "mưa to" in text_lower or "mưa lớn" in text_lower or "heavy rain" in text_lower:
                        if "heavy" in description or "torrential" in description:
                            return {
                                "conclusion": "TIN THẬT",
                                "reason": _as_str(f"Heuristic: OpenWeather API xác nhận {weather_item.get('source')} - {description} ({weather_data.get('temperature')}°C) cho {weather_data.get('location')} ngày {weather_data.get('date')}."),
                                "style_analysis": "",
                                "key_evidence_snippet": _as_str(weather_item.get("snippet")),
                                "key_evidence_source": _as_str(weather_item.get("source")),
                                "cached": False
                            }
                    else:
                        # Mưa thường
                        return {
                            "conclusion": "TIN THẬT",
                            "reason": _as_str(f"Heuristic: OpenWeather API xác nhận {weather_item.get('source')} - {description} ({weather_data.get('temperature')}°C) cho {weather_data.get('location')} ngày {weather_data.get('date')}."),
                            "style_analysis": "",
                            "key_evidence_snippet": _as_str(weather_item.get("snippet")),
                            "key_evidence_source": _as_str(weather_item.get("source")),
                            "cached": False
                        }
            # Kiểm tra nắng
            elif "nắng" in text_lower or "sunny" in text_lower or "clear" in text_lower:
                if "clear" in main_condition or "sunny" in description:
                    return {
                        "conclusion": "TIN THẬT",
                        "reason": _as_str(f"Heuristic: OpenWeather API xác nhận {weather_item.get('source')} - {description} ({weather_data.get('temperature')}°C) cho {weather_data.get('location')} ngày {weather_data.get('date')}."),
                        "style_analysis": "",
                        "key_evidence_snippet": _as_str(weather_item.get("snippet")),
                        "key_evidence_source": _as_str(weather_item.get("source")),
                        "cached": False
                    }
            # Nếu không khớp điều kiện cụ thể, vẫn trả về dữ liệu từ OpenWeather
            return {
                "conclusion": "TIN THẬT",
                "reason": _as_str(f"Heuristic: OpenWeather API cung cấp dữ liệu thời tiết {weather_item.get('source')} - {description} ({weather_data.get('temperature')}°C) cho {weather_data.get('location')} ngày {weather_data.get('date')}."),
                "style_analysis": "",
                "key_evidence_snippet": _as_str(weather_item.get("snippet")),
                "key_evidence_source": _as_str(weather_item.get("source")),
                "cached": False
            }

    # Yêu cầu chặt chẽ: cần >=2 nguồn Lớp 2 đồng thuận để kết luận TIN THẬT
    if len(l2) >= 2:
        top = l2[0]
        return {
            "conclusion": "TIN THẬT",
            "reason": _as_str(f"Heuristic: Có từ 2 nguồn LỚP 2 uy tín gần đây, ví dụ {top.get('source')} ({top.get('date')})."),
            "style_analysis": "",
            "key_evidence_snippet": _as_str(top.get("snippet")),
            "key_evidence_source": _as_str(top.get("source")),
            "cached": False
        }

    if is_weather_claim and l2:
        weather_sources = [item for item in l2 if _is_weather_source(item)]
        if weather_sources:
            top = weather_sources[0]
            return {
                "conclusion": "TIN THẬT",
                "reason": _as_str(f"Heuristic (weather): Dựa trên nguồn dự báo thời tiết {top.get('source')} ({top.get('date') or 'N/A'})."),
                "style_analysis": "",
                "key_evidence_snippet": _as_str(top.get("snippet")),
                "key_evidence_source": _as_str(top.get("source")),
                "cached": False
            }

    if is_weather_claim:
        layer3 = bundle.get("layer_3_general") or []
        weather_layer3 = [item for item in layer3 if _is_weather_source(item)]
        if weather_layer3:
            top = weather_layer3[0]
            return {
                "conclusion": "TIN THẬT",
                "reason": _as_str(f"Heuristic (weather): Dựa trên trang dự báo {top.get('source')} cho địa điểm được nêu."),
                "style_analysis": "",
                "key_evidence_snippet": _as_str(top.get("snippet")),
                "key_evidence_source": _as_str(top.get("source")),
                "cached": False
            }

    # Không đủ điều kiện → CHƯA XÁC THỰC
    return {
        "conclusion": "TIN CHƯA XÁC THỰC",
        "reason": _as_str("Heuristic fallback: Không tìm thấy đủ nguồn LỚP 2 hoặc LỚP 3 (Search-Only)."),
        "style_analysis": "",
        "key_evidence_snippet": "",
        "key_evidence_source": "",
        "cached": False
    }



def _pick_models(flash_mode: bool) -> List[str]:
    """Chọn danh sách model cho Synthesizer dựa trên chế độ flash"""
    if flash_mode:
        return ['models/gemini-2.5-flash']  # Flash mode: dùng gemini-2.5-flash
    return ['models/gemini-2.5-pro']  # Normal mode: dùng gemini-2.5-pro


async def execute_final_analysis(text_input: str, evidence_bundle: dict, current_date: str, flash_mode: bool = False) -> dict:
    """
    Gọi Agent 2 để tổng hợp bằng chứng; cắt gọn evidence; dynamic model picking; retry nhẹ; heuristic fallback.
    """
    if not SYNTHESIS_PROMPT:
        raise ValueError("Synthesis prompt (prompt 2) chưa được tải.")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY chưa được cấu hình.")

    genai.configure(api_key=GEMINI_API_KEY)

    model_names = _pick_models(flash_mode)

    # Trim evidence before sending
    trimmed_bundle = _trim_evidence_bundle(evidence_bundle)
    evidence_bundle_json = json.dumps(trimmed_bundle, indent=2, ensure_ascii=False)

    # Prompt
    prompt = SYNTHESIS_PROMPT
    prompt = prompt.replace("{evidence_bundle_json}", evidence_bundle_json)
    prompt = prompt.replace("{text_input}", text_input)
    prompt = prompt.replace("{current_date}", current_date)

    last_err = None
    # Try each model once với timeout (nếu không unlimit)
    for model_name in model_names:
        try:
            print(f"Synthesizer: thử model '{model_name}'")
            model = genai.GenerativeModel(model_name)
            if flash_mode:
                response = await asyncio.to_thread(model.generate_content, prompt, safety_settings=SAFETY_SETTINGS)
            else:
                response = await asyncio.wait_for(
                    asyncio.to_thread(model.generate_content, prompt, safety_settings=SAFETY_SETTINGS),
                    timeout=45.0
                )
            text = getattr(response, 'text', None)
            if text is None and hasattr(response, 'candidates') and response.candidates:
                text = str(response.candidates[0].content)
            result_json = _parse_json_from_text(text or "")
            if result_json:
                result_json["cached"] = False
                return result_json
        except asyncio.TimeoutError:
            print(f"Synthesizer: Timeout khi gọi model '{model_name}'")
            last_err = "Timeout"
            continue
        except Exception as e:
            last_err = e
            # 429/quota → fallback ngay
            msg = str(e)
            if '429' in msg or 'quota' in msg.lower():
                break
            print(f"Synthesizer: Lỗi với model '{model_name}': {e}")
            continue

    print(f"Lỗi khi gọi Agent 2 (Synthesizer): {last_err}")
    # (SỬA ĐỔI) Gọi hàm fallback đã được cập nhật
    return _heuristic_summarize(text_input, trimmed_bundle, current_date)
