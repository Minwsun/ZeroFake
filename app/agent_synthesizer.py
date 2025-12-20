# app/agent_synthesizer.py

import os
import json
import re
from dotenv import load_dotenv
from typing import Dict, Any, List

from app.weather import classify_claim
from app.model_clients import (
    call_gemini_model,
    call_agent_with_capability_fallback,
    ModelClientError,
    RateLimitError,
)
from app.tool_executor import execute_tool_plan  # Import for Re-Search

load_dotenv()


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SYNTHESIS_PROMPT = ""
CRITIC_PROMPT = ""  # NEW: Prompt cho CRITIC agent


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


# ==============================================================================
# SYNTH LOGIC: Phân loại claim để quyết định quyền tự quyết của Agent
# ==============================================================================

def _classify_claim_type(text_input: str) -> str:
    """
    SYNTH: Phân loại claim thành 2 loại:
    
    - "KNOWLEDGE": Kiến thức (địa lý, khoa học, định nghĩa)
      → Agent có quyền TỰ QUYẾT dựa trên kiến thức nội tại
      → KHÔNG bắt buộc phải có evidence
      
    - "NEWS": Tin tức (sự kiện, tuyên bố, thông tin thời sự)
      → BẮT BUỘC phải có evidence để kết luận
      → Không có evidence = không thể kết luận chắc chắn
    """
    text_lower = text_input.lower()
    
    # KNOWLEDGE patterns - Agent có thể tự quyết
    knowledge_patterns = [
        # Địa lý cố định
        r"(thủ đô|thủ phủ|thành phố lớn nhất|diện tích|biên giới|giáp với)",
        r"(châu lục|biển|đại dương|sông|núi|hồ|sa mạc|rừng)",
        r"(quốc gia|nước|tỉnh|vùng miền)",
        # Dân số/Dân tộc
        r"(dân số|dân tộc|ngôn ngữ chính thức)",
        # Khoa học/Kỹ thuật cố định
        r"(công thức|định luật|nguyên lý|nguyên tố|phân tử)",
        r"(phát minh ra|phát hiện ra|được thành lập năm)",
        # Định nghĩa
        r"(là gì\??|nghĩa là|định nghĩa|thuộc về)",
        # Sự thật lịch sử cố định
        r"(năm \d{4}|vào năm \d{4}|từ năm \d{4})",
        # Thông tin kỹ thuật cố định
        r"(được phát triển bởi|do .+ phát triển|thuộc sở hữu của)",
    ]
    
    for pattern in knowledge_patterns:
        if re.search(pattern, text_lower):
            return "KNOWLEDGE"
    
    # NEWS patterns - BẮT BUỘC phải có evidence
    news_patterns = [
        # Thời điểm gần
        r"(sáng nay|hôm nay|tối qua|mới đây|vừa mới|gần đây|mới nhất)",
        r"(đang diễn ra|ngay lúc này|hiện tại)",
        # Tuyên bố
        r"(tuyên bố|công bố|phát biểu|cho biết|thông báo|khẳng định)",
        r"(theo nguồn tin|theo báo cáo)",
        # Sự kiện
        r"(xảy ra|diễn ra|dự kiến)",
        # Tin tức indicators
        r"(\[nóng\]|\[breaking\]|\[cập nhật\])",
    ]
    
    for pattern in news_patterns:
        if re.search(pattern, text_lower):
            return "NEWS"
    
    # Default: NEWS (cần evidence để an toàn)
    return "NEWS"


def normalize_conclusion(conclusion: str) -> str:
    """
    Normalize conclusion to BINARY classification: TIN THẬT or TIN GIẢ only.
    
    🟢 NGUYÊN TẮC MỚI: PRESUMPTION OF TRUTH
    - Mặc định là TIN THẬT nếu không có dấu hiệu TIN GIẢ rõ ràng
    - Chỉ trả về TIN GIẢ khi có keywords chỉ định rõ ràng
    """
    if not conclusion:
        return "TIN THẬT"  # ĐỔI: Mặc định TIN THẬT nếu không có kết luận
    
    conclusion_upper = conclusion.upper().strip()
    
    # 🔴 CHỈ TIN GIẢ KHI CÓ DẤU HIỆU RÕ RÀNG
    fake_indicators = [
        # Vietnamese fake indicators
        "TIN GIẢ", "TIN GIA", "GIẢ MẠO", "FAKE", "FALSE",
        "BỊA ĐẶT", "BIA DAT", "LỪA ĐẢO", "LUA DAO", "SCAM",
        "ZOMBIE", "OUTDATED", "LỖI THỜI", "LOI THOI",
        "KHÔNG ĐÚNG", "KHONG DUNG", "SAI SỰ THẬT", "SAI SU THAT",
        "KHÔNG CÓ CƠ SỞ", "KHONG CO CO SO", "VÔ CĂN CỨ", "VO CAN CU",
        "ALMOST CERTAINLY FALSE", "HIGHLY UNLIKELY",
        "BÁC BỎ", "BAC BO", "KHÔNG XÁC NHẬN", "KHONG XAC NHAN",
        # Y tế sai
        "Y TẾ SAI", "Y TE SAI", "MISLEADING",
        # Số liệu phi thực tế
        "PHI THỰC TẾ", "PHI THUC TE", "UNREALISTIC",
        # GÂY HIỂU LẦM - vẫn coi là TIN GIẢ
        "GÂY HIỂU LẦM", "GAY HIEU LAM",
    ]
    
    # Nếu có bất kỳ indicator TIN GIẢ nào -> TIN GIẢ
    for indicator in fake_indicators:
        if indicator in conclusion_upper:
            return "TIN GIẢ"
    
    # 🟢 TẤT CẢ CÁC TRƯỜNG HỢP KHÁC -> TIN THẬT
    # Bao gồm: TIN THẬT, CHƯA KIỂM CHỨNG, TRUE, PROBABLE, LIKELY, etc.
    return "TIN THẬT"


# Product version database for outdated information detection
# Format: product_pattern -> (latest_version, release_year)
PRODUCT_VERSIONS = {
    # Apple iPhone (as of Dec 2025)
    r"iphone\s*(\d+)": {"latest": 17, "year": 2025, "name": "iPhone"},
    # Samsung Galaxy S
    r"galaxy\s*s\s*(\d+)": {"latest": 25, "year": 2025, "name": "Galaxy S"},
    # Samsung Galaxy Note
    r"galaxy\s*note\s*(\d+)": {"latest": 20, "year": 2020, "name": "Galaxy Note"},
    # Google Pixel
    r"pixel\s*(\d+)": {"latest": 9, "year": 2024, "name": "Pixel"},
    # PlayStation
    r"playstation\s*(\d+)|ps\s*(\d+)": {"latest": 5, "year": 2020, "name": "PlayStation"},
    # Xbox (Xbox One=1, Series X=2)
    r"xbox\s*series\s*([xs])": {"latest": "x", "year": 2020, "name": "Xbox Series"},
    # Windows
    r"windows\s*(\d+)": {"latest": 11, "year": 2021, "name": "Windows"},
    # macOS versions
    r"macos\s*(\d+)|mac\s*os\s*(\d+)": {"latest": 15, "year": 2024, "name": "macOS"},
    # MacBook chips
    r"macbook.*m(\d+)": {"latest": 4, "year": 2024, "name": "MacBook M-chip"},
}


