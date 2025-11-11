# app/retriever.py
import os
import json
import re
from typing import List, Dict, Optional
import google.generativeai as genai
from datetime import datetime, timedelta

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_RETRIEVER_MODEL = os.getenv("GEMINI_RETRIEVER_MODEL", "").strip()


# ---------------- Helpers -----------------

def _parse_json_array(text: str) -> List[Dict]:
    if not text:
        return []
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
        return arr if isinstance(arr, list) else []
    except Exception:
        return []


def _build_prompt(queries: List[str], allowed_domains: Optional[List[str]] = None, recent_window_days: int = 14, strict: bool = True) -> str:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    window_start = (datetime.utcnow() - timedelta(days=recent_window_days)).strftime("%Y-%m-%d")
    policy = (
        f"ƯU TIÊN bài trong {recent_window_days} ngày gần đây và nếu có nhiều kết quả thì chọn bài MỚI NHẤT (gần {today})."
        if strict else
        "Cho phép lấy kết quả rộng hơn nếu ít kết quả, nhưng vẫn ưu tiên bài mới và uy tín."
    )
    domain_clause = ""
    if allowed_domains:
        domain_clause = "\nCHỈ LẤY các kết quả thuộc các domain sau (nếu có):\n" + ", ".join(sorted(set(allowed_domains))) + "\n"
    return (
        "Bạn là tác nhân duyệt web và tổng hợp nguồn báo chí uy tín."\
        " Hãy tìm các bài viết liên quan đến các truy vấn dưới đây. " + policy + "\n" +
        domain_clause +
        "Tuyệt đối KHÔNG bịa đặt tiêu đề/URL. Chỉ báo cáo URL thực và public.\n"
        "Chỉ TRẢ VỀ DUY NHẤT một JSON array (tối đa 10 phần tử), mỗi phần tử có dạng:\n"
        "[\n  {\n    \"title\": \"...\",\n    \"url\": \"https://...\",\n    \"snippet\": \"tóm tắt ngắn <= 250 ký tự\",\n    \"date\": \"YYYY-MM-DD\"\n  }\n]\n"
        "YÊU CẦU: Chỉ trả JSON (không thêm chữ nào khác). Nếu không tìm thấy, trả []\n"
        f"Hôm nay: {today}. Ưu tiên bài có date >= {window_start}.\n"
        f"Các truy vấn:\n{json.dumps(queries, ensure_ascii=False)}\n"
        "ƯU TIÊN nguồn chính thống/uy tín và ngày gần hiện tại."
    )


_VN_EN_MAP = [
    ("dự báo thời tiết", "weather forecast"),
    ("thời tiết", "weather"),
    ("mưa", "rain"),
    ("nắng", "sunny"),
    ("ngày mai", "tomorrow"),
    ("hôm nay", "today"),
]


def _expand_queries(queries: List[str]) -> List[str]:
    out = []
    seen = set()
    for q in queries:
        if not q:
            continue
        base = q.strip()
        if base and base not in seen:
            out.append(base)
            seen.add(base)
        q_en = base
        for vn, en in _VN_EN_MAP:
            q_en = re.sub(vn, en, q_en, flags=re.IGNORECASE)
        if q_en != base and q_en not in seen:
            out.append(q_en)
            seen.add(q_en)
    return out[:12]


def _pick_model() -> str:
    # Bắt buộc dùng gemini-2.5-flash
    return 'models/gemini-2.5-flash'


# --------------- Main API -----------------

def gemini_web_search(queries: List[str], allowed_domains: Optional[List[str]] = None) -> List[Dict]:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY chưa được cấu hình")
    genai.configure(api_key=GEMINI_API_KEY)
    model_name = _pick_model()

    # 1st pass: strict + original queries
    try:
        model = genai.GenerativeModel(model_name)
        prompt = _build_prompt(queries, allowed_domains=allowed_domains, recent_window_days=14, strict=True)
        resp = model.generate_content(prompt)
        text = getattr(resp, 'text', None) or (str(resp.candidates[0].content) if getattr(resp, 'candidates', None) else "")
        arr = _parse_json_array(text)
        if arr:
            return arr
    except Exception as e:
        print(f"Gemini web search pass1 error: {e}")

    # 2nd pass: relaxed + expanded queries (VN->EN)
    try:
        exp = _expand_queries(queries)
        model = genai.GenerativeModel(model_name)
        prompt = _build_prompt(exp, allowed_domains=allowed_domains, recent_window_days=30, strict=False)
        resp = model.generate_content(prompt)
        text = getattr(resp, 'text', None) or (str(resp.candidates[0].content) if getattr(resp, 'candidates', None) else "")
        arr = _parse_json_array(text)
        if arr:
            return arr
    except Exception as e:
        print(f"Gemini web search pass2 error: {e}")

    return []
