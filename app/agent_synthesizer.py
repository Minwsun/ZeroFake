# app/agent_synthesizer.py
import os
import json
import google.generativeai as genai
import re
import asyncio
from dotenv import load_dotenv
from typing import Dict, Any, List

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_SYNTH_MODEL = os.getenv("GEMINI_SYNTH_MODEL", "").strip()
SYNTHESIS_PROMPT = ""

# Cài đặt an toàn
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


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
        "layer_1_tools": [],
        "layer_2_high_trust": [],
        "layer_3_general": [],
        "layer_4_social_low": []
    }
    # Lớp 1: giữ nguyên status/data ngắn gọn
    for it in (bundle.get("layer_1_tools") or [])[:3]:
        if not isinstance(it, dict):
            continue
        short = dict(it)
        data = short.get("data") or {}
        if isinstance(data, dict) and isinstance(data.get("description"), str):
            data["description"] = _trim_snippet(data.get("description"))
            short["data"] = data
        out["layer_1_tools"].append(short)
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
    l2 = bundle.get("layer_2_high_trust") or []
    l1 = bundle.get("layer_1_tools") or []

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

    # Cho phép dùng weather cho claim thời tiết khi L1 thành công
    for it in l1:
        if it.get("tool_name") == "weather" and it.get("status") == "success":
            data = it.get("data") or {}
            src = data.get("city") or "openweather"
            desc = data.get("description") or ""
            return {
                "conclusion": "TIN THẬT",
                "reason": _as_str("Heuristic: Dữ liệu thời tiết (LỚP 1) khớp thời điểm/địa điểm đã nêu."),
                "style_analysis": "",
                "key_evidence_snippet": _as_str(desc),
                "key_evidence_source": _as_str(src),
                "cached": False
            }

    # Không đủ điều kiện → CHƯA XÁC THỰC
    return {
        "conclusion": "TIN CHƯA XÁC THỰC",
        "reason": _as_str("Heuristic fallback: Không có đủ nguồn LỚP 2/3 và không có tool thời tiết thành công."),
        "style_analysis": "",
        "key_evidence_snippet": "",
        "key_evidence_source": "",
        "cached": False
    }


def _pick_models() -> List[str]:
    """Bắt buộc dùng gemini-2.5-pro"""
    return ['models/gemini-2.5-pro']


async def execute_final_analysis(text_input: str, evidence_bundle: dict, current_date: str) -> dict:
    """
    Gọi Agent 2 để tổng hợp bằng chứng; cắt gọn evidence; dynamic model picking; retry nhẹ; heuristic fallback.
    """
    if not SYNTHESIS_PROMPT:
        raise ValueError("Synthesis prompt (prompt 2) chưa được tải.")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY chưa được cấu hình.")

    genai.configure(api_key=GEMINI_API_KEY)

    model_names = _pick_models()

    # Trim evidence before sending
    trimmed_bundle = _trim_evidence_bundle(evidence_bundle)
    evidence_bundle_json = json.dumps(trimmed_bundle, indent=2, ensure_ascii=False)

    # Prompt
    prompt = SYNTHESIS_PROMPT
    prompt = prompt.replace("{evidence_bundle_json}", evidence_bundle_json)
    prompt = prompt.replace("{text_input}", text_input)
    prompt = prompt.replace("{current_date}", current_date)

    last_err = None
    # Try each model once
    for model_name in model_names:
        try:
            print(f"Synthesizer: thử model '{model_name}'")
            model = genai.GenerativeModel(model_name)
            response = await asyncio.to_thread(model.generate_content, prompt, safety_settings=SAFETY_SETTINGS)
            text = getattr(response, 'text', None)
            if text is None and hasattr(response, 'candidates') and response.candidates:
                text = str(response.candidates[0].content)
            result_json = _parse_json_from_text(text or "")
            if result_json:
                result_json["cached"] = False
                return result_json
        except Exception as e:
            last_err = e
            # 429/quota → fallback ngay
            msg = str(e)
            if '429' in msg or 'quota' in msg.lower():
                break
            continue

    print(f"Lỗi khi gọi Agent 2 (Synthesizer): {last_err}")
    return _heuristic_summarize(text_input, trimmed_bundle, current_date)