def _detect_outdated_product(text_input: str) -> dict | None:
    """
    Detect if the input mentions an outdated product version.
    Returns dict with product info if outdated, None otherwise.
    """
    text_lower = text_input.lower()
    
    for pattern, info in PRODUCT_VERSIONS.items():
        match = re.search(pattern, text_lower)
        if match:
            # Get the version number from match groups
            version_str = None
            for group in match.groups():
                if group:
                    version_str = group
                    break
            
            if version_str:
                try:
                    # Handle numeric versions
                    if version_str.isdigit():
                        mentioned_version = int(version_str)
                        latest_version = info["latest"]
                        
                        if isinstance(latest_version, int) and mentioned_version < latest_version:
                            return {
                                "product": info["name"],
                                "mentioned_version": mentioned_version,
                                "latest_version": latest_version,
                                "latest_year": info["year"],
                                "is_outdated": True,
                                "years_behind": latest_version - mentioned_version
                            }
                except (ValueError, TypeError):
                    pass
    
    return None


def _is_common_knowledge(text_input: str) -> bool:
    """
    Detect if the claim is about well-known, easily verifiable facts.
    These are facts that are widely accepted and don't need extensive verification.
    """
    text_lower = text_input.lower()
    
    # Well-known tech facts
    common_knowledge_patterns = [
        # Company ownership/development
        ("chatgpt", "openai"),
        ("gpt-4", "openai"),
        ("gpt-3", "openai"),
        ("google", "alphabet"),
        ("youtube", "google"),
        ("instagram", "meta"),
        ("whatsapp", "meta"),
        ("facebook", "meta"),
        ("iphone", "apple"),
        ("android", "google"),
        ("windows", "microsoft"),
        ("azure", "microsoft"),
        ("aws", "amazon"),
        
        # Historical events that are well-documented
        ("facebook", "meta", "2021"),
        ("messi", "world cup", "2022"),
        ("argentina", "world cup", "2022"),
    ]
    
    for pattern in common_knowledge_patterns:
        if all(keyword in text_lower for keyword in pattern):
            return True
    
    return False


def _is_weather_source(item: Dict[str, Any]) -> bool:
    source = (item.get("source") or item.get("url") or "").lower()
    if not source:
        return False
    return any(keyword in source for keyword in WEATHER_SOURCE_KEYWORDS)


def load_synthesis_prompt(prompt_path="prompts/synthesis_prompt.txt"):
    """Tải prompt cho Agent 2 (Synthesizer)"""
    global SYNTHESIS_PROMPT
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            SYNTHESIS_PROMPT = f.read()
        print("INFO: Tải Synthesis Prompt thành công.")
    except Exception as e:
        print(f"LỖI: không thể tải {prompt_path}: {e}")
        raise


def load_critic_prompt(prompt_path="prompts/critic_prompt.txt"):
    """Tải prompt cho CRITIC agent (Devil's Advocate)"""
    global CRITIC_PROMPT
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            CRITIC_PROMPT = f.read()
        print("INFO: Tải CRITIC Prompt thành công.")
    except FileNotFoundError:
        # Fallback to default prompt if file not found
        CRITIC_PROMPT = (
            "Bạn là Biện lý đối lập (Devil's Advocate). "
            "Hãy chỉ ra 3 điểm yếu, mâu thuẫn hoặc khả năng đây là tin cũ/satire/tin đồn. "
            "Chỉ trả lời ngắn gọn, gay gắt."
        )
        print(f"WARNING: Không tìm thấy {prompt_path}, dùng prompt mặc định.")
    except Exception as e:
        print(f"LỖI: không thể tải {prompt_path}: {e}")


def _parse_json_from_text(text: str) -> dict:
    """Trích xuất JSON an toàn từ text trả về của LLM"""
    if not text:
        print("LỖI: Agent 2 (Synthesizer) không tìm thấy JSON.")
        return {}

    cleaned = text.strip()
    # Remove Markdown code fences if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = cleaned.rstrip("`").strip()

    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            print(f"LỖI: Agent 2 (Synthesizer) trả về JSON không hợp lệ. Text: {cleaned[:300]}...")
            return {}
    # Try direct JSON load if regex failed
    try:
        return json.loads(cleaned)
    except Exception:
        print(f"LỖI: Agent 2 (Synthesizer) không tìm thấy JSON. Raw response: {cleaned[:300]}...")
        return {}


def _trim_snippet(s: str, max_len: int = 200) -> str:
    """
    OPTIMIZED: Giảm max_len từ 500 xuống 200 để tiết kiệm token.
    Với 3 evidence items * 200 chars = 600 chars thay vì 10 * 500 = 5000 chars.
    Tiết kiệm ~90% token cho evidence.
    """
    if not s:
        return ""
    s = s.replace("\n", " ").strip()
    return s[:max_len]


