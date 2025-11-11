# 22520876-NguyenNhatMinh
"""
Module 2c: Gemini API Call
"""
import os
import re
import json
import google.generativeai as genai
from dotenv import load_dotenv
from app.feedback import get_relevant_examples

load_dotenv()

# Biến toàn cục
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SAFETY_SETTINGS = [
    {
        "category": "HARM_CATEGORY_HARASSMENT",
        "threshold": "BLOCK_NONE",
    },
    {
        "category": "HARM_CATEGORY_HATE_SPEECH",
        "threshold": "BLOCK_NONE",
    },
    {
        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "threshold": "BLOCK_NONE",
    },
    {
        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
        "threshold": "BLOCK_NONE",
    },
]
PROMPT_TEMPLATE = ""


def load_prompt_template(prompt_path="gemini_prompt.txt"):
    """Đọc gemini_prompt.txt vào PROMPT_TEMPLATE"""
    global PROMPT_TEMPLATE
    with open(prompt_path, 'r', encoding='utf-8') as f:
        PROMPT_TEMPLATE = f.read()


def call_gemini_analysis(text_input: str, evidence_json_string: str, current_date: str, weather_api_data: str) -> dict:
    """
    Gọi Gemini API với prompt động.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY chưa được cấu hình trong .env")
    
    if not PROMPT_TEMPLATE:
        raise ValueError("PROMPT_TEMPLATE chưa được load. Gọi load_prompt_template() trước.")
    
    # Cấu hình Gemini
    genai.configure(api_key=GEMINI_API_KEY)
    
    # Logic v3.2: Lấy các ví dụ liên quan
    dynamic_examples = get_relevant_examples(text_input, limit=3)
    
    # Tạo full prompt với cơ chế escape an toàn cho dấu ngoặc nhọn trong ví dụ JSON
    def _safe_format_template(tpl: str, mapping: dict) -> str:
        # Escape tất cả ngoặc trước
        esc = tpl.replace('{', '{{').replace('}', '}}')
        # Mở lại các placeholder được phép
        for key in mapping.keys():
            esc = esc.replace('{{' + key + '}}', '{' + key + '}')
        return esc.format(**mapping)

    full_prompt = _safe_format_template(
        PROMPT_TEMPLATE,
        {
            'dynamic_few_shot_examples': dynamic_examples,
            'current_date': current_date,
            'weather_api_data': weather_api_data if weather_api_data else 'Không có',
            'text_input': text_input,
            'evidence_json_string': evidence_json_string,
        }
    )
    
    # Thử list các models available trước
    available_model_names = []
    try:
        for model in genai.list_models():
            if 'generateContent' in model.supported_generation_methods:
                # Lấy tên model (có thể là full path hoặc short name)
                model_name = model.name
                # Nếu là full path, extract short name
                if '/' in model_name:
                    short_name = model_name.split('/')[-1]
                    available_model_names.append(short_name)
                    available_model_names.append(model_name)  # Cũng thử full path
                else:
                    available_model_names.append(model_name)
    except Exception as e:
        # Nếu không list được, dùng danh sách mặc định
        pass
    
    # Danh sách model để thử (ưu tiên các model có sẵn, sau đó là danh sách mặc định)
    default_model_names = [
        'gemini-1.5-flash',
        'gemini-1.5-pro', 
        'gemini-pro',
        'models/gemini-1.5-flash',
        'models/gemini-1.5-pro',
        'models/gemini-pro'
    ]
    
    # Kết hợp: ưu tiên các model có sẵn, sau đó là default
    model_names = list(dict.fromkeys(available_model_names + default_model_names))  # dict.fromkeys để loại bỏ duplicate nhưng giữ thứ tự
    response = None
    last_error = None
    successful_model = None
    
    # Thử gọi API với từng model cho đến khi thành công
    for model_name in model_names:
        try:
            model = genai.GenerativeModel(model_name)
            # Gọi API thực sự để kiểm tra model có hoạt động không
            response = model.generate_content(
                full_prompt,
                safety_settings=SAFETY_SETTINGS
            )
            # Nếu thành công, lưu tên model và break
            successful_model = model_name
            break
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            # Nếu lỗi là 404 hoặc model not found, thử model tiếp theo
            if "404" in str(e) or "not found" in error_str or "not supported" in error_str:
                continue
            # Nếu lỗi là 429 (quota exceeded), thử model tiếp theo hoặc retry sau
            if "429" in str(e) or "quota" in error_str or "rate limit" in error_str:
                # Thử model tiếp theo trước, nếu hết model thì raise
                if model_name != model_names[-1]:  # Chưa phải model cuối cùng
                    continue
                # Nếu là model cuối cùng và vẫn bị quota, raise với thông báo rõ ràng
                raise ValueError(
                    f"Đã vượt quota Gemini API. Vui lòng kiểm tra: "
                    f"https://ai.google.dev/gemini-api/docs/rate-limits. "
                    f"Lỗi: {str(e)}"
                )
            # Nếu lỗi khác, có thể là lỗi API key hoặc network, raise ngay
            raise
    
    if response is None:
        # Thử list các models available để debug
        try:
            available_models = [m.name for m in genai.list_models()]
            available_info = f"\nCác model có sẵn: {', '.join(available_models[:5])}" if available_models else "\nKhông thể list models."
        except:
            available_info = "\nKhông thể list models available."
        
        raise ValueError(
            f"Không thể gọi Gemini API với bất kỳ model nào. "
            f"Đã thử: {model_names}. "
            f"Lỗi cuối: {str(last_error)}"
            f"{available_info}"
        )
    
    # Xử lý response
    try:
        response_text = response.text
        
        # Trích xuất JSON từ response
        # Tìm khối JSON đầu tiên
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
        
        if json_match:
            json_str = json_match.group(0)
            result = json.loads(json_str)
            result["cached"] = False
            return result
        else:
            try:
                result = json.loads(response_text)
                result["cached"] = False
                return result
            except:
                return {
                    "conclusion": "TIN CHƯA XÁC THỰC",
                    "reason": "Không thể phân tích kết quả từ Gemini API.",
                    "style_analysis": "",
                    "key_evidence_snippet": "",
                    "key_evidence_source": "",
                    "cached": False
                }
    except Exception as e:
        return {
            "conclusion": "TIN CHƯA XÁC THỰC",
            "reason": f"Lỗi khi gọi Gemini API: {str(e)}",
            "style_analysis": "",
            "key_evidence_snippet": "",
            "key_evidence_source": "",
            "cached": False
        }

