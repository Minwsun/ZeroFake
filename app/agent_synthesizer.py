# app/agent_synthesizer.py

import os
import json
import re
from dotenv import load_dotenv
from typing import Dict, Any, List

from app.weather import classify_claim
from app.model_clients import (
    call_gemini_model,
    call_openrouter_chat_completion,
    call_agent_with_capability_fallback,
    ModelClientError,
    RateLimitError,
)


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


def normalize_conclusion(conclusion: str) -> str:
    """
    Normalize conclusion to BINARY classification: TIN THẬT or TIN GIẢ only.
    No "GÂY HIỂU LẦM" - misleading info is treated as TIN GIẢ.
    """
    if not conclusion:
        return "TIN GIẢ"
    
    conclusion_upper = conclusion.upper().strip()
    
    # TIN THẬT (with and without diacritics)
    # Only return TIN THẬT if explicitly confirmed as true/verified
    if any(x in conclusion_upper for x in [
        "TIN THẬT", "TIN THAT", 
        "TRUE", "REAL", "VERIFIED", 
        "CHINH XAC", "CHÍNH XÁC",
        "CÓ CƠ SỞ", "CO CO SO",
        "XÁC NHẬN", "XAC NHAN",
        "ĐÃ XÁC MINH", "DA XAC MINH"
    ]):
        return "TIN THẬT"
    
    # Everything else -> TIN GIẢ 
    # Including: GÂY HIỂU LẦM, CHƯA KIỂM CHỨNG, TIN ĐỒN, FALSE, FAKE, OUTDATED, etc.
    return "TIN GIẢ"


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
    (ĐÃ SỬA ĐỔI - ADVERSARIAL DIALECTIC)
    Logic dự phòng khi LLM thất bại.
    Ưu tiên:
    1. Phát hiện sản phẩm lỗi thời (iPhone 12, Galaxy S21, etc.)
    2. Lớp 1 (OpenWeather API) cho tin thời tiết
    3. Lớp 2/3 cho tin tức khác
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
    # PRIORITY 1: Phát hiện sản phẩm LỖI THỜI (Outdated Product)
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
    
    # Yêu cầu chặt chẽ: cần >=2 nguồn Lớp 2 LIÊN QUAN THỰC SỰ để kết luận TIN THẬT
    if len(relevant_l2) >= 2:
        top = relevant_l2[0]
        return {
            "conclusion": "TIN THẬT",
            "debate_log": {
                "red_team_argument": "Tôi không tìm thấy bằng chứng bác bỏ.",
                "blue_team_argument": _as_str(f"Có ít nhất 2 nguồn uy tín xác nhận: {top.get('source')}."),
                "judge_reasoning": "Blue Team thắng với bằng chứng từ nhiều nguồn uy tín."
            },
            "confidence_score": 85,
            "reason": _as_str(f"Có từ 2 nguồn uy tín xác nhận thông tin này ({top.get('source')})."),
            "style_analysis": "",
            "key_evidence_snippet": _as_str(top.get("snippet")),
            "key_evidence_source": _as_str(top.get("source")),
            "evidence_link": _as_str(top.get("url") or top.get("link")),
            "cached": False
        }
    
    # Nếu có nguồn L2 nhưng KHÔNG liên quan -> Có thể là TIN GIẢ
    all_claim_keywords = person_keywords + org_location_keywords
    if len(l2) >= 2 and len(relevant_l2) == 0 and all_claim_keywords:
        # Claim có thực thể cụ thể (tên người/tổ chức) nhưng không có bằng chứng liên quan
        debate_log = {
            "red_team_argument": _as_str(
                f"Không tìm thấy bất kỳ nguồn uy tín nào xác nhận thông tin này. "
                f"Các nguồn tìm được không liên quan đến nội dung claim."
            ),
            "blue_team_argument": _as_str(
                "Tôi không tìm thấy bằng chứng xác nhận. Tôi thừa nhận thua cuộc."
            ),
            "judge_reasoning": _as_str(
                "Red Team thắng. Không có nguồn uy tín nào xác nhận tin này. "
                "Đây có thể là tin đồn hoặc tin giả."
            )
        }
        return {
            "conclusion": "TIN GIẢ",
            "confidence_score": 80,
            "reason": _as_str(
                "Không tìm thấy nguồn uy tín nào xác nhận thông tin này. "
                "Các kết quả tìm kiếm không liên quan đến nội dung claim."
            ),
            "debate_log": debate_log,
            "key_evidence_snippet": "",
            "key_evidence_source": "",
            "evidence_link": "",
            "style_analysis": "Tin có vẻ là tin đồn không có căn cứ",
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

    # Không đủ điều kiện → TIN GIẢ (không có bằng chứng xác nhận)
    return {
        "conclusion": "TIN GIẢ",
        "reason": _as_str("Heuristic fallback: Không tìm thấy đủ nguồn LỚP 2 hoặc LỚP 3 (Search-Only) để xác nhận thông tin."),
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
) -> dict:
    """
    Pipeline: Input → Planner → Search → CRITIC → JUDGE → (RE-SEARCH nếu cần)
    
    1. CRITIC (Biện lý) - Phản biện mạnh, tìm điểm yếu trong bằng chứng
    2. JUDGE (Thẩm phán) - Ra phán quyết dựa trên bằng chứng VÀ ý kiến CRITIC
    3. RE-SEARCH - Chỉ khi JUDGE yêu cầu thêm bằng chứng (không double-check)
    
    Fallback chain: GPT-OSS-120B → Gemma-27B → Llama-3.3-70B
    """
    if not SYNTHESIS_PROMPT:
        raise ValueError("Synthesis prompt (prompt 2) chưa được tải.")

    # Trim evidence before sending
    trimmed_bundle = _trim_evidence_bundle(evidence_bundle)
    evidence_bundle_json = json.dumps(trimmed_bundle, indent=2, ensure_ascii=False)

    # ========== BƯỚC 1: CRITIC (BIỆN LÝ ĐỐI LẬP) ==========
    critic_feedback = ""
    try:
        # Sử dụng CRITIC_PROMPT từ file 
        if CRITIC_PROMPT:
            critic_prompt = CRITIC_PROMPT
            critic_prompt = critic_prompt.replace("{text_input}", text_input)
            critic_prompt = critic_prompt.replace("{current_date}", current_date)
            critic_prompt = critic_prompt.replace("{evidence_bundle_json}", evidence_bundle_json[:4000])
        else:
            # Fallback prompt mạnh mẽ
            critic_prompt = (
                f"[VAI TRÒ]: Bạn là BIỆN LÝ ĐỐI LẬP (Devil's Advocate).\n"
                f"[NHIỆM VỤ]: TÌM MỌI LỖI, PHẢN BIỆN MẠNH MẼ, CHỈ RA ĐIỂM YẾU.\n\n"
                f"TIN CẦN KIỂM TRA: {text_input}\n"
                f"NGÀY HIỆN TẠI: {current_date}\n"
                f"BẰNG CHỨNG: {evidence_bundle_json[:3000]}...\n\n"
                f"GÓC TẤN CÔNG:\n"
                f"1. Nguồn có uy tín không? (Tier 0/1/2)\n"
                f"2. Thời gian có khớp không? Tin cũ được đào lại?\n"
                f"3. Sản phẩm/thông tin đã lỗi thời?\n"
                f"4. Ngữ cảnh bị cắt xén?\n"
                f"5. Có phải satire/châm biếm?\n"
                f"6. Có xác nhận chính thức hay chỉ là tin đồn?\n\n"
                f"CHỈ RA 3 ĐIỂM YẾU LỚN NHẤT VÀ KẾT LUẬN SƠ BỘ!"
            )
        
        print("\n[CRITIC] Dang phan bien bang chung...")
        critic_feedback = await call_agent_with_capability_fallback(
            role="CRITIC",
            prompt=critic_prompt,
            temperature=0.3,
            timeout=60.0,
        )
        if critic_feedback:
            print(f"[CRITIC] Ý kiến: {critic_feedback[:200]}...")
    except Exception as e:
        print(f"[CRITIC] WARNING: Bo qua phan bien do loi: {e}")

    # ========== BƯỚC 2: JUDGE (THẨM PHÁN) ==========
    # Build prompt với ý kiến CRITIC
    base_prompt = SYNTHESIS_PROMPT
    base_prompt = base_prompt.replace("{evidence_bundle_json}", evidence_bundle_json)
    base_prompt = base_prompt.replace("{text_input}", text_input)
    base_prompt = base_prompt.replace("{current_date}", current_date)
    
    # Thêm ý kiến CRITIC vào prompt cho JUDGE
    if critic_feedback:
        base_prompt += (
            f"\n\n══════════════════════════════════════════════════════════════\n"
            f"[Ý KIẾN TỪ BIỆN LÝ ĐỐI LẬP - BẮT BUỘC THAM KHẢO]:\n"
            f"{critic_feedback[:1500]}\n"
            f"══════════════════════════════════════════════════════════════\n"
            f"Hay can nhac KY cac diem yeu tren truoc khi ket luan.\n"
            f"Nếu CRITIC đúng, hãy điều chỉnh kết luận tương ứng."
        )

    text_response = ""
    try:
        print("\n[JUDGE] Dang ra phan quyet cuoi cung...")
        text_response = await call_agent_with_capability_fallback(
            role="JUDGE",
            prompt=base_prompt,
            temperature=0.2,
            timeout=90.0,
        )
    except Exception as e:
        print(f"[JUDGE] Lỗi: {e}")
    
    result_json = _parse_json_from_text(text_response or "")
    
    # ========== RE-SEARCH (CHỈ KHI JUDGE YÊU CẦU THÊM BẰNG CHỨNG) ==========
    # Kích hoạt khi: needs_more_evidence=true HOẶC confidence < 70
    needs_research = False
    confidence = 0
    
    if result_json:
        try:
            confidence = int(str(result_json.get("confidence_score", 0)).strip('% '))
        except:
            confidence = 0
        
        if result_json.get("needs_more_evidence"):
            needs_research = True
            print(f"\n[JUDGE] Yêu cầu tìm thêm bằng chứng...")
        elif confidence < 70 and confidence > 0:
            needs_research = True
            print(f"\n[JUDGE] Độ tin cậy thấp ({confidence}%), tìm thêm bằng chứng...")
    
    if needs_research and not flash_mode:
        suggested_queries = result_json.get("suggested_queries", [])
        
        # Nếu không có suggested_queries, tạo queries mặc định
        if not suggested_queries:
            suggested_queries = [
                f"{text_input[:100]} xác minh",
                f"{text_input[:100]} tin thật hay giả",
            ]
        
        print(f"[RE-SEARCH] Tìm kiếm với {len(suggested_queries)} queries...")
        
        try:
            from app.search import call_google_search
            from app.ranker import get_rank_from_url, _extract_date
            from app.article_scraper import scrape_multiple_articles, enrich_search_results_with_full_text
            from datetime import datetime
            import asyncio
            
            additional_evidence = []
            seen_urls = set()
            
            # Lấy URLs đã có
            for layer in ["layer_2_high_trust", "layer_3_general", "layer_4_social_low"]:
                for item in evidence_bundle.get(layer, []):
                    if item.get("url") or item.get("link"):
                        seen_urls.add(item.get("url") or item.get("link"))
            
            # Search với suggested queries (giới hạn 2)
            for query in suggested_queries[:2]:
                print(f"  └── Searching: '{query}'")
                search_items = await asyncio.to_thread(call_google_search, query, "")
                
                for item in search_items or []:
                    link = item.get('link')
                    if link and link not in seen_urls:
                        seen_urls.add(link)
                        rank = get_rank_from_url(link)
                        date = _extract_date(item.get('snippet', ''), item.get('title', ''))
                        is_old = False
                        if date:
                            try:
                                date_obj = datetime.strptime(date[:10], '%Y-%m-%d')
                                days_diff = (datetime.now() - date_obj).days
                                is_old = days_diff > 365
                            except:
                                pass
                        
                        additional_evidence.append({
                            'title': item.get('title', ''),
                            'link': link,
                            'url': link,
                            'snippet': item.get('snippet', ''),
                            'source': link,
                            'rank_score': rank,
                            'date': date,
                            'is_old': is_old
                        })
            
            # Scrape top 3 URLs từ re-search
            if additional_evidence:
                top_urls = [item["link"] for item in additional_evidence[:3]]
                scraped = await scrape_multiple_articles(top_urls, max_articles=3)
                additional_evidence = enrich_search_results_with_full_text(additional_evidence, scraped)
            
            print(f"  └── Tìm thấy {len(additional_evidence)} bằng chứng mới")
            
            if additional_evidence:
                # Merge vào evidence bundle
                for item in additional_evidence:
                    rank = item.get('rank_score', 0)
                    if rank >= 0.7:
                        if 'layer_2_high_trust' not in evidence_bundle:
                            evidence_bundle['layer_2_high_trust'] = []
                        evidence_bundle['layer_2_high_trust'].append(item)
                    else:
                        if 'layer_3_general' not in evidence_bundle:
                            evidence_bundle['layer_3_general'] = []
                        evidence_bundle['layer_3_general'].append(item)
                
                # Re-call JUDGE với evidence mới
                print("\n[JUDGE] Danh gia lai voi bang chung bo sung...")
                trimmed_bundle = _trim_evidence_bundle(evidence_bundle)
                evidence_bundle_json = json.dumps(trimmed_bundle, indent=2, ensure_ascii=False)
                
                re_prompt = SYNTHESIS_PROMPT
                re_prompt = re_prompt.replace("{evidence_bundle_json}", evidence_bundle_json)
                re_prompt = re_prompt.replace("{text_input}", text_input)
                re_prompt = re_prompt.replace("{current_date}", current_date)
                
                # Thêm CRITIC feedback vào re-prompt
                if critic_feedback:
                    re_prompt += (
                        f"\n\n══════════════════════════════════════════════════════════════\n"
                        f"[Ý KIẾN TỪ BIỆN LÝ ĐỐI LẬP]:\n{critic_feedback[:1000]}\n"
                        f"══════════════════════════════════════════════════════════════"
                    )
                
                re_prompt += "\n\n[LƯU Ý]: Đây là lần đánh giá thứ 2 với bằng chứng bổ sung. Không được yêu cầu thêm bằng chứng nữa."
                
                re_response = await call_agent_with_capability_fallback(
                    role="JUDGE",
                    prompt=re_prompt,
                    temperature=0.2,
                    timeout=90.0,
                )
                
                re_result = _parse_json_from_text(re_response or "")
                if re_result:
                    result_json = re_result
                    result_json["re_searched"] = True
                    print(f"[JUDGE] Kết luận sau re-search: {result_json.get('conclusion', 'N/A')}")
                        
        except Exception as e:
            print(f"[RE-SEARCH] Lỗi: {e}")

    if result_json:
        # Check if Agent 2 requested additional search queries
        additional_queries = result_json.get("additional_search_queries", [])
        if additional_queries and isinstance(additional_queries, list) and len(additional_queries) > 0:
            # Limit to max 3 queries
            additional_queries = additional_queries[:3]
            print(f"Synthesizer: Agent 2 requested {len(additional_queries)} additional search queries: {additional_queries}")
            
            # Perform additional searches
            from app.search import call_google_search
            from app.ranker import get_rank_from_url, _extract_date
            from datetime import datetime
            import asyncio
            
            additional_evidence = []
            seen_urls = set(evidence_bundle.get("seen_urls", set()))
            
            for query in additional_queries:
                try:
                    print(f"Synthesizer: Searching additional query: '{query}'")
                    search_items = await asyncio.to_thread(call_google_search, query, "")
                    
                    for item in search_items or []:
                        link = item.get('link')
                        if link and link not in seen_urls:
                            seen_urls.add(link)
                            # Rank and classify the item
                            rank = get_rank_from_url(link)
                            date = _extract_date(item.get('snippet', ''), item.get('title', ''))
                            is_old = False
                            if date:
                                try:
                                    date_obj = datetime.strptime(date[:10], '%Y-%m-%d')
                                    days_diff = (datetime.now() - date_obj).days
                                    is_old = days_diff > 365
                                except:
                                    pass
                            
                            additional_evidence.append({
                                'title': item.get('title', ''),
                                'link': link,
                                'snippet': item.get('snippet', ''),
                                'source': link,
                                'rank': rank,
                                'date': date,
                                'is_old': is_old
                            })
                except Exception as e:
                    print(f"Synthesizer: Error searching additional query '{query}': {e}")
                    continue
            
            # If we found additional evidence, merge it into evidence bundle and re-analyze
            if additional_evidence:
                print(f"Synthesizer: Found {len(additional_evidence)} additional evidence items, re-analyzing...")
                
                # Merge additional evidence into appropriate layers
                # Add to layer_3_general (or layer_2 if high rank)
                for item in additional_evidence:
                    rank = item.get('rank', 0)
                    if rank >= 0.7:
                        if 'layer_2_trusted' not in evidence_bundle:
                            evidence_bundle['layer_2_trusted'] = []
                        evidence_bundle['layer_2_trusted'].append(item)
                    else:
                        if 'layer_3_general' not in evidence_bundle:
                            evidence_bundle['layer_3_general'] = []
                        evidence_bundle['layer_3_general'].append(item)
                
                # Update seen_urls
                evidence_bundle['seen_urls'] = seen_urls
                
                # Re-trim and re-analyze with updated evidence
                trimmed_bundle = _trim_evidence_bundle(evidence_bundle)
                evidence_bundle_json = json.dumps(trimmed_bundle, indent=2, ensure_ascii=False)
                
                # Update prompt with new evidence
                updated_prompt = SYNTHESIS_PROMPT
                updated_prompt = updated_prompt.replace("{evidence_bundle_json}", evidence_bundle_json)
                updated_prompt = updated_prompt.replace("{text_input}", text_input)
                updated_prompt = updated_prompt.replace("{current_date}", current_date)
                
                # Call Agent 2 again with updated evidence (only once to avoid infinite loop)
                try:
                    if provider == "gemini":
                        text_response = await call_gemini_model(
                            model_name, updated_prompt, timeout=None if flash_mode else 45.0
                        )
                    elif provider == "openrouter":
                        text_response = await call_openrouter_chat_completion(
                            model_name,
                            updated_prompt,
                            timeout=60.0,
                            temperature=0.1,
                            system_prompt=(
                                "You are ZeroFake Agent 2 (Synthesizer). "
                                "Read the evidence bundle and user's news claim. "
                                "Respond ONLY with a valid JSON object that matches the required schema. "
                                "Do NOT request additional_search_queries again - use the provided evidence."
                            ),
                        )
                    
                    # Parse the updated response
                    updated_result = _parse_json_from_text(text_response or "")
                    if updated_result:
                        # Remove additional_search_queries from final result (internal use only)
                        updated_result.pop("additional_search_queries", None)
                        updated_result["cached"] = False

                        # (NEW) Extract evidence_link from the best evidence item
                        top_link = ""
                        if evidence_bundle.get("layer_2_high_trust"):
                            top_link = evidence_bundle["layer_2_high_trust"][0].get("url") or ""
                        elif evidence_bundle.get("layer_3_general"):
                            top_link = evidence_bundle["layer_3_general"][0].get("url") or ""
                        updated_result["evidence_link"] = top_link

                        # Normalize conclusion to only 3 categories
                        updated_result["conclusion"] = normalize_conclusion(updated_result.get("conclusion", ""))
                        
                        print(f"Synthesizer: Re-analysis complete with additional evidence (link: {top_link})")
                        return updated_result
                except Exception as e:
                    print(f"Synthesizer: Error during re-analysis: {e}")
                    # Fall through to return original result
        
        # Remove additional_search_queries from final result (internal use only)
        result_json.pop("additional_search_queries", None)
        result_json["cached"] = False

        # Extract evidence_link from the best evidence item (check both 'url' and 'link')
        top_link = ""
        for layer in ["layer_2_high_trust", "layer_3_general", "layer_4_social_low"]:
            if evidence_bundle.get(layer) and len(evidence_bundle[layer]) > 0:
                item = evidence_bundle[layer][0]
                top_link = item.get("url") or item.get("link") or ""
                if top_link:
                    break
        result_json["evidence_link"] = top_link

        # Add debate_log with CRITIC feedback (for evaluation metrics)
        result_json["debate_log"] = {
            "red_team_argument": critic_feedback[:500] if critic_feedback else "",
            "blue_team_argument": result_json.get("final_message", result_json.get("reason", ""))[:500]
        }

        # Normalize conclusion to only 3 categories
        result_json["conclusion"] = normalize_conclusion(result_json.get("conclusion", ""))

        # Ensure 'reason' field is populated for evaluation metrics
        if not result_json.get("reason"):
            # Try to extract from final_message or judge_reasoning
            result_json["reason"] = result_json.get("final_message", "") or \
                                    result_json.get("judge_reasoning", {}).get("final_logic", "")

        return result_json

    print("Lỗi khi gọi Agent 2 (Synthesizer): Model response invalid or empty.")
    # (SỬA ĐỔI) Gọi hàm fallback đã được cập nhật
    heuristic_result = _heuristic_summarize(text_input, trimmed_bundle, current_date)
    # Normalize conclusion for heuristic result too
    heuristic_result["conclusion"] = normalize_conclusion(heuristic_result.get("conclusion", ""))
    return heuristic_result