def _trim_evidence_bundle(bundle: Dict[str, Any], cap_l2: int = 3, cap_l3: int = 3, cap_l4: int = 2) -> Dict[str, Any]:
    """
    OPTIMIZED: Giảm cap từ 10/10/5 xuống 3/3/2 để tiết kiệm token.
    Tổng: 8 evidence items thay vì 25 items.
    Mục tiêu: Giảm latency từ ~70s xuống ~25s.
    """
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
    Logic dự phòng khi LLM thất bại.
    
    NGUYÊN TẮC: PRESUMPTION OF TRUTH
    - Mặc định là TIN THẬT nếu không có bằng chứng BÁC BỎ
    - Chỉ TIN GIẢ khi: evidence BÁC BỎ trực tiếp hoặc sản phẩm lỗi thời
    """
    l1 = bundle.get("layer_1_tools") or []
    l2 = bundle.get("layer_2_high_trust") or []
    l3 = bundle.get("layer_3_general") or []

    try:
        claim = classify_claim(text_input)
    except Exception:
        claim = {"is_weather": False}

    is_weather_claim = claim.get("is_weather", False)
    text_lower = text_input.lower()
    
    # ═══════════════════════════════════════════════════════════════
    # PRIORITY 0: Sự thật hiển nhiên (Common Knowledge)
    # ═══════════════════════════════════════════════════════════════
    if _is_common_knowledge(text_input):
        debate_log = {
            "red_team_argument": "Tôi không tìm thấy bằng chứng bác bỏ sự thật khoa học/kỹ thuật này.",
            "blue_team_argument": "Đây là sự thật đã được khoa học/cộng đồng công nhận rộng rãi.",
            "judge_reasoning": "Blue Team thắng. Đây là kiến thức phổ thông đã được xác nhận."
        }
        return {
            "conclusion": "TIN THẬT",
            "confidence_score": 99,
            "reason": "Đây là sự thật khoa học/kỹ thuật đã được công nhận rộng rãi.",
            "debate_log": debate_log,
            "key_evidence_snippet": "Kiến thức phổ thông",
            "key_evidence_source": "",
            "evidence_link": "",
            "style_analysis": "",
            "cached": False
        }
    
    # ═══════════════════════════════════════════════════════════════
    # PRIORITY 2: Phát hiện sản phẩm LỖI THỜI (Outdated Product)
    # ═══════════════════════════════════════════════════════════════
    outdated_info = _detect_outdated_product(text_input)
    if outdated_info and outdated_info.get("is_outdated"):
        product = outdated_info["product"]
        mentioned = outdated_info["mentioned_version"]
        latest = outdated_info["latest_version"]
        latest_year = outdated_info["latest_year"]
        
        # Build Adversarial Dialectic debate
        debate_log = {
            "red_team_argument": _as_str(
                f"Thông tin này SAI! {product} {mentioned} là phiên bản cũ. "
                f"Hiện tại đã có {product} {latest} (ra mắt năm {latest_year}). "
                f"Việc đăng tin về {product} {mentioned} như tin mới là SAI SỰ THẬT."
            ),
            "blue_team_argument": _as_str(
                f"Đúng là {product} {mentioned} đã ra mắt thật. "
                f"Tuy nhiên, đây là thông tin lỗi thời. Tôi thừa nhận thua cuộc."
            ),
            "judge_reasoning": _as_str(
                f"Red Team thắng. {product} {mentioned} là phiên bản cũ. "
                f"Hiện tại đã có {product} {latest}. Tin lỗi thời = TIN GIẢ."
            )
        }
        
        return {
            "conclusion": "TIN GIẢ",
            "confidence_score": 95,
            "reason": _as_str(
                f"{product} {mentioned} đã lỗi thời. "
                f"Hiện tại đã có {product} {latest} (năm {latest_year}). "
                f"Tin về sản phẩm cũ = TIN GIẢ."
            ),
            "debate_log": debate_log,
            "key_evidence_snippet": _as_str(f"{product} {latest} ra mắt năm {latest_year}"),
            "key_evidence_source": "",
            "evidence_link": "",
            "style_analysis": "Thông tin lỗi thời được trình bày như tin mới",
            "cached": False
        }

    # Ưu tiên Lớp 1 (OpenWeather API) cho tin thời tiết
    if is_weather_claim and l1:
        weather_item = l1[0]
        weather_data = weather_item.get("weather_data", {})
        if weather_data:
            # So sánh điều kiện thời tiết
            main_condition = weather_data.get("main", "").lower()
            description = weather_data.get("description", "").lower()
            
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
                                "evidence_link": _as_str(weather_item.get("url") or weather_item.get("link")),
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
                            "evidence_link": _as_str(weather_item.get("url") or weather_item.get("link")),
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
                        "evidence_link": _as_str(weather_item.get("url") or weather_item.get("link")),
                        "cached": False
                    }
            # Nếu không khớp điều kiện cụ thể, vẫn trả về dữ liệu từ OpenWeather
            return {
                "conclusion": "TIN THẬT",
                "reason": _as_str(f"Heuristic: OpenWeather API cung cấp dữ liệu thời tiết {weather_item.get('source')} - {description} ({weather_data.get('temperature')}°C) cho {weather_data.get('location')} ngày {weather_data.get('date')}."),
                "style_analysis": "",
                "key_evidence_snippet": _as_str(weather_item.get("snippet")),
                "key_evidence_source": _as_str(weather_item.get("source")),
                "evidence_link": _as_str(weather_item.get("url") or weather_item.get("link")),
                "cached": False
            }

    # ═══════════════════════════════════════════════════════════════
    # PRIORITY 2: Kiểm tra nguồn L2 CÓ LIÊN QUAN đến claim
    # ═══════════════════════════════════════════════════════════════
    # Trích xuất các thực thể quan trọng từ claim để kiểm tra relevance
    person_keywords = []
    org_location_keywords = []
    
    # Tìm tên người (viết hoa, thường là từ đầu tiên)
    name_pattern = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b')
    names = name_pattern.findall(text_input)
    person_keywords.extend([n.lower() for n in names])
    
    # Tìm tên tổ chức/CLB/địa điểm
    org_patterns = [
        (r'clb\s+(\w+\s*\w*)', 'clb'),
        (r'fc\s+(\w+\s*\w*)', 'fc'),
        (r'đội\s+(\w+\s*\w*)', 'đội'),
    ]
    for pat, prefix in org_patterns:
        match = re.search(pat, text_lower)
        if match:
            org_location_keywords.append(match.group(1).strip())
    
    # Thêm các địa danh phổ biến
    location_names = ["hà nội", "ha noi", "hanoi", "sài gòn", "saigon", "ho chi minh", 
                      "việt nam", "vietnam", "barca", "barcelona", "inter miami", "real madrid"]
    for loc in location_names:
        if loc in text_lower:
            org_location_keywords.append(loc)
    
    # Kiểm tra L2 sources có liên quan THỰC SỰ không
    # Đối với claim về người + tổ chức: CẦN KHỚP CẢ HAI
    relevant_l2 = []
    has_person_org_claim = len(person_keywords) > 0 and len(org_location_keywords) > 0
    
    for item in l2:
        snippet = (item.get("snippet") or "").lower()
        title = (item.get("title") or "").lower()
        combined = snippet + " " + title
        
        if has_person_org_claim:
            # Claim có cả người + tổ chức -> cần khớp CẢ HAI
            has_person = any(kw in combined for kw in person_keywords if kw and len(kw) > 2)
            has_org = any(kw in combined for kw in org_location_keywords if kw and len(kw) > 2)
            
            if has_person and has_org:
                relevant_l2.append(item)
        else:
            # Claim đơn giản -> chỉ cần khớp 1 keyword
            is_relevant = False
            all_keywords = person_keywords + org_location_keywords
            for kw in all_keywords:
                if kw and len(kw) > 2 and kw in combined:
                    is_relevant = True
                    break
            if is_relevant:
                relevant_l2.append(item)
    
    # Giảm yêu cầu từ 2 xuống 1: Chỉ cần 1 nguồn uy tín LIÊN QUAN THỰC SỰ để hỗ trợ TIN THẬT
    if len(relevant_l2) >= 1:
        top = relevant_l2[0]
        return {
            "conclusion": "TIN THẬT",
            "debate_log": {
                "red_team_argument": "Tôi không tìm thấy bằng chứng bác bỏ.",
                "blue_team_argument": _as_str(f"Có ít nhất 1 nguồn uy tín xác nhận: {top.get('source')}."),
                "judge_reasoning": "Blue Team thắng với bằng chứng từ nguồn uy tín."
            },
            "confidence_score": 85,
            "reason": _as_str(f"Có nguồn uy tín xác nhận thông tin này ({top.get('source')})."),
            "style_analysis": "",
            "key_evidence_snippet": _as_str(top.get("snippet")),
            "key_evidence_source": _as_str(top.get("source")),
            "evidence_link": _as_str(top.get("url") or top.get("link")),
            "cached": False
        }
    
    # ĐÃ XÓA: Block đánh TIN GIẢ khi "có L2 nhưng không liên quan"
    # Đây là logic SAI: Không có evidence ≠ Tin giả
    # Theo IFCN: Presumption of Truth - chỉ TIN GIẢ khi có BẰNG CHỨNG BÁC BỎ


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
                "evidence_link": _as_str(top.get("url") or top.get("link")),
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
                "evidence_link": _as_str(top.get("url") or top.get("link")),
                "cached": False
            }

    # Phát hiện thông tin gây hiểu lầm do đã cũ (đặc biệt với sản phẩm/phiên bản)
    if not is_weather_claim:
        evidence_items = l2 + l3
        old_items = [item for item in evidence_items if item.get("is_old")]
        fresh_items = [item for item in evidence_items if item.get("is_old") is False]

        marketing_keywords = [
            "giảm giá", "khuyến mãi", "sale", "ra mắt", "mở bán", "đặt trước",
            "phiên bản", "model", "thế hệ", "đời", "nâng cấp", "lên kệ", "ưu đãi",
            "launch", "promotion"
        ]
        product_pattern = re.compile(r"(iphone|ipad|macbook|galaxy|pixel|surface|playstation|xbox|sony|samsung|apple|oppo|xiaomi|huawei|vinfast)\s?[0-9a-z]{1,4}", re.IGNORECASE)
        mentions_product_cycle = any(kw in text_lower for kw in marketing_keywords) or bool(product_pattern.search(text_input))

        if old_items and (fresh_items or mentions_product_cycle):
            reference_old = old_items[0]
            old_source = reference_old.get("source") or reference_old.get("url") or "nguồn cũ"
            old_date = reference_old.get("date") or "trước đây"
            latest_snippet = _as_str(reference_old.get("snippet"))

            if fresh_items:
                latest_item = fresh_items[0]
                latest_source = latest_item.get("source") or latest_item.get("url") or "nguồn mới"
                latest_date = latest_item.get("date") or "gần đây"
                reason = _as_str(
                    f"Thông tin về '{text_input}' dựa trên nguồn {old_source} ({old_date}) đã cũ, "
                    f"trong khi các nguồn mới như {latest_source} ({latest_date}) cho thấy bối cảnh đã thay đổi. "
                    "Việc trình bày như tin nóng dễ gây hiểu lầm."
                )
            else:
                reason = _as_str(
                    f"Thông tin về '{text_input}' chỉ được hỗ trợ bởi nguồn cũ {old_source} ({old_date}). "
                    "Sản phẩm/sự kiện này đã xuất hiện từ lâu nên việc trình bày như tin tức mới là gây hiểu lầm."
                )

            return {
                "conclusion": "TIN GIẢ",
                "reason": reason,
                "style_analysis": "Tin lỗi thời",
                "key_evidence_snippet": latest_snippet,
                "key_evidence_source": _as_str(old_source),
                "evidence_link": _as_str(reference_old.get("url") or reference_old.get("link")),
                "cached": False
            }

        if mentions_product_cycle and fresh_items and not old_items:
            latest_item = fresh_items[0]
            latest_source = latest_item.get("source") or latest_item.get("url") or "nguồn mới"
            latest_date = latest_item.get("date") or "gần đây"
            reason = _as_str(
                f"Không tìm thấy nguồn gần đây xác nhận '{text_input}', trong khi các sản phẩm mới hơn đã xuất hiện "
                f"(ví dụ {latest_source}, {latest_date}). Đây là thông tin cũ được lặp lại khiến người đọc hiểu lầm bối cảnh hiện tại."
            )
            return {
                "conclusion": "TIN GIẢ",
                "reason": reason,
                "style_analysis": "Tin lỗi thời",
                "key_evidence_snippet": _as_str(latest_item.get("snippet")),
                "key_evidence_source": _as_str(latest_source),
                "evidence_link": _as_str(latest_item.get("url") or latest_item.get("link")),
                "cached": False
            }

        claim_implies_present = any(
            kw in text_lower
            for kw in [
                "hiện nay", "bây giờ", "đang", "sắp", "vừa", "today", "now", "currently",
                "mới đây", "ngay lúc này", "trong thời gian tới"
            ]
        )
        if claim_implies_present and old_items and not fresh_items:
            old_item = old_items[0]
            older_source = old_item.get("source") or old_item.get("url") or "nguồn cũ"
            older_date = old_item.get("date") or "trước đây"
            reason = _as_str(
                f"'{text_input}' ám chỉ thông tin đang diễn ra nhưng chỉ có nguồn {older_source} ({older_date}) từ trước kia. "
                "Việc dùng lại tin cũ khiến người đọc hiểu sai về tình trạng hiện tại."
            )
            return {
                "conclusion": "TIN GIẢ",
                "reason": reason,
                "style_analysis": "Tin lỗi thời",
                "key_evidence_snippet": _as_str(old_item.get("snippet")),
                "key_evidence_source": _as_str(older_source),
                "evidence_link": _as_str(old_item.get("url") or old_item.get("link")),
                "cached": False
            }

        misleading_tokens = [
            "đã kết thúc", "đã dừng", "ngừng áp dụng", "không còn áp dụng",
            "đã hủy", "đã hoãn", "đã đóng", "đã ngưng", "no longer", "ended", "discontinued"
        ]
        for item in evidence_items:
            snippet_lower = (item.get("snippet") or "").lower()
            if any(token in snippet_lower for token in misleading_tokens):
                source = item.get("source") or item.get("url") or "nguồn cập nhật"
                reason = _as_str(
                    f"'{text_input}' bỏ qua cập nhật từ {source} cho biết sự kiện/chương trình đã kết thúc hoặc thay đổi "
                    "nên thông tin dễ gây hiểu lầm."
                )
                return {
                    "conclusion": "TIN GIẢ",
                    "reason": reason,
                    "style_analysis": "Tin đã không còn đúng",
                    "key_evidence_snippet": _as_str(item.get("snippet")),
                    "key_evidence_source": _as_str(source),
                    "evidence_link": _as_str(item.get("url") or item.get("link")),
                    "cached": False
                }

    # FIX: Mặc định TIN THẬT khi không có bằng chứng BÁC BỎ (innocent until proven guilty)
    # Trước đây mặc định TIN GIẢ gây false positive cao
    return {
        "conclusion": "TIN THẬT",
        "confidence_score": 60,
        "reason": _as_str("Không tìm thấy bằng chứng BÁC BỎ thông tin này. Dựa trên nguyên tắc 'innocent until proven guilty'."),
        "debate_log": {
            "red_team_argument": "Không tìm thấy bằng chứng phản bác rõ ràng.",
            "blue_team_argument": "Không có nguồn nào bác bỏ thông tin này.",
            "judge_reasoning": "Khi không có bằng chứng bác bỏ, tin được coi là có thể đúng."
        },
        "style_analysis": "",
        "key_evidence_snippet": "",
        "key_evidence_source": "",
        "evidence_link": "",
        "cached": False
    }


def _normalize_agent2_model(model_key: str | None) -> str:
    """Normalize Agent 2 model identifier."""
    if not model_key:
        return "models/gemini-2.5-pro"
    mapping = {
        "gemini_flash": "models/gemini-2.5-flash",
        "gemini flash": "models/gemini-2.5-flash",
        "gemini-2.5-flash": "models/gemini-2.5-flash",
        "models/gemini_flash": "models/gemini-2.5-flash",
        "gemini_pro": "models/gemini-2.5-pro",
        "gemini pro": "models/gemini-2.5-pro",
        "models/gemini-2.5-pro": "models/gemini-2.5-pro",
        "openai/gpt-oss-120b": "openai/gpt-oss-120b",
        "meta-llama/llama-3.3-70b-instruct": "meta-llama/llama-3.3-70b-instruct",
        "qwen/qwen-2.5-72b-instruct": "qwen/qwen-2.5-72b-instruct",
        "gemma-3-1b": "models/gemma-3-1b-it",
        "gemma-3-1b-it": "models/gemma-3-1b-it",
        "gemma-3-2b": "models/gemma-3-4b-it",  # 2B not available, fallback to 4B
        "gemma-3-4b": "models/gemma-3-4b-it",
        "gemma-3-4b-it": "models/gemma-3-4b-it",
        "gemma-3-12b": "models/gemma-3-12b-it",
        "gemma-3-12b-it": "models/gemma-3-12b-it",
        "gemma-3-27b": "models/gemma-3-27b-it",
        "gemma-3-27b-it": "models/gemma-3-27b-it",
        "google/gemma-3-1b": "models/gemma-3-1b-it",
        "google/gemma-3-2b": "models/gemma-3-4b-it",
        "google/gemma-3-4b": "models/gemma-3-4b-it",
        "google/gemma-3-12b": "models/gemma-3-12b-it",
        "google/gemma-3-27b": "models/gemma-3-27b-it",
        "models/gemma-3-1b": "models/gemma-3-1b-it",
        "models/gemma-3-2b": "models/gemma-3-4b-it",
        "models/gemma-3-4b": "models/gemma-3-4b-it",
        "models/gemma-3-12b": "models/gemma-3-12b-it",
        "models/gemma-3-27b": "models/gemma-3-27b-it",
        "models/gemma-3-1b-it": "models/gemma-3-1b-it",
        "models/gemma-3-4b-it": "models/gemma-3-4b-it",
        "models/gemma-3-12b-it": "models/gemma-3-12b-it",
        "models/gemma-3-27b-it": "models/gemma-3-27b-it",
        "models/gemma-3n-e2b-it": "models/gemma-3n-e2b-it",
        "models/gemma-3n-e4b-it": "models/gemma-3n-e4b-it",
    }
    return mapping.get(model_key, model_key)


def _detect_agent2_provider(model_name: str) -> str:
    """Detect provider for Agent 2 model."""
    if not model_name:
        return "gemini"
    lowered = model_name.lower()
    if "gemini" in lowered or "gemma" in lowered or model_name.startswith("models/"):
        return "gemini"
    # All Agent 2 models now use Gemini API
    return "gemini"

async def execute_final_analysis(
    text_input: str,
    evidence_bundle: dict,
    current_date: str,
    model_key: str | None = None,
    flash_mode: bool = False,
    site_query_string: str = "",  # Added for re-search
) -> dict:
    """
    Pipeline OPTIMIZED: SYNTH → CRITIC → JUDGE
    
    SYNTH Logic:
    - KNOWLEDGE claims: Agent có quyền tự quyết dựa trên kiến thức
    - NEWS claims: Bắt buộc phải có evidence
    
    Optimizations applied:
    - Reduced evidence bundle size (3/3/2 items)
    - Reduced snippet length (200 chars)
    - Reduced timeouts (30s/40s)
    - Simplified prompts
    """
    if not SYNTHESIS_PROMPT:
        raise ValueError("Synthesis prompt (prompt 2) chưa được tải.")
    if not CRITIC_PROMPT:
        print("WARNING: Critic prompt chưa được tải, dùng mặc định.")

    # =========================================================================
    # SYNTH: Phân loại claim để quyết định quyền tự quyết
    # =========================================================================
    claim_type = _classify_claim_type(text_input)
    print(f"\n[SYNTH] Claim type: {claim_type}")
    
    if claim_type == "KNOWLEDGE":
        synth_instruction = (
            "\n\n[SYNTH INSTRUCTION - KNOWLEDGE CLAIM]\n"
            "Đây là KNOWLEDGE CLAIM (kiến thức cố định: địa lý, khoa học, định nghĩa).\n"
            "→ Bạn có quyền TỰ QUYẾT dựa trên kiến thức nội tại.\n"
            "→ KHÔNG bắt buộc phải có evidence để kết luận.\n"
            "→ Nếu thông tin đúng với kiến thức của bạn → TIN THẬT.\n"
            "→ Nếu thông tin sai với kiến thức của bạn → TIN GIẢ.\n"
        )
        print(f"[SYNTH] Agent có quyền tự quyết dựa trên kiến thức")
    else:
        synth_instruction = (
            "\n\n[SYNTH INSTRUCTION - NEWS CLAIM]\n"
            "Đây là NEWS CLAIM (tin tức, sự kiện, tuyên bố).\n"
            "→ BẮT BUỘC phải có evidence để kết luận chắc chắn.\n"
            "→ Nếu KHÔNG có evidence liên quan → áp dụng PRESUMPTION OF TRUTH (TIN THẬT với confidence thấp).\n"
            "→ Nếu có evidence XÁC NHẬN → TIN THẬT với confidence cao.\n"
            "→ Nếu có evidence BÁC BỎ → TIN GIẢ.\n"
        )
        print(f"[SYNTH] Bắt buộc phải có evidence cho NEWS claim")

    # Trim evidence before sending to models
    trimmed_bundle = _trim_evidence_bundle(evidence_bundle)
    evidence_bundle_json = json.dumps(trimmed_bundle, indent=2, ensure_ascii=False)

    # =========================================================================
    # PHASE 1: CRITIC AGENT (BIỆN LÝ ĐỐI LẬP)
    # =========================================================================
    critic_report = "Không có phản biện."
    try:
        print(f"\n[CRITIC] Bắt đầu phản biện (Model: {model_key})...")
        critic_prompt_filled = CRITIC_PROMPT.replace("{text_input}", text_input)
        critic_prompt_filled = critic_prompt_filled.replace("{evidence_bundle_json}", evidence_bundle_json)
        critic_prompt_filled = critic_prompt_filled.replace("{current_date}", current_date)
        
        critic_report = await call_agent_with_capability_fallback(
            role="CRITIC",
            prompt=critic_prompt_filled,
            temperature=0.5,
            timeout=20.0  # 20s - balanced for Gemma 27B
        )
        print(f"[CRITIC] Report: {critic_report[:150]}...")
        
    except Exception as e:
        print(f"[CRITIC] Gặp lỗi: {e}")
        critic_report = "Lỗi khi chạy Critic Agent."

    # =========================================================================
    # PHASE 2: JUDGE AGENT (THẨM PHÁN) - Round 1
    # =========================================================================
    judge_result = {}
    try:
        print(f"\n[JUDGE] Bắt đầu phán quyết Round 1...")
        judge_prompt_filled = SYNTHESIS_PROMPT.replace("{text_input}", text_input)
        judge_prompt_filled = judge_prompt_filled.replace("{evidence_bundle_json}", evidence_bundle_json)
        judge_prompt_filled = judge_prompt_filled.replace("{current_date}", current_date)
        
        # Add SYNTH instruction and CRITIC report
        judge_prompt_filled += synth_instruction
        judge_prompt_filled += f"\n\n[Ý KIẾN BIỆN LÝ (CRITIC)]:\n{critic_report}"
        
        judge_text = await call_agent_with_capability_fallback(
            role="JUDGE",
            prompt=judge_prompt_filled,
            temperature=0.1,  # Strict logic
            timeout=25.0  # 25s - enough for complex reasoning
        )
        
        judge_result = _parse_json_from_text(judge_text)

        # ---------------------------------------------------------------------
        # ADAPTER: Convert New "Cognitive Architecture" JSON to Flat Schema
        # ---------------------------------------------------------------------
        verdict_meta = judge_result.get("verdict_metadata")
        if verdict_meta:
            # CONCLUSION
            judge_result["conclusion"] = verdict_meta.get("conclusion")
            judge_result["confidence_score"] = verdict_meta.get("probability_score")
            
            # REASON (Combine BLUF + Synthesis)
            exec_summary = judge_result.get("executive_summary") or {}
            dialectical = judge_result.get("dialectical_analysis") or {}
            
            bluf = exec_summary.get("bluf")
            synthesis = dialectical.get("synthesis")
            
            combined_reason = ""
            if bluf:
                combined_reason += f"{bluf}\n\n"
            if synthesis:
                combined_reason += f"ANALYSIS: {synthesis}"
            
            judge_result["reason"] = combined_reason.strip() or "No rationale provided."
            
            # DEBATE LOG
            judge_result["debate_log"] = {
                "red_team_argument": dialectical.get("antithesis", "N/A"),
                "blue_team_argument": dialectical.get("thesis", "N/A"),
                "judge_reasoning": dialectical.get("synthesis", "N/A")
            }
            
            # STYLE / WEP
            judge_result["style_analysis"] = verdict_meta.get("wep_label") or "N/A"
            
            # KEY EVIDENCE
            citations = judge_result.get("key_evidence_citations") or []
            if citations and isinstance(citations, list) and len(citations) > 0:
                first_cit = citations[0]
                judge_result["key_evidence_snippet"] = first_cit.get("quote") or "N/A"
                judge_result["key_evidence_source"] = first_cit.get("source") or "N/A"
                judge_result["evidence_link"] = first_cit.get("url") or ""
                
            print(f"[JUDGE] Round 1 (Cognitive Schema): {judge_result.get('conclusion')} ({judge_result.get('confidence_score')}%)")
        else:
            # FIX: Handle FLAT SCHEMA (fallback models may return simpler JSON)
            # Fallback models có thể trả về nhiều format khác nhau
            
            # 1. Tìm conclusion từ nhiều field có thể
            if not judge_result.get("conclusion"):
                for key in ["final_conclusion", "verdict", "result", "classification", "判定"]:
                    if judge_result.get(key):
                        judge_result["conclusion"] = judge_result[key]
                        break
            
            # 2. Tìm confidence_score từ nhiều field có thể
            if not judge_result.get("confidence_score"):
                for key in ["probability_score", "confidence", "score", "probability", "certainty", "độ_tin_cậy"]:
                    val = judge_result.get(key)
                    if val is not None:
                        try:
                            judge_result["confidence_score"] = int(val) if isinstance(val, (int, float)) else int(str(val).replace("%", ""))
                        except:
                            pass
                        break
                        
                # Nếu vẫn không có, thử tìm trong nested objects
                if not judge_result.get("confidence_score"):
                    for nested_key in ["metadata", "verdict_info", "analysis"]:
                        nested = judge_result.get(nested_key)
                        if isinstance(nested, dict):
                            for key in ["probability_score", "confidence", "score", "confidence_score"]:
                                val = nested.get(key)
                                if val is not None:
                                    try:
                                        judge_result["confidence_score"] = int(val) if isinstance(val, (int, float)) else int(str(val).replace("%", ""))
                                    except:
                                        pass
                                    break
            
            # 3. Tìm reason từ nhiều field có thể (mở rộng danh sách)
            if not judge_result.get("reason"):
                reason_keys = [
                    "reasoning", "explanation", "rationale", "analysis", 
                    "lý_do", "giải_thích", "bluf", "summary", "message",
                    "judgment", "verdict_reason", "conclusion_reason", 
                    "justification", "evidence_analysis", "finding",
                    "key_judgment", "final_analysis", "assessment"
                ]
                for key in reason_keys:
                    if judge_result.get(key):
                        judge_result["reason"] = str(judge_result[key])
                        print(f"[JUDGE] Found reason in field '{key}'")
                        break
                        
                # Nếu vẫn không có, thử tìm trong nested objects
                if not judge_result.get("reason"):
                    nested_searches = [
                        ("executive_summary", ["bluf", "summary", "key_judgment", "message"]),
                        ("analysis", ["reasoning", "explanation", "summary", "text"]),
                        ("verdict_info", ["reason", "explanation", "analysis"]),
                        ("verdict_metadata", ["reason", "explanation", "temporal_reason"]),
                        ("dialectical_analysis", ["synthesis", "thesis", "antithesis"]),
                    ]
                    for nested_key, sub_keys in nested_searches:
                        nested = judge_result.get(nested_key)
                        if isinstance(nested, dict):
                            for key in sub_keys:
                                if nested.get(key):
                                    judge_result["reason"] = str(nested[key])
                                    print(f"[JUDGE] Found reason in '{nested_key}.{key}'")
                                    break
                            if judge_result.get("reason"):
                                break
                
                # FIX: Thử lấy từ temporal_analysis TRƯỚC (fallback model thường trả về field này)
                if not judge_result.get("reason"):
                    temporal = judge_result.get("temporal_analysis")
                    if isinstance(temporal, dict):
                        # Ưu tiên currency_reason vì đây là field được định nghĩa trong schema
                        for key in ["currency_reason", "reason", "explanation", "analysis", "currency_status"]:
                            val = temporal.get(key)
                            if val and isinstance(val, str) and len(val) > 5:
                                # Combine với currency_status nếu có để tạo reason đầy đủ hơn
                                currency_status = temporal.get("currency_status", "")
                                if key == "currency_reason":
                                    judge_result["reason"] = f"[{currency_status}] {val}" if currency_status else val
                                else:
                                    judge_result["reason"] = str(val)
                                print(f"[JUDGE] Found reason in 'temporal_analysis.{key}'")
                                break
                    elif isinstance(temporal, str) and len(temporal) > 20:
                        judge_result["reason"] = temporal
                        print(f"[JUDGE] Using 'temporal_analysis' string as reason")
                
                # Nếu vẫn không có, dùng wep_label + conclusion làm reason
                if not judge_result.get("reason"):
                    wep = judge_result.get("wep_label", "")
                    conclusion = judge_result.get("conclusion", "")
                    if wep:
                        judge_result["reason"] = f"Đánh giá: {wep}. Kết luận: {conclusion}."
                        print(f"[JUDGE] Using wep_label as fallback reason")
                
                # Thử lấy bất kỳ string field nào có độ dài > 50 làm reason
                if not judge_result.get("reason"):
                    for key, val in judge_result.items():
                        if isinstance(val, str) and len(val) > 50 and key not in ["conclusion", "text_input"]:
                            judge_result["reason"] = val
                            print(f"[JUDGE] Using field '{key}' as reason")
                            break
                
                # CHỈ log DEBUG nếu sau tất cả các phương pháp vẫn không tìm được reason
                if not judge_result.get("reason"):
                    print(f"[JUDGE] DEBUG: Could not find reason after all attempts. Available keys: {list(judge_result.keys())}")
                    # Fallback cuối cùng: tạo reason từ conclusion
                    judge_result["reason"] = f"Kết luận: {judge_result.get('conclusion', 'N/A')}. Xem bằng chứng chi tiết bên dưới."
            
            # 4. Log kết quả
            if judge_result.get("conclusion"):
                conf = judge_result.get("confidence_score")
                conf_str = f"{conf}%" if conf is not None else "N/A"
                print(f"[JUDGE] Round 1 (Flat Schema): {judge_result.get('conclusion')} ({conf_str})")
            else:
                # JSON parse được nhưng không có conclusion hợp lệ
                print(f"[JUDGE] WARNING: JSON parsed but no valid conclusion found. Keys: {list(judge_result.keys())}")
                # FIX: LUÔN dùng heuristic fallback khi không có conclusion
                print(f"[JUDGE] Fallback to heuristic analyzer...")
                return _heuristic_summarize(text_input, evidence_bundle, current_date)

        # ---------------------------------------------------------------------
    except Exception as e:
        print(f"[JUDGE] Gặp lỗi Round 1: {e}")
        return _heuristic_summarize(text_input, evidence_bundle, current_date)

    # =========================================================================
    # PHASE 2.5: COUNTER-SEARCH (Tìm dẫn chứng BẢO VỆ claim trước khi kết luận TIN GIẢ)
    # =========================================================================
    # Nếu JUDGE Round 1 kết luận TIN GIẢ → Search thêm để tìm dẫn chứng ủng hộ claim
    # Đây là cơ hội "phản biện lại CRITIC" bằng bằng chứng mới
    
    conclusion_r1 = normalize_conclusion(judge_result.get("conclusion", ""))
    
    if conclusion_r1 == "TIN GIẢ":
        print(f"\n[COUNTER-SEARCH] JUDGE Round 1 kết luận TIN GIẢ → Tìm dẫn chứng BẢO VỆ claim...")
        
        try:
            from app.search import call_google_search
            
            # Search để tìm dẫn chứng XÁC NHẬN claim (phản biện CRITIC)
            counter_queries = [
                f"{text_input} xác nhận",
                f"{text_input} chứng minh đúng",
                f"{text_input} official",
            ]
            
            counter_evidence = []
            for query in counter_queries[:2]:  # Chỉ 2 queries để nhanh
                results = call_google_search(query, "")
                counter_evidence.extend(results[:5])
                if len(counter_evidence) >= 5:
                    break
            
            if counter_evidence:
                print(f"[COUNTER-SEARCH] Tìm thấy {len(counter_evidence)} dẫn chứng có thể ủng hộ claim")
                
                # Tạo evidence bundle mới với counter-evidence
                counter_bundle = {
                    "layer_1_tools": evidence_bundle.get("layer_1_tools", []),
                    "layer_2_high_trust": counter_evidence[:5],
                    "layer_3_general": evidence_bundle.get("layer_3_general", []),
                    "layer_4_social_low": []
                }
                counter_evidence_json = json.dumps(_trim_evidence_bundle(counter_bundle), indent=2, ensure_ascii=False)
                
                # JUDGE Round 1.5: Xem xét lại với dẫn chứng mới
                print(f"[JUDGE] Round 1.5: Xem xét lại với dẫn chứng mới...")
                
                counter_prompt = SYNTHESIS_PROMPT.replace("{text_input}", text_input)
                counter_prompt = counter_prompt.replace("{evidence_bundle_json}", counter_evidence_json)
                counter_prompt = counter_prompt.replace("{current_date}", current_date)
                counter_prompt += f"""

