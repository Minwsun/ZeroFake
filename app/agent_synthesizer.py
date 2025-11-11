# app/agent_synthesizer.py
import os
import json
import google.generativeai as genai
import re
import asyncio
from dotenv import load_dotenv

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
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            print(f"LỖI: Agent 2 (Synthesizer) trả về JSON không hợp lệ. Text: {text}")
            return {}
    print(f"LỖI: Agent 2 (Synthesizer) không tìm thấy JSON. Text: {text}")
    return {}


async def execute_final_analysis(text_input: str, evidence_bundle: dict, current_date: str) -> dict:
    """
    Gọi Agent 2 (Gemini Pro) để tổng hợp bằng chứng 4 Lớp và đưa ra phán quyết.
    """
    if not SYNTHESIS_PROMPT:
        raise ValueError("Synthesis prompt (prompt 2) chưa được tải.")
        
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY chưa được cấu hình.")
        
    genai.configure(api_key=GEMINI_API_KEY)
    
    # Sử dụng model Pro cho chất lượng suy luận cao
    model = genai.GenerativeModel('gemini-1.5-pro')
    
    # Chuyển gói bằng chứng thành JSON string để đưa vào prompt
    evidence_bundle_json = json.dumps(evidence_bundle, indent=2, ensure_ascii=False)
    
    # Tránh KeyError do dấu ngoặc nhọn trong prompt
    prompt = SYNTHESIS_PROMPT
    prompt = prompt.replace("{evidence_bundle_json}", evidence_bundle_json)
    prompt = prompt.replace("{text_input}", text_input)
    prompt = prompt.replace("{current_date}", current_date)
    
    # Thử nhiều tên model để tương thích các phiên bản API
    model_names = [
        'models/gemini-2.5-pro',
        'gemini-1.5-pro-002',
        'models/gemini-1.5-pro-002',
        'gemini-1.5-pro-latest',
        'models/gemini-1.5-pro-latest',
        'gemini-1.5-pro',
        'models/gemini-1.5-pro'
    ]

    # Ưu tiên model có sẵn từ list_models và hỗ trợ generateContent
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
            pro_fallback = [m.name for m in available if 'generateContent' in (getattr(m, 'supported_generation_methods', []) or []) and 'pro' in m.name]
            if pro_fallback:
                model_names = pro_fallback
    except Exception:
        pass

    last_err = None
    for model_name in model_names:
        try:
            print(f"Synthesizer: thử model '{model_name}'")
            model = genai.GenerativeModel(model_name)
            # Dùng sync API để tăng tương thích phiên bản
            response = await asyncio.to_thread(model.generate_content, prompt, safety_settings=SAFETY_SETTINGS)
            text = getattr(response, 'text', None)
            if text is None and hasattr(response, 'candidates') and response.candidates:
                parts = getattr(response.candidates[0], 'content', None)
                text = str(parts)
            result_json = _parse_json_from_text(text or "")
            if result_json:
                result_json["cached"] = False
                return result_json
        except Exception as e:
            last_err = e
            continue

    print(f"Lỗi khi gọi Agent 2 (Synthesizer): {last_err}")
    # Fallback mềm: không raise để tránh 500, trả về nhãn an toàn
    return {
        "conclusion": "TIN CHƯA XÁC THỰC",
        "reason": "Không gọi được LLM để tổng hợp; chỉ có bằng chứng tìm kiếm, cần người xem xét thêm.",
        "style_analysis": "",
        "key_evidence_snippet": "",
        "key_evidence_source": "",
        "cached": False
    }