[COUNTER-SEARCH EVIDENCE]
Đã tìm thêm dẫn chứng CÓ THỂ ủng hộ claim. Hãy xem xét lại kết luận.

[NGUYÊN TẮC]
- Nếu dẫn chứng mới XÁC NHẬN claim → TIN THẬT
- Nếu dẫn chứng mới KHÔNG liên quan → Giữ nguyên TIN GIẢ
- CHỈ kết luận TIN GIẢ nếu có bằng chứng BÁC BỎ rõ ràng

[CRITIC FEEDBACK TRƯỚC ĐÓ]
{critic_report}
"""
                
                counter_text = await call_agent_with_capability_fallback(
                    role="JUDGE",
                    prompt=counter_prompt,
                    temperature=0.1,
                    timeout=25.0  # Same as JUDGE
                )
                
                counter_result = _parse_json_from_text(counter_text)
                
                # Parse kết quả
                if counter_result.get("verdict_metadata"):
                    counter_conclusion = counter_result["verdict_metadata"].get("conclusion")
                    counter_confidence = counter_result["verdict_metadata"].get("probability_score")
                else:
                    counter_conclusion = counter_result.get("conclusion")
                    counter_confidence = counter_result.get("confidence_score")
                
                counter_conclusion = normalize_conclusion(counter_conclusion or "")
                
                print(f"[JUDGE] Round 1.5: {counter_conclusion} ({counter_confidence}%)")
                
                # Nếu Counter-Search đổi ý → Cập nhật judge_result
                if counter_conclusion == "TIN THẬT":
                    print(f"[COUNTER-SEARCH] ✅ Counter-evidence đã thay đổi kết luận: TIN GIẢ → TIN THẬT")
                    judge_result["conclusion"] = "TIN THẬT"
                    judge_result["confidence_score"] = counter_confidence or 75
                    judge_result["reason"] = (judge_result.get("reason", "") + 
                        f"\n\n[COUNTER-SEARCH] Sau khi tìm thêm dẫn chứng, claim được xác nhận là TIN THẬT.")
                else:
                    print(f"[COUNTER-SEARCH] ❌ Counter-evidence không thay đổi kết luận, giữ TIN GIẢ")
            else:
                print(f"[COUNTER-SEARCH] Không tìm thấy dẫn chứng mới")
                
        except Exception as e:
            print(f"[COUNTER-SEARCH] Lỗi: {e}")

    # =========================================================================
    # PHASE 3: SELF-CORRECTION (RE-SEARCH LOOP)
    # =========================================================================
    
    # FIX: Parse confidence an toàn - default 50 (neutral) thay vì 0 để tránh trigger re-search sai
    confidence = 50  # Neutral default
    raw_confidence = judge_result.get("confidence_score")
    if raw_confidence is not None:
        try:
            confidence = int(raw_confidence)
        except (ValueError, TypeError):
            confidence = 50  # Keep neutral if parse fails
            print(f"[SELF-CORRECTION] Warning: Could not parse confidence '{raw_confidence}', using default 50")
    else:
        print(f"[SELF-CORRECTION] Warning: No confidence_score in judge result, using default 50")
    
    # FIX: needs_more_evidence phải là True EXPLICIT, không phải chỉ vì confidence thấp do parse lỗi    
    needs_more = judge_result.get("needs_more_evidence", False)
    if not isinstance(needs_more, bool):
        needs_more = str(needs_more).lower() == "true"
    
    # Kích hoạt Re-search nếu:
    # 1. Judge YÊU CẦU EXPLICIT (needs_more_evidence = True) - ưu tiên cao nhất
    # 2. Hoặc Confidence < 40 (rất thấp, không phải do parse fail)
    # 3. VÀ chưa phải là tin thời tiết (thời tiết thường check 1 lần là đủ)
    # 4. VÀ judge_result không rỗng (có kết quả thực sự)
    is_weather = "thời tiết" in judge_result.get("claim_type", "").lower()
    has_valid_result = bool(judge_result.get("conclusion"))
    
    # FIX: Chỉ trigger re-search khi THỰC SỰ cần, không phải do parse error
    should_research = (
        needs_more  # Judge yêu cầu explicit
        or (confidence < 40 and has_valid_result)  # Confidence thấp thật sự
    ) and not is_weather and has_valid_result
    
    if should_research:
        print(f"\n[SELF-CORRECTION] Kích hoạt Re-Search (Confidence: {confidence}%, Needs More: {needs_more}, Has Result: {has_valid_result})")
        
        new_queries = judge_result.get("additional_search_queries", [])
        if not new_queries:
            # Fallback nếu Judge không đưa query
            new_queries = [f"{text_input} sự thật", f"{text_input} fact check"]
            
        print(f"[SELF-CORRECTION] Queries mới: {new_queries}")
        
        if new_queries:
            # Thực hiện search bổ sung
            re_search_plan = {
                "required_tools": [{
                    "tool_name": "search",
                    "parameters": {"queries": new_queries}
                }]
            }
            
            # Execute search
            new_evidence = await execute_tool_plan(re_search_plan, site_query_string, flash_mode)
            
            # FIX: Safe initialization - đảm bảo các layer keys tồn tại trước khi merge
            for layer_key in ["layer_2_high_trust", "layer_3_general", "layer_4_social_low"]:
                if layer_key not in evidence_bundle:
                    evidence_bundle[layer_key] = []
                if not isinstance(evidence_bundle[layer_key], list):
                    evidence_bundle[layer_key] = []
            
            # Merge vào bundle cũ (now safe)
            evidence_bundle["layer_2_high_trust"].extend(new_evidence.get("layer_2_high_trust", []))
            evidence_bundle["layer_3_general"].extend(new_evidence.get("layer_3_general", []))
            evidence_bundle["layer_4_social_low"].extend(new_evidence.get("layer_4_social_low", []))
            
            # Remove duplicates based on URL
            seen_urls = set()
            for layer in ["layer_2_high_trust", "layer_3_general", "layer_4_social_low"]:
                unique_items = []
                for item in evidence_bundle[layer]:
                    url = item.get("url")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        unique_items.append(item)
                evidence_bundle[layer] = unique_items
                
            print(f"[SELF-CORRECTION] Đã merge evidence mới. Tổng L2: {len(evidence_bundle['layer_2_high_trust'])}")
            
            # Re-Generate Critic (Nhanh) - Optional, but good for completeness
            # Để tiết kiệm thời gian, có thể bỏ qua Critic R2 hoặc chạy nhanh
            # Ở đây ta update lại Critic Report với bằng chứng mới
            evidence_bundle_json_v2 = json.dumps(_trim_evidence_bundle(evidence_bundle), indent=2, ensure_ascii=False)
            
            # Re-Run Judge Round 2
            print(f"[JUDGE] Bắt đầu phán quyết Round 2 (Final)...")
            judge_prompt_filled_v2 = SYNTHESIS_PROMPT.replace("{text_input}", text_input)
            judge_prompt_filled_v2 = judge_prompt_filled_v2.replace("{evidence_bundle_json}", evidence_bundle_json_v2)
            judge_prompt_filled_v2 = judge_prompt_filled_v2.replace("{current_date}", current_date)
            judge_prompt_filled_v2 += f"\n\n[Ý KIẾN BIỆN LÝ (CRITIC - ROUND 1)]:\n{critic_report}\n(Lưu ý: Bằng chứng đã được cập nhật thêm sau vòng 1)"
            
            # FIX: Lưu kết quả Round 1 làm backup
            judge_result_r1_backup = judge_result.copy() if judge_result else {}
            
            try:
                judge_text_v2 = await call_agent_with_capability_fallback(
                    role="JUDGE",
                    prompt=judge_prompt_filled_v2,
                    temperature=0.1,
                    timeout=80.0
                )
                judge_result_r2 = _parse_json_from_text(judge_text_v2)
                
                # ---------------------------------------------------------------------
                # ADAPTER ROUND 2: Convert "Cognitive Architecture" JSON to Flat Schema
                # ---------------------------------------------------------------------
                verdict_meta = judge_result_r2.get("verdict_metadata")
                if verdict_meta:
                    # CONCLUSION
                    judge_result_r2["conclusion"] = verdict_meta.get("conclusion")
                    judge_result_r2["confidence_score"] = verdict_meta.get("probability_score")
                    
                    # REASON (Combine BLUF + Synthesis)
                    exec_summary = judge_result_r2.get("executive_summary") or {}
                    dialectical = judge_result_r2.get("dialectical_analysis") or {}
                    
                    bluf = exec_summary.get("bluf")
                    synthesis = dialectical.get("synthesis")
                    
                    combined_reason = ""
                    if bluf:
                        combined_reason += f"{bluf}\n\n"
                    if synthesis:
                        combined_reason += f"ANALYSIS: {synthesis}"
                    
                    judge_result_r2["reason"] = combined_reason.strip() or "No rationale provided."
                    
                    # DEBATE LOG
                    judge_result_r2["debate_log"] = {
                        "red_team_argument": dialectical.get("antithesis", "N/A"),
                        "blue_team_argument": dialectical.get("thesis", "N/A"),
                        "judge_reasoning": dialectical.get("synthesis", "N/A")
                    }
                    
                    # STYLE / WEP
                    judge_result_r2["style_analysis"] = verdict_meta.get("wep_label") or "N/A"
                    
                    # KEY EVIDENCE
                    citations = judge_result_r2.get("key_evidence_citations") or []
                    if citations and isinstance(citations, list) and len(citations) > 0:
                        first_cit = citations[0]
                        judge_result_r2["key_evidence_snippet"] = first_cit.get("quote") or "N/A"
                        judge_result_r2["key_evidence_source"] = first_cit.get("source") or "N/A"
                        judge_result_r2["evidence_link"] = first_cit.get("url") or ""
                        
                    print(f"[JUDGE] Round 2 (Cognitive Schema): {judge_result_r2.get('conclusion')} ({judge_result_r2.get('confidence_score')}%)")
                else:
                    # FIX: Handle FLAT SCHEMA for Round 2 (same logic as Round 1)
                    
                    # 1. Tìm conclusion từ nhiều field có thể
                    if not judge_result_r2.get("conclusion"):
                        for key in ["final_conclusion", "verdict", "result", "classification"]:
                            if judge_result_r2.get(key):
                                judge_result_r2["conclusion"] = judge_result_r2[key]
                                break
                    
                    # 2. Tìm confidence_score từ nhiều field có thể
                    if not judge_result_r2.get("confidence_score"):
                        for key in ["probability_score", "confidence", "score", "probability", "certainty"]:
                            val = judge_result_r2.get(key)
                            if val is not None:
                                try:
                                    judge_result_r2["confidence_score"] = int(val) if isinstance(val, (int, float)) else int(str(val).replace("%", ""))
                                except:
                                    pass
                                break
                    
                    # 3. Tìm reason từ nhiều field có thể
                    if not judge_result_r2.get("reason"):
                        for key in ["reasoning", "explanation", "rationale", "analysis", "summary", "bluf"]:
                            if judge_result_r2.get(key):
                                judge_result_r2["reason"] = str(judge_result_r2[key])
                                break
                    
                    # 4. Log kết quả
                    if judge_result_r2.get("conclusion"):
                        conf = judge_result_r2.get("confidence_score")
                        conf_str = f"{conf}%" if conf is not None else "N/A"
                        print(f"[JUDGE] Round 2 (Flat Schema): {judge_result_r2.get('conclusion')} ({conf_str})")
                    else:
                        print(f"[JUDGE] WARNING Round 2: No valid conclusion. Keys: {list(judge_result_r2.keys())}")
                
                # FIX: Chỉ sử dụng Round 2 nếu có kết quả hợp lệ
                if judge_result_r2.get("conclusion"):
                    judge_result = judge_result_r2
                    judge_result["cached"] = False
                    print(f"[JUDGE] Kết quả Round 2: {judge_result.get('conclusion')} ({judge_result.get('confidence_score')}%)")
                    
                    # FIX: Đảm bảo reason và evidence_link được copy từ R2
                    if not judge_result.get("reason"):
                        judge_result["reason"] = judge_result_r1_backup.get("reason", "Xem bằng chứng bên dưới.")
                    if not judge_result.get("evidence_link"):
                        judge_result["evidence_link"] = judge_result_r1_backup.get("evidence_link", "")
                else:
                    # Round 2 không có kết quả hợp lệ - giữ Round 1
                    print(f"[JUDGE] Round 2 failed to produce valid result. Keeping Round 1 result.")
                    judge_result = judge_result_r1_backup
                    
            except Exception as e:
                print(f"[JUDGE] Lỗi Round 2: {e}. Giữ nguyên kết quả Round 1.")
                judge_result = judge_result_r1_backup  # FIX: Ensure we use backup
        else:
             print("[SELF-CORRECTION] Không có query mới, bỏ qua Round 2.")

    # Post-processing normalization
    if judge_result:
        # Map old schema keys if needed (fallback)
        if "final_conclusion" in judge_result and "conclusion" not in judge_result:
            judge_result["conclusion"] = judge_result["final_conclusion"]
            
        judge_result["conclusion"] = normalize_conclusion(judge_result.get("conclusion"))
        return judge_result

    # Fallback final
    return _heuristic_summarize(text_input, evidence_bundle, current_date)

