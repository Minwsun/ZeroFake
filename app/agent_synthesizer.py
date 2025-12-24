# app/agent_synthesizer.py

import os
import json
import re
from dotenv import load_dotenv
from typing import Dict, Any, List

from app.weather import classify_claim
from app.model_clients import (
    call_gemini_model,
    call_groq_chat_completion,
    call_agent_with_capability_fallback,
    ModelClientError,
    RateLimitError,
)
from app.tool_executor import execute_tool_plan  # Import for Re-Search
from app.fact_check import call_google_fact_check, interpret_fact_check_rating, format_fact_check_evidence  # NEW: Fact Check API
from app.search_helper import quick_fact_check, search_google_news, search_wikipedia  # NEW: Direct search for JUDGE/CRITIC

load_dotenv()


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SYNTHESIS_PROMPT = ""
CRITIC_PROMPT = ""  # NEW: Prompt cho CRITIC agent

# ==============================================================================
# COGNITIVE PIPELINE FLAGS - Quy trình tư duy CRITIC-JUDGE
# ==============================================================================
# SEARCH FLAGS - Cho phép search khi THỰC SỰ cần thiết
# ==============================================================================
ENABLE_CRITIC_SEARCH = False    # TẮT - CRITIC chỉ tư duy, không search thêm
ENABLE_COUNTER_SEARCH = False   # TẮT - JUDGE chỉ tư duy, không search thêm
ENABLE_SELF_CORRECTION = False  # TẮT - Không có UNIFIED-RE-SEARCH (tốn thời gian)


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
# SYNTH LOGIC: Để LLM tự phân loại claim (không dùng pattern cứng)
# ==============================================================================

def _classify_claim_type(text_input: str) -> str:
    """
    SIMPLIFIED: Không dùng pattern cứng nữa.
    Trả về "AUTO" để LLM tự quyết định dựa trên context.
    
    LLM sẽ tự phân loại:
    - KNOWLEDGE: Kiến thức cố định (địa lý, khoa học, định nghĩa)
    - NEWS: Tin tức, sự kiện, tuyên bố
    
    Như vậy hệ thống sẽ khách quan hơn và hoạt động trên mọi trường hợp.
    """
    return "AUTO"


def normalize_conclusion(conclusion: str) -> str:
    """
    Normalize conclusion to BINARY classification: TIN THẬT or TIN GIẢ only.
    
    🔴 NGUYÊN TẮC MỚI: PRESUMPTION OF DOUBT
    - Mặc định là TIN GIẢ nếu không chứng minh được TIN THẬT
    - Chỉ trả về TIN THẬT khi có keywords chỉ định rõ ràng
    """
    if not conclusion:
        return "TIN GIẢ"  # MẶC ĐỊNH: Không có kết luận = TIN GIẢ
    
    conclusion_upper = conclusion.upper().strip()
    
    # 🟢 CHỈ TIN THẬT KHI CÓ DẤU HIỆU RÕ RÀNG
    true_indicators = [
        # English true indicators
        "TRUE NEWS", "TRUE", "REAL", "VERIFIED", "CONFIRMED",
        # Vietnamese true indicators
        "TIN THẬT", "TIN THAT", "THẬT", "THAT", "ĐÚNG", "DUNG",
        "XÁC NHẬN", "XAC NHAN", "CHÍNH XÁC", "CHINH XAC",
    ]
    
    for indicator in true_indicators:
        if indicator in conclusion_upper:
            return "TIN THẬT"
    
    # MẶC ĐỊNH: Không chứng minh được TIN THẬT → TIN GIẢ
    # Bao gồm cả các trường hợp: TIN GIẢ, FAKE, FALSE, UNVERIFIED, etc.
    return "TIN GIẢ"


# Some legacy fake indicators for reference (deprecated - logic đảo ngược)
_DEPRECATED_FAKE_INDICATORS = [
    # English fake indicators (new prompts are in English)
    "FAKE NEWS", "FAKE", "FALSE", "UNTRUE", "NOT TRUE",
    # Vietnamese fake indicators
    "TIN GIẢ", "TIN GIA", "GIẢ MẠO",
    "BỊA ĐẶT", "BIA DAT", "LỪA ĐẢO", "LUA DAO", "SCAM",
]


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


# ==============================================================================
# TRUSTED SOURCE DETECTION - Reduce False Positive Rate
# ==============================================================================

TRUSTED_SOURCE_PREFIXES = [
    # International news agencies
    "theo reuters:", "reuters:", "theo ap:", "ap news:", "thông tin từ ap:",
    "afp:", "theo afp:", 
    # Major broadcasters
    "bbc đưa tin:", "bbc:", "cnn:", "theo cnn:",
    # Vietnamese trusted sources
    "theo vnexpress:", "vnexpress:", "tuổi trẻ:", "thanh niên:", "dân trí:",
    "theo nguồn tin chính thức:", 
    # International newspapers
    "the guardian:", "new york times:", "washington post:", "the economist:",
]

def _has_trusted_source_citation(text: str) -> bool:
    """
    Check if claim begins with a trusted source citation.
    Claims with trusted source prefixes should be given benefit of the doubt.
    
    Returns True if text starts with a trusted source prefix.
    """
    if not text:
        return False
    text_lower = text.lower().strip()
    return any(text_lower.startswith(prefix) for prefix in TRUSTED_SOURCE_PREFIXES)


def _is_common_knowledge(text_input: str) -> bool:
    """
    Detect if the claim is about well-known, easily verifiable facts.
    These are facts that are widely accepted and don't need extensive verification.
    
    SOFT MATCHING: 70-80% match is OK for geographic/sports facts.
    """
    text_lower = text_input.lower()
    
    # ===========================================================================
    # CATEGORY 1: Tech/Company Facts (exact match)
    # ===========================================================================
    tech_patterns = [
        ("chatgpt", "openai"), ("gpt-4", "openai"), ("gpt-3", "openai"),
        ("google", "alphabet"), ("youtube", "google"),
        ("instagram", "meta"), ("whatsapp", "meta"), ("facebook", "meta"),
        ("iphone", "apple"), ("android", "google"),
        ("windows", "microsoft"), ("azure", "microsoft"), ("aws", "amazon"),
    ]
    
    for pattern in tech_patterns:
        if all(keyword in text_lower for keyword in pattern):
            return True
    
    # ===========================================================================
    # CATEGORY 2: Geographic/Population Facts (soft match - 70-80% OK)
    # ===========================================================================
    geo_facts = [
        # Vietnam
        ("việt nam", "hà nội", "thủ đô"), ("vietnam", "hanoi", "capital"),
        ("việt nam", "63", "tỉnh"), ("việt nam", "tỉnh thành"),
        ("việt nam", "dân số", "100"), ("việt nam", "triệu người"),
        ("việt nam", "diện tích"), ("việt nam", "km²"),
        ("việt nam", "giáp", "trung quốc"), ("việt nam", "giáp", "lào"),
        ("việt nam", "giáp", "campuchia"),
        ("fansipan", "cao nhất"), ("fansipan", "3143"),
        ("mekong", "sông"), ("mê kông", "sông"),
        # General geography
        ("trái đất", "quay", "mặt trời"),
        ("nước", "sôi", "100"), ("nước sôi", "độ"),
    ]
    
    for pattern in geo_facts:
        matches = sum(1 for kw in pattern if kw in text_lower)
        # Soft match: 70% of keywords is enough
        if matches >= len(pattern) * 0.7:
            return True
    
    # ===========================================================================
    # CATEGORY 3: Major Sports Events (soft match)
    # ===========================================================================
    sports_facts = [
        # World Cup
        ("argentina", "world cup", "2022"), ("messi", "world cup", "2022"),
        ("argentina", "vô địch", "2022"), ("argentina", "world cup"),
        ("france", "world cup", "2018"), ("pháp", "world cup", "2018"),
        # Champions League
        ("real madrid", "champions league", "2024"),
        ("real madrid", "champions", "2024"),
        ("real madrid", "vô địch", "champions"),
        ("inter", "serie a", "2024"), ("napoli", "serie a", "2023"),
        ("manchester city", "premier league"),
        # Transfers
        ("ronaldo", "al-nassr"), ("ronaldo", "al nassr"),
        ("messi", "inter miami"), ("messi", "barcelona"),
        # NBA
        ("nba", "mvp"), ("nba", "champion"),
        # Other sports
        ("taylor swift", "eras tour"),
        ("bts", "nghĩa vụ", "quân sự"),
    ]
    
    for pattern in sports_facts:
        matches = sum(1 for kw in pattern if kw in text_lower)
        # Soft match: 70% of keywords is enough
        if matches >= len(pattern) * 0.7:
            return True
    
    # ===========================================================================
    # CATEGORY 4: Historical Events (known to AI)
    # ===========================================================================
    historical_facts = [
        ("facebook", "meta", "2021"),
        ("vinfast", "nasdaq", "2023"), ("vinfast", "ipo"),
        ("who", "covid", "khẩn cấp"), ("who", "pandemic"),
        ("alibaba", "chia tách"), ("alibaba", "split"),
        ("jimmy carter", "qua đời"), ("jimmy carter", "died"),
    ]
    
    for pattern in historical_facts:
        if all(keyword in text_lower for keyword in pattern):
            return True
    
    return False


def _detect_zombie_news(text_input: str, current_date: str) -> dict | None:
    """
    Detect ZOMBIE NEWS: News about past events presented as if they just happened.
    
    Examples:
    - "Việt Nam vô địch AFF Cup 2018 đêm qua" (AFF 2018 but "last night")
    - "Steve Jobs vừa qua đời" (Steve Jobs died in 2011)
    - "Samsung Galaxy Note 7 bị thu hồi" (Note 7 was recalled in 2016)
    
    Returns dict with zombie news info if detected, None otherwise.
    """
    import re
    from datetime import datetime
    
    text_lower = text_input.lower()
    
    # Get current year from current_date or system
    try:
        if current_date and len(current_date) >= 4:
            current_year = int(current_date[:4])
        else:
            current_year = datetime.now().year
    except:
        current_year = datetime.now().year
    
    # Words indicating "just happened" / "breaking news" / "recent"
    recency_indicators = [
        "đêm qua", "sáng nay", "vừa", "mới", "hôm nay", "hôm qua", "tuần này",
        "breaking", "nóng", "khẩn cấp", "mới nhất", "cập nhật", "tin sốc",
        "vừa xảy ra", "vừa mới", "sáng sớm", "chiều nay", "tối nay",
        "xem ngay", "share ngay", "chia sẻ ngay"
    ]
    
    has_recency_indicator = any(indicator in text_lower for indicator in recency_indicators)
    
    if not has_recency_indicator:
        return None
    
    # Pattern 1: Detect year in the text (e.g., "2018", "2019", etc.)
    # Only consider years that are significantly in the past (at least 1 year ago)
    year_pattern = re.search(r'\b(19\d{2}|20[0-2]\d)\b', text_input)
    if year_pattern:
        mentioned_year = int(year_pattern.group(1))
        years_ago = current_year - mentioned_year
        
        # If the mentioned year is at least 1 year ago, this is zombie news
        if years_ago >= 1:
            return {
                "is_zombie_news": True,
                "mentioned_year": mentioned_year,
                "current_year": current_year,
                "years_ago": years_ago,
                "recency_indicator": next((ind for ind in recency_indicators if ind in text_lower), "unknown")
            }
    
    # Pattern 2: Known past events database (famous events that can't "just happen")
    # These are events that definitively happened in the past and cannot happen again
    known_past_events = [
        # Deaths of famous people
        ("steve jobs", "qua đời", 2011),
        ("steve jobs", "died", 2011),
        ("michael jackson", "qua đời", 2009),
        ("michael jackson", "died", 2009),
        ("kobe bryant", "qua đời", 2020),
        ("kobe bryant", "died", 2020),
        
        # Product recalls/launches that are old
        ("galaxy note 7", "thu hồi", 2016),
        ("galaxy note 7", "recall", 2016),
        ("galaxy note 7", "cháy nổ", 2016),
        
        # Aviation incidents
        ("mh370", "mất tích", 2014),
        ("mh370", "missing", 2014),
        
        # Specific tournaments with years (AFF Cup 2018 was in past)
        # Sports events follow: {event} + {year} + recency = zombie
    ]
    
    for keywords_year in known_past_events:
        *keywords, event_year = keywords_year
        if all(kw in text_lower for kw in keywords):
            years_ago = current_year - event_year
            if years_ago >= 1:
                return {
                    "is_zombie_news": True,
                    "mentioned_year": event_year,
                    "current_year": current_year,
                    "years_ago": years_ago,
                    "recency_indicator": next((ind for ind in recency_indicators if ind in text_lower), "unknown"),
                    "known_event": " ".join(keywords)
                }
    return None


# NOTE: _detect_half_truth function REMOVED per user request
# System should be objective and rely on LLM reasoning, not hardcoded patterns
# Real-world scenarios are more complex than patterns can handle


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
    """Trích xuất JSON an toàn từ text trả về của LLM - IMPROVED VERSION"""
    if not text:
        print("LỖI: Agent 2 (Synthesizer) không tìm thấy JSON.")
        return {}

    cleaned = text.strip()
    
    # Remove <think>...</think> blocks (common in reasoning models)
    cleaned = re.sub(r'<think>.*?</think>', '', cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()
    
    # Remove Markdown code fences if present
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = cleaned.rstrip("`").strip()
    
    # METHOD 1: Find JSON by balanced braces
    def find_json_object(s: str) -> str | None:
        start = s.find('{')
        if start == -1:
            return None
        depth = 0
        for i, c in enumerate(s[start:], start):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return s[start:i+1]
        return None
    
    json_str = find_json_object(cleaned)
    if json_str:
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass  # Continue to fallback
    
    # METHOD 2: Try direct JSON load
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    
    # METHOD 3: FALLBACK - Extract conclusion from raw text
    result = {}
    text_lower = cleaned.lower()
    
    # Extract conclusion - multiple patterns
    if "tin giả" in text_lower or "tin gả" in text_lower or '"conclusion": "tin giả"' in text_lower or "fake" in text_lower:
        result["conclusion"] = "TIN GIẢ"
    elif "tin thật" in text_lower or "tin that" in text_lower or '"conclusion": "tin thật"' in text_lower or "true news" in text_lower:
        result["conclusion"] = "TIN THẬT"
    
    # Extract confidence from multiple patterns
    # Pattern 1: "confidence": 85, "confidence_score": 75, probability_score: 90
    conf_patterns = [
        r'(?:confidence|probability)[_\s]*(?:score)?["\s:]+(\d+)',
        r'"confidence_score"\s*:\s*(\d+)',
        r'"probability_score"\s*:\s*(\d+)',
        r'confidence[:\s]+(\d+)\s*%',
        r'(\d+)\s*%\s*(?:confidence|chắc chắn)',
    ]
    for pattern in conf_patterns:
        conf_match = re.search(pattern, text_lower)
        if conf_match:
            result["confidence_score"] = int(conf_match.group(1))
            break
    
    # If conclusion found but no confidence, default to 70
    if result.get("conclusion") and not result.get("confidence_score"):
        result["confidence_score"] = 70  # Default confidence
    
    # Extract reason
    reason_match = re.search(r'"reason"\s*:\s*"([^"]+)"', cleaned, re.IGNORECASE)
    if reason_match:
        result["reason"] = reason_match.group(1)
    
    if result.get("conclusion"):
        print(f"[JSON FALLBACK] Extracted from raw text: {result.get('conclusion')} ({result.get('confidence_score', 70)}%)")
        return result
    
    print(f"LỖI: Agent 2 (Synthesizer) không tìm thấy JSON. Raw response: {cleaned[:300]}...")
    return {}


# Track if Fact Check API was used (only CRITIC OR JUDGE can use, not both)
_fact_check_used_by = None  # "CRITIC" or "JUDGE" or None


async def _agent_fact_check(agent_name: str, query: str) -> dict:
    """
    Allow CRITIC or JUDGE to call Fact Check API (only one can use per claim).
    Returns: {"used": bool, "results": list, "conclusion": str, "confidence": int}
    """
    global _fact_check_used_by
    
    # Only one agent can use fact check
    if _fact_check_used_by is not None:
        print(f"[FACT-CHECK] {agent_name} skipped - already used by {_fact_check_used_by}")
        return {"used": False, "results": [], "conclusion": "", "confidence": 0}
    
    print(f"[FACT-CHECK] {agent_name} calling Fact Check API for: {query[:50]}...")
    _fact_check_used_by = agent_name
    
    results = await call_google_fact_check(query)
    
    if results:
        # Find highest confidence result
        best_conclusion = ""
        best_confidence = 0
        for r in results:
            conclusion, confidence = interpret_fact_check_rating(r.get("rating", ""))
            if confidence > best_confidence:
                best_conclusion = conclusion
                best_confidence = confidence
        
        print(f"[FACT-CHECK] {agent_name} got {len(results)} results, best: {best_conclusion} ({best_confidence}%)")
        return {
            "used": True,
            "results": results,
            "conclusion": best_conclusion,
            "confidence": best_confidence,
            "evidence_text": format_fact_check_evidence(results)
        }
    
    return {"used": True, "results": [], "conclusion": "", "confidence": 0}


def _reset_fact_check_state():
    """Reset fact check usage tracking for new claim."""
    global _fact_check_used_by
    _fact_check_used_by = None


# ==============================================================================
# FILTER SEARCH RESULT - LLM-based evidence filtering
# ==============================================================================

FILTER_PROMPT = ""

# Cache for filter results (key: claim_hash, value: filtered_bundle)
_filter_cache = {}
_FILTER_CACHE_MAX_SIZE = 500  # Increased from 200 for better cache hit rate

def _get_claim_hash(claim: str, evidence_count: int) -> str:
    """Generate hash for caching filter results."""
    import hashlib
    cache_key = f"{claim.strip().lower()}_{evidence_count}"
    return hashlib.md5(cache_key.encode()).hexdigest()[:16]

def load_filter_prompt(prompt_path="prompts/filter_search_result.txt"):
    """Tải prompt cho Filter Search Result agent"""
    global FILTER_PROMPT
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            FILTER_PROMPT = f.read()
        print("INFO: Tải Filter Search Result Prompt thành công.")
    except FileNotFoundError:
        FILTER_PROMPT = (
            "Lọc các kết quả tìm kiếm. Giữ lại evidence liên quan đến claim. "
            "Loại bỏ spam, quảng cáo, nội dung không liên quan. "
            "Trả về JSON với filtered array."
        )
        print(f"WARNING: Không tìm thấy {prompt_path}, dùng prompt mặc định.")
    except Exception as e:
        print(f"LỖI: không thể tải {prompt_path}: {e}")


async def filter_evidence_with_llm(claim: str, evidence_bundle: dict, current_date: str) -> dict:
    """
    Use LLM to intelligently filter search results before passing to CRITIC/JUDGE.
    
    Model Priority:
    1. Llama 8B (Groq) - Fast & accurate
    2. Gemma 27B - High quality fallback
    3. Gemma 12B - Medium fallback
    4. Gemma 4B - Light fallback
    
    Input: Raw evidence bundle from search
    Output: Filtered evidence bundle (only useful evidence)
    """
    if not FILTER_PROMPT:
        load_filter_prompt()
    
    # Combine all evidence into a single list for filtering
    all_evidence = []
    
    # Layer 2: High trust sources
    for idx, item in enumerate(evidence_bundle.get("layer_2_high_trust", [])):
        all_evidence.append({
            "i": idx,  # Shortened key to save tokens
            "s": item.get("source", ""),
            "t": (item.get("snippet", "") or "")[:400],  # 400 chars for balanced info
        })
    
    # Layer 3: General sources
    l2_count = len(all_evidence)
    for idx, item in enumerate(evidence_bundle.get("layer_3_general", [])):
        all_evidence.append({
            "i": l2_count + idx,
            "s": item.get("source", ""),
            "t": (item.get("snippet", "") or "")[:400],  # 400 chars for balanced info
        })
    
    # Layer 4: Low trust sources (previously blocked)
    l3_count = len(all_evidence)
    for idx, item in enumerate(evidence_bundle.get("layer_4_social_low", [])):
        all_evidence.append({
            "i": l3_count + idx,
            "s": item.get("source", ""),
            "t": (item.get("snippet", "") or "")[:400],  # 400 chars for balanced info
        })
    
    if not all_evidence:
        print("[FILTER] No evidence to filter")
        return evidence_bundle
    
    l2_len = len(evidence_bundle.get("layer_2_high_trust", []))
    l3_len = len(evidence_bundle.get("layer_3_general", []))
    l4_len = len(evidence_bundle.get("layer_4_social_low", []))
    
    # Check cache first
    cache_key = _get_claim_hash(claim, len(all_evidence))
    if cache_key in _filter_cache:
        print(f"[FILTER] Cache HIT for {cache_key[:8]}... - returning cached result")
        return _filter_cache[cache_key]
    
    print(f"[FILTER] Input: {len(all_evidence)} items (L2={l2_len}, L3={l3_len}, L4={l4_len})")
    print(f"[FILTER] Goal: Remove duplicates, keep max 10 best items...")
    
    # Prepare prompt - compact format
    evidence_json = json.dumps(all_evidence, ensure_ascii=False, separators=(',', ':'))
    filter_prompt_filled = FILTER_PROMPT.replace("{claim}", claim)
    filter_prompt_filled = filter_prompt_filled.replace("{search_results}", evidence_json)
    
    filter_response = None
    model_used = None
    
    # Model cascade: Llama 8B (Groq) → Gemma 4B (fastest fallback)
    # Reduced cascade for latency optimization
    models_to_try = [
        ("groq", "llama-3.1-8b-instant"),
        ("gemini", "models/gemma-3-4b-it"),  # Skip 27B/12B for speed
    ]
    
    for provider, model_name in models_to_try:
        try:
            print(f"[FILTER] Trying {provider}/{model_name}...")
            
            if provider == "groq":
                filter_response = await call_groq_chat_completion(
                    model_name=model_name,
                    prompt=filter_prompt_filled,
                    temperature=0.1,
                    timeout=15.0,  # Reduced from 30s
                )
            else:  # gemini
                filter_response = await call_gemini_model(
                    model_name=model_name,
                    prompt=filter_prompt_filled,
                    timeout=20.0,  # Reduced from 45s
                    safety_settings=SAFETY_SETTINGS
                )
            
            if filter_response:
                model_used = f"{provider}/{model_name}"
                print(f"[FILTER] Success with {model_used}")
                break
                
        except Exception as e:
            print(f"[FILTER] {provider}/{model_name} failed: {e}")
            continue
    
    if not filter_response:
        print("[FILTER] All models failed, returning original evidence")
        return evidence_bundle
    
    # Parse response - expect {"filtered": [{"i": 0, "s": "source", "info": "..."}, ...], "removed": [...]}
    try:
        filter_result = _parse_json_from_text(filter_response)
        
        if not filter_result:
            print("[FILTER] Failed to parse JSON, returning original evidence")
            return evidence_bundle
        
        # Get filtered items (support both "filtered" and "keep" keys)
        keep_items = filter_result.get("filtered", []) or filter_result.get("keep", [])
        removed_items = filter_result.get("removed", [])
        
        if not isinstance(keep_items, list):
            print("[FILTER] Invalid format, returning original evidence")
            return evidence_bundle
        
        # Log removed items
        if removed_items:
            print(f"[FILTER] REMOVED: {', '.join(str(r) for r in removed_items[:5])}{'...' if len(removed_items) > 5 else ''}")
        
        # Extract indices and log info
        keep_set = set()
        for item in keep_items:
            if isinstance(item, dict):
                idx = item.get("i")
                source = item.get("s", "")
                info = item.get("info", "") or item.get("r", "")  # Support both "info" and "r"
                if idx is not None:
                    keep_set.add(idx)
                    print(f"[FILTER] ✓ #{idx} ({source}): {info[:60]}{'...' if len(info) > 60 else ''}")
            elif isinstance(item, (int, float)):
                # Fallback: plain index array
                keep_set.add(int(item))
        
        print(f"[FILTER] Keeping {len(keep_set)}/{len(all_evidence)} items")
        
        # Rebuild evidence bundle from filtered indices
        filtered_bundle = {
            "layer_1_tools": evidence_bundle.get("layer_1_tools", []),  # Keep weather data
            "layer_2_high_trust": [],
            "layer_3_general": [],
            "layer_4_social_low": [],
            "fact_check_verdict": evidence_bundle.get("fact_check_verdict"),  # Keep fact check
        }
        
        # Map filtered indices back to layers
        l2_items = evidence_bundle.get("layer_2_high_trust", [])
        l3_items = evidence_bundle.get("layer_3_general", [])
        l4_items = evidence_bundle.get("layer_4_social_low", [])
        
        for idx, item in enumerate(l2_items):
            if idx in keep_set:
                filtered_bundle["layer_2_high_trust"].append(item)
        
        l2_max = len(l2_items)
        for idx, item in enumerate(l3_items):
            if (l2_max + idx) in keep_set:
                filtered_bundle["layer_3_general"].append(item)
        
        l3_max = l2_max + len(l3_items)
        for idx, item in enumerate(l4_items):
            if (l3_max + idx) in keep_set:
                filtered_bundle["layer_4_social_low"].append(item)
        
        kept_total = (len(filtered_bundle["layer_2_high_trust"]) + 
                      len(filtered_bundle["layer_3_general"]) + 
                      len(filtered_bundle["layer_4_social_low"]))
        
        print(f"[FILTER] Result: L2={len(filtered_bundle['layer_2_high_trust'])}, "
              f"L3={len(filtered_bundle['layer_3_general'])}, "
              f"L4={len(filtered_bundle['layer_4_social_low'])} (total={kept_total})")
        
        # Save to cache (with size limit)
        if len(_filter_cache) >= _FILTER_CACHE_MAX_SIZE:
            # Remove oldest entry (first key)
            oldest_key = next(iter(_filter_cache))
            del _filter_cache[oldest_key]
        _filter_cache[cache_key] = filtered_bundle
        
        return filtered_bundle
        
    except Exception as e:
        print(f"[FILTER] Error parsing response: {e}")
        print("[FILTER] Returning original evidence bundle")
        return evidence_bundle

def _trim_snippet(s: str, max_len: int = 400) -> str:
    """
    Use 400 chars for balanced context.
    """
    if not s:
        return ""
    s = s.replace("\n", " ").strip()
    return s[:max_len]


def _trim_evidence_bundle(bundle: Dict[str, Any], cap_l2: int = 1000, cap_l3: int = 1000, cap_l4: int = 1000, claim_text: str = "") -> Dict[str, Any]:
    """
    OPTIMIZED: Filter evidence by relevance before capping.
    Only include evidence that mentions keywords from the claim.
    This reduces token waste on irrelevant search results.
    """
    if not bundle:
        return {"layer_1_tools": [], "layer_2_high_trust": [], "layer_3_general": [], "layer_4_social_low": []}
    
    # Extract keywords from claim for relevance filtering
    claim_keywords = set()
    if claim_text:
        # Extract words with 3+ chars, excluding common words
        stop_words = {"được", "trong", "với", "của", "cho", "người", "những", "theo", "đang", "sẽ", "đã", "này", "các", "một", "have", "been", "from", "with", "that", "this", "will", "the", "and", "for"}
        words = re.findall(r'\b\w{3,}\b', claim_text.lower())
        claim_keywords = {w for w in words if w not in stop_words}
    
    def is_relevant(item: Dict) -> bool:
        """
        Check if evidence snippet is TRULY relevant to the claim.
        IMPROVED: Requires at least 2 keyword matches OR 50% of keywords.
        This prevents false positives like "Bill Clinton" matching "Bill Gates".
        """
        if not claim_keywords:
            return True  # No filtering if no claim provided
        
        snippet = (item.get("snippet") or "").lower()
        title = (item.get("title") or "").lower()
        url = (item.get("url") or "").lower()
        combined = snippet + " " + title + " " + url
        
        # Count how many keywords match
        matched_keywords = [kw for kw in claim_keywords if kw in combined]
        match_count = len(matched_keywords)
        
        # STRICTER MATCHING:
        # - If claim has 3+ keywords: need at least 2 matches
        # - If claim has 1-2 keywords: need at least 1 match
        min_required = 2 if len(claim_keywords) >= 3 else 1
        
        return match_count >= min_required

    
    out = {
        "layer_1_tools": [],
        "layer_2_high_trust": [],
        "layer_3_general": [],
        "layer_4_social_low": []
    }
    
    # Lớp 1: OpenWeather API data (always include)
    for it in (bundle.get("layer_1_tools") or []):
        out["layer_1_tools"].append({
            "source": it.get("source"),
            "url": it.get("url"),
            "snippet": _trim_snippet(it.get("snippet")),
            "rank_score": it.get("rank_score"),
            "date": it.get("date"),
            "weather_data": it.get("weather_data")
        })
    
    # Lớp 2: RE-ENABLED FILTER - Lọc theo relevance để tránh nhầm lẫn (Bill Gates vs Bill Clinton)
    all_l2 = bundle.get("layer_2_high_trust") or []
    for it in all_l2[:cap_l2]:
        if is_relevant(it):
            out["layer_2_high_trust"].append({
                "source": it.get("source"),
                "url": it.get("url"),
                "snippet": _trim_snippet(it.get("snippet")),
                "rank_score": it.get("rank_score"),
                "date": it.get("date")
            })
    
    # Lớp 3: RE-ENABLED FILTER - Lọc theo relevance
    all_l3 = bundle.get("layer_3_general") or []
    for it in all_l3[:cap_l3]:
        if is_relevant(it):
            out["layer_3_general"].append({
                "source": it.get("source"),
                "url": it.get("url"),
                "snippet": _trim_snippet(it.get("snippet")),
                "rank_score": it.get("rank_score"),
                "date": it.get("date")
            })
    
    # Lớp 4: RE-ENABLED FILTER - Lọc theo relevance
    all_l4 = bundle.get("layer_4_social_low") or []
    for it in all_l4[:cap_l4]:
        if is_relevant(it):
            out["layer_4_social_low"].append({
                "source": it.get("source"),
                "url": it.get("url"),
                "snippet": _trim_snippet(it.get("snippet")),
                "rank_score": it.get("rank_score"),
                "date": it.get("date")
            })

    
    # Log số lượng evidence (không filter nữa)
    total_evidence = len(all_l2) + len(all_l3) + len(all_l4)
    if total_evidence > 0:
        print(f"[EVIDENCE] Total: {total_evidence} items (L2={len(all_l2)}, L3={len(all_l3)}, L4={len(all_l4)})")
    else:
        print(f"[EVIDENCE] No evidence found")
    
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
    # NOTE: Pattern-based detection REMOVED for objectivity
    # LLM will decide based on evidence, not hardcoded patterns
    # ═══════════════════════════════════════════════════════════════
    
    # ═══════════════════════════════════════════════════════════════
    # PRIORITY 0.5: Trusted Source Citations (NEW - Reduce False Positive)
    # ═══════════════════════════════════════════════════════════════
    if _has_trusted_source_citation(text_input):
        # Check if evidence CONTRADICTS the claim
        combined_evidence = " ".join(
            [item.get("snippet", "") for item in l2 + l3]
        ).lower()
        
        # Only mark as fake if CONTRADICTING evidence found
        contradiction_keywords = ["sai sự thật", "bác bỏ", "debunked", "fake", "false", "không chính xác", "incorrect"]
        has_contradiction = any(kw in combined_evidence for kw in contradiction_keywords)
        
        if not has_contradiction:
            # Extract source name from text
            source_match = None
            for prefix in TRUSTED_SOURCE_PREFIXES:
                if text_input.lower().strip().startswith(prefix):
                    source_match = prefix.replace("theo ", "").replace(":", "").replace("đưa tin", "").strip().title()
                    break
            
            debate_log = {
                "red_team_argument": "Tôi không tìm thấy bằng chứng cụ thể bác bỏ tin này.",
                "blue_team_argument": f"Claim trích dẫn nguồn uy tín ({source_match}). Không có phản chứng → nên tin.",
                "judge_reasoning": f"Blue Team thắng. Claim có nguồn {source_match} và không tìm thấy phản chứng."
            }
            return {
                "conclusion": "TIN THẬT",
                "confidence_score": 90,  # Boosted from 75 to 90 for trusted sources
                "reason": f"Claim trích dẫn nguồn uy tín ({source_match}) và không tìm thấy bằng chứng bác bỏ.",
                "debate_log": debate_log,
                "key_evidence_snippet": f"Nguồn: {source_match}",
                "key_evidence_source": source_match or "",
                "evidence_link": "",
                "style_analysis": "Tin có nguồn uy tín, ưu tiên TIN THẬT",
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

    # ═══════════════════════════════════════════════════════════════
    # PRIORITY 3: Phát hiện ZOMBIE NEWS (tin cũ trình bày như tin mới)
    # ═══════════════════════════════════════════════════════════════
    zombie_info = _detect_zombie_news(text_input, current_date)
    if zombie_info and zombie_info.get("is_zombie_news"):
        mentioned_year = zombie_info["mentioned_year"]
        years_ago = zombie_info["years_ago"]
        recency_indicator = zombie_info.get("recency_indicator", "vừa xảy ra")
        known_event = zombie_info.get("known_event", "")
        
        # Build Adversarial Dialectic debate
        debate_log = {
            "red_team_argument": _as_str(
                f"Đây là ZOMBIE NEWS! Sự kiện năm {mentioned_year} ({years_ago} năm trước) "
                f"nhưng được trình bày như vừa xảy ra ('{recency_indicator}'). "
                f"Đây là thủ thuật clickbait phổ biến để lừa người đọc."
            ),
            "blue_team_argument": _as_str(
                f"Đúng là sự kiện năm {mentioned_year} đã xảy ra thật. "
                f"Nhưng việc dùng ngôn ngữ '{recency_indicator}' là gây hiểu lầm. Tôi thua."
            ),
            "judge_reasoning": _as_str(
                f"Red Team thắng. Sự kiện năm {mentioned_year} KHÔNG THỂ '{recency_indicator}' được. "
                f"Đây là tin cũ được tái sử dụng = ZOMBIE NEWS = TIN GIẢ."
            )
        }
        
        return {
            "conclusion": "TIN GIẢ",
            "confidence_score": 95,
            "reason": _as_str(
                f"ZOMBIE NEWS: Sự kiện năm {mentioned_year} ({years_ago} năm trước) "
                f"được trình bày như vừa xảy ra ('{recency_indicator}'). "
                f"Đây là tin cũ được lặp lại để lừa người đọc."
            ),
            "debate_log": debate_log,
            "key_evidence_snippet": _as_str(f"Sự kiện xảy ra năm {mentioned_year}, không phải '{recency_indicator}'"),
            "key_evidence_source": "",
            "evidence_link": "",
            "style_analysis": "ZOMBIE NEWS - Tin cũ trình bày như tin mới",
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
    skip_critic: bool = False,    # NEW: Skip CRITIC when Fact Check has verdict
) -> dict:
    """
    Pipeline: SYNTH → CRITIC (optional) → JUDGE
    
    When skip_critic=True (Fact Check has verdict):
    - Skip CRITIC phase
    - Go directly to JUDGE with Fact Check + Search evidence
    
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

    # Reset fact check state for new claim (only CRITIC or JUDGE can use, not both)
    _reset_fact_check_state()

    # =========================================================================
    # PHASE 0: FILTER EVIDENCE với Gemma 12B
    # Lọc thông minh các kết quả tìm kiếm trước khi đưa cho CRITIC/JUDGE
    # =========================================================================
    print(f"\n[PIPELINE] Phase 0: Filtering evidence with Gemma 12B...")
    filtered_evidence_bundle = await filter_evidence_with_llm(text_input, evidence_bundle, current_date)

    # =========================================================================
    # SYNTH: Để LLM tự phân loại claim (không dùng pattern cứng)
    # =========================================================================
    claim_type = _classify_claim_type(text_input)
    print(f"\n[SYNTH] Claim type: {claim_type}")
    
    # AUTO: Để LLM tự quyết định dựa trên context
    synth_instruction = (
        "\n\n[SYNTH INSTRUCTION]\n"
        "Hãy TỰ PHÂN LOẠI claim này:\n"
        "- KNOWLEDGE: Kiến thức cố định (địa lý, khoa học, định nghĩa) → Có thể tự suy luận\n"
        "- NEWS: Tin tức, sự kiện, tuyên bố → Cần evidence\n\n"
        "Sau đó áp dụng:\n"
        "- Nếu KNOWLEDGE: Tự quyết dựa trên kiến thức nội tại\n"
        "- Nếu NEWS: Bắt buộc có evidence để kết luận\n"
        "- Nếu không có evidence bác bỏ → PRESUMPTION OF TRUTH (TIN THẬT)\n"
    )
    print(f"[SYNTH] LLM sẽ tự phân loại và quyết định")

    # Trim evidence before sending to models (using FILTERED bundle)
    trimmed_bundle = _trim_evidence_bundle(filtered_evidence_bundle, claim_text=text_input)
    
    # DEBUG: Log weather data
    weather_items = trimmed_bundle.get("layer_1_tools", [])
    if weather_items:
        print(f"[WEATHER→JUDGE] Found {len(weather_items)} weather items in evidence:")
        for item in weather_items:
            print(f"  → {item.get('source')}: {item.get('snippet', '')[:100]}...")
    
    evidence_bundle_json = json.dumps(trimmed_bundle, indent=2, ensure_ascii=False)

    # =========================================================================
    # PHASE 1: CRITIC AGENT (BIỆN LÝ ĐỐI LẬP)
    # Skip if Fact Check already has verdict - use Fact Check as "critic"
    # =========================================================================
    critic_report = "Không có phản biện."
    critic_parsed = {}
    
    # Check if Fact Check has verdict (preserved in filtered bundle)
    fact_check_verdict = filtered_evidence_bundle.get("fact_check_verdict")
    
    if skip_critic and fact_check_verdict:
        # Use Fact Check verdict as the CRITIC report
        fc_conclusion = fact_check_verdict.get("conclusion", "")
        fc_confidence = fact_check_verdict.get("confidence", 0)
        fc_source = fact_check_verdict.get("source", "Fact Check")
        fc_url = fact_check_verdict.get("url", "")
        
        print(f"\n[SKIP CRITIC] Using Fact Check verdict from {fc_source}")
        critic_report = f"""[FACT CHECK VERDICT]
Source: {fc_source}
Verdict: {fc_conclusion} (Confidence: {fc_confidence}%)
URL: {fc_url}

This claim has been fact-checked by {fc_source}. The verdict is {fc_conclusion}."""
        
        critic_parsed = {
            "issues_found": fc_conclusion == "TIN GIẢ",
            "issue_type": "FACT_CHECK_DEBUNKED" if fc_conclusion == "TIN GIẢ" else "FACT_CHECK_VERIFIED",
            "fact_check_source": fc_source,
            "fact_check_url": fc_url
        }
        print(f"[SKIP CRITIC] Fact Check verdict added to evidence")
    
    # Skip CRITIC for KNOWLEDGE claims with Wikipedia evidence
    elif claim_type == "KNOWLEDGE":
        # Check if Wikipedia evidence exists
        has_wikipedia = any(
            "wikipedia" in (item.get("source", "") or "").lower()
            for layer in ["layer_2_high_trust", "layer_3_general"]
            for item in filtered_evidence_bundle.get(layer, [])
        )
        if has_wikipedia:
            print(f"\n[SKIP CRITIC] KNOWLEDGE claim with Wikipedia evidence - skipping CRITIC")
            critic_report = "[AUTO-SKIP] Knowledge claim verified by Wikipedia. No adversarial analysis needed."
            critic_parsed = {
                "issues_found": False,
                "issue_type": "KNOWLEDGE_VERIFIED",
                "skip_reason": "Wikipedia evidence for knowledge claim"
            }
    # Skip CRITIC for common knowledge (LATENCY OPTIMIZATION)
    elif _is_common_knowledge(text_input):
        print(f"\n[SKIP CRITIC] Common knowledge detected - skipping CRITIC (saves ~40s)")
        critic_report = "[AUTO-SKIP] Common knowledge. No adversarial analysis needed."
        critic_parsed = {
            "issues_found": False,
            "issue_type": "COMMON_KNOWLEDGE",
            "skip_reason": "Common knowledge claim"
        }
    else:
        # Normal CRITIC flow
        try:
            print(f"\n[CRITIC] Bắt đầu phản biện...")
            critic_prompt_filled = CRITIC_PROMPT.replace("{text_input}", text_input)
            critic_prompt_filled = critic_prompt_filled.replace("{evidence_bundle_json}", evidence_bundle_json)
            critic_prompt_filled = critic_prompt_filled.replace("{current_date}", current_date)
            
            critic_report = await call_agent_with_capability_fallback(
                role="CRITIC",
                prompt=critic_prompt_filled,
                temperature=0.5,
                timeout=60.0  # Reduced from 120s for latency optimization
            )
            print(f"[CRITIC] Report: {critic_report[:150]}...")
            
            # Parse CRITIC response để kiểm tra counter_search_needed
            critic_parsed = _parse_json_from_text(critic_report)
            
            # NEW SCHEMA: Kiểm tra issues_found trực tiếp (không qua conclusion.issues_found)
            critic_issues = critic_parsed.get("issues_found", False)
            if not critic_issues:
                # Fallback: check old schema
                conclusion_obj = critic_parsed.get("conclusion", {})
                if isinstance(conclusion_obj, dict):
                    critic_issues = conclusion_obj.get("issues_found", False)
            
            issue_type = critic_parsed.get("issue_type", "NONE")
            if not issue_type or issue_type == "NONE":
                conclusion_obj = critic_parsed.get("conclusion", {})
                if isinstance(conclusion_obj, dict):
                    issue_type = conclusion_obj.get("issue_type", "NONE")
            
            # Log moved to after counter-search condition check
            
        except Exception as e:
            print(f"[CRITIC] Gặp lỗi: {e}")
            critic_report = "Lỗi khi chạy Critic Agent."

    # =========================================================================
    # PHASE 1.5: CRITIC COUNTER-SEARCH (nếu CRITIC cần search thêm)
    # Kích hoạt khi:
    # - CRITIC phát hiện vấn đề cần verify (issues_found=True AND issue_type != NONE)
    # - HOẶC CRITIC thiếu bằng chứng để phản biện (evidence_verdict = INSUFFICIENT)
    # =========================================================================
    
    # CRITIC output schema: adversarial_findings.issues_found, adversarial_findings.issue_type
    adv_findings = critic_parsed.get("adversarial_findings", {})
    if isinstance(adv_findings, dict):
        critic_issues = adv_findings.get("issues_found", False)
        issue_type = adv_findings.get("issue_type", "NONE")
    else:
        # Fallback to top-level (old schema)
        critic_issues = critic_parsed.get("issues_found", False)
        issue_type = critic_parsed.get("issue_type", "NONE")
    
    # Check if evidence is insufficient (CRITIC cần thêm bằng chứng để phản biện)
    evidence_assessment = critic_parsed.get("evidence_assessment", {})
    evidence_verdict = evidence_assessment.get("evidence_verdict", "UNKNOWN") if isinstance(evidence_assessment, dict) else "UNKNOWN"
    evidence_insufficient = evidence_verdict in ["INSUFFICIENT", "IRRELEVANT"]
    
    print(f"[CRITIC] Issues found: {critic_issues}, Type: {issue_type}, Evidence: {evidence_verdict}")
    
    # Counter-search CHỈ KHI THỰC SỰ CẦN THIẾT:
    # 1. Flag ENABLE_CRITIC_SEARCH = True
    # 2. VÀ một trong các điều kiện sau:
    #    a) Evidence là INSUFFICIENT hoặc IRRELEVANT (không có gì để phản biện)
    #    b) CRITIC phát hiện vấn đề CỤ THỂ (không phải NONE/UNVERIFIED chung chung)
    # 3. VÀ CRITIC có trả về counter_search_queries
    
    should_counter_search = False
    if ENABLE_CRITIC_SEARCH:
        has_critical_issue = critic_issues and issue_type not in ["NONE", "UNVERIFIED"]  # Vấn đề cụ thể như ZOMBIE, SCAM
        evidence_truly_missing = evidence_verdict in ["INSUFFICIENT", "IRRELEVANT"]
        has_valid_queries = bool(critic_parsed.get("counter_search_queries"))
        
        # CHỈ search khi: (có vấn đề cụ thể HOẶC thiếu evidence) VÀ có queries
        should_counter_search = (has_critical_issue or evidence_truly_missing) and has_valid_queries
        
        if should_counter_search:
            print(f"[CRITIC-SEARCH] Kích hoạt vì: issue={issue_type}, evidence={evidence_verdict}")
        else:
            print(f"[CRITIC-SEARCH] Bỏ qua - không đủ điều kiện")
    
    if should_counter_search:
        counter_queries = critic_parsed.get("counter_search_queries", [])
        if counter_queries:
            print(f"\n[CRITIC-SEARCH] CRITIC yêu cầu search thêm: {counter_queries}")
            try:
                from app.search import call_google_search
                
                critic_counter_evidence = []
                for query in counter_queries[:2]:  # Giới hạn 2 queries
                    results = call_google_search(query, "")
                    critic_counter_evidence.extend(results[:5])
                    if len(critic_counter_evidence) >= 5:
                        break
                
                if critic_counter_evidence:
                    print(f"[CRITIC-SEARCH] Tìm thấy {len(critic_counter_evidence)} evidence mới")
                    # Merge vào evidence bundle
                    if "layer_2_high_trust" not in evidence_bundle:
                        evidence_bundle["layer_2_high_trust"] = []
                    evidence_bundle["layer_2_high_trust"].extend(critic_counter_evidence[:3])
                    
                    # Update evidence_bundle_json cho JUDGE
                    trimmed_bundle = _trim_evidence_bundle(evidence_bundle, claim_text=text_input)
                    evidence_bundle_json = json.dumps(trimmed_bundle, indent=2, ensure_ascii=False)
                    
            except Exception as e:
                print(f"[CRITIC-SEARCH] Lỗi search: {e}")

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
            timeout=120.0  # Tăng lên 120s theo yêu cầu user
        )
        
        judge_result = _parse_json_from_text(judge_text)

        # ---------------------------------------------------------------------
        # ADAPTER: Convert to Flat Schema (Support BOTH old and new schemas)
        # ---------------------------------------------------------------------
        
        # NEW SCHEMA (simpler): conclusion, confidence_score at top level
        if not judge_result.get("conclusion"):
            # Try verdict_metadata (old schema)
            verdict_meta = judge_result.get("verdict_metadata")
            if verdict_meta and isinstance(verdict_meta, dict):
                judge_result["conclusion"] = verdict_meta.get("conclusion")
                judge_result["confidence_score"] = verdict_meta.get("probability_score")
        
        # NEW SCHEMA: key_evidence -> key_evidence_snippet, key_evidence_source
        key_ev = judge_result.get("key_evidence")
        if key_ev and isinstance(key_ev, dict):
            judge_result["key_evidence_snippet"] = key_ev.get("quote", "N/A")
            judge_result["key_evidence_source"] = key_ev.get("source", "N/A")
        
        # NEW SCHEMA: critic_response -> debate_log
        critic_resp = judge_result.get("critic_response")
        if critic_resp and isinstance(critic_resp, dict):
            judge_result["debate_log"] = {
                "critic_found_issues": critic_resp.get("critic_found_issues", False),
                "judge_agrees": critic_resp.get("judge_agrees", True),
                "judge_reasoning": critic_resp.get("judge_reasoning", "N/A")
            }
        
        # Fallback for reason - more comprehensive extraction
        if not judge_result.get("reason"):
            # Try alternate field names first
            for key in ["reasoning", "explanation", "rationale", "analysis", "summary"]:
                if judge_result.get(key):
                    judge_result["reason"] = str(judge_result[key])
                    break
            
            # Try extracting from thinking_process
            if not judge_result.get("reason"):
                thinking = judge_result.get("thinking_process")
                if thinking and isinstance(thinking, dict):
                    logical_reasoning = thinking.get("step3_logical_reasoning") or thinking.get("logical_reasoning")
                    if logical_reasoning:
                        judge_result["reason"] = str(logical_reasoning)
                    elif thinking.get("key_factors"):
                        factors = thinking.get("key_factors", [])
                        if isinstance(factors, list) and factors:
                            judge_result["reason"] = "; ".join(str(f) for f in factors[:3])
            
            # Try extracting from key_evidence
            if not judge_result.get("reason"):
                key_ev = judge_result.get("key_evidence")
                if key_ev and isinstance(key_ev, dict):
                    quote = key_ev.get("quote", "")
                    source = key_ev.get("source", "")
                    if quote and source:
                        judge_result["reason"] = f"Theo {source}: \"{quote[:200]}...\""
            
            # Final fallback: generate reason from conclusion with claim input
            if not judge_result.get("reason"):
                conclusion = judge_result.get("conclusion", "")
                verdict_meta = judge_result.get("verdict_metadata", {})
                verdict_type = verdict_meta.get("verdict_type", "") if isinstance(verdict_meta, dict) else ""
                
                # Truncate claim for display (max 100 chars)
                claim_display = text_input[:100] + "..." if len(text_input) > 100 else text_input
                
                if conclusion == "TIN GIẢ":
                    if verdict_type == "ZOMBIE_NEWS":
                        judge_result["reason"] = f"Đây là tin cũ được trình bày như tin mới (Zombie News): \"{claim_display}\""
                    elif verdict_type == "SCAM":
                        judge_result["reason"] = f"Nội dung có dấu hiệu lừa đảo/scam: \"{claim_display}\""
                    elif verdict_type == "UNVERIFIED":
                        judge_result["reason"] = f"Không có thông tin nào đề cập đến \"{claim_display}\""
                    else:
                        judge_result["reason"] = f"Không có thông tin nào đề cập đến \"{claim_display}\""
                elif conclusion == "TIN THẬT":
                    judge_result["reason"] = f"Thông tin được xác nhận từ nguồn đáng tin cậy: \"{claim_display}\""
                else:
                    # Nếu không xác minh được → TIN GIẢ (theo yêu cầu user)
                    judge_result["conclusion"] = "TIN GIẢ"
                    judge_result["reason"] = f"Không có thông tin nào đề cập đến \"{claim_display}\""
                    judge_result["confidence_score"] = 60  # Medium confidence for unverified
        
        # Final log
        if judge_result.get("conclusion"):
            conf = judge_result.get("confidence_score", "N/A")
            print(f"[JUDGE] Round 1: {judge_result.get('conclusion')} ({conf}%)")
        else:
            print(f"[JUDGE] WARNING: No valid conclusion. Fallback to heuristic.")
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
    confidence_r1 = 50
    try:
        conf_raw = judge_result.get("confidence_score")
        if conf_raw is not None:
            confidence_r1 = int(conf_raw)
    except:
        pass
    
    # Track queries already searched (avoid duplicates)
    searched_queries = set()
    # Add queries from original search (estimated from text_input)
    searched_queries.add(text_input.lower().strip())
    # Add queries from CRITIC if any
    critic_queries = critic_parsed.get("counter_search_queries", [])
    for q in critic_queries:
        if q:
            searched_queries.add(q.lower().strip())
    
    # SMART TRIGGER: Counter-search CHỈ khi JUDGE thực sự không chắc chắn (<70%)
    judge_uncertain = confidence_r1 < 70  # Thấp hơn 70% mới search thêm
    needs_more_evidence = judge_result.get("needs_more_evidence", False)
    if isinstance(needs_more_evidence, str):
        needs_more_evidence = needs_more_evidence.lower() == "true"
    
    should_counter_search = (
        ENABLE_COUNTER_SEARCH 
        and conclusion_r1 == "TIN GIẢ" 
        and judge_uncertain  # CHỈ khi confidence thấp (<70%)
    )
    
    if should_counter_search:
        print(f"\n[COUNTER-SEARCH] JUDGE ngờ ngời (confidence={confidence_r1}%) → Tìm dẫn chứng BẢO VỆ claim...")
        
        try:
            from app.search import call_google_search, _is_international_event, _extract_english_query
            
            # IMPROVED: Multi-language counter queries
            counter_queries = []
            
            # 1. Vietnamese confirmation query
            counter_queries.append(f"{text_input} tin tức chính thống")
            
            # 2. English for international events (key improvement)
            if _is_international_event(text_input):
                en_text = _extract_english_query(text_input)
                if en_text and len(en_text) > 10:
                    counter_queries.append(f"{en_text} confirmed official")
                    counter_queries.append(f"{en_text} news Reuters AP")
            else:
                counter_queries.append(f"{text_input} Reuters AFP BBC")
            
            # FILTER: Remove queries similar to already searched (avoid redundant search)
            def is_similar(q: str, searched: set) -> bool:
                q_lower = q.lower().strip()
                for s in searched:
                    # Skip if query is substring of searched or vice versa
                    if q_lower in s or s in q_lower:
                        return True
                    # Skip if >70% word overlap
                    q_words = set(q_lower.split())
                    s_words = set(s.split())
                    if q_words and s_words:
                        overlap = len(q_words & s_words) / max(len(q_words), len(s_words))
                        if overlap > 0.7:
                            return True
                return False
            
            unique_counter_queries = [q for q in counter_queries if not is_similar(q, searched_queries)]
            
            if not unique_counter_queries:
                print(f"[COUNTER-SEARCH] Bỏ qua - queries đã được search trước đó")
            else:
                counter_evidence = []
                for query in unique_counter_queries[:2]:  # Chỉ 2 queries để nhanh
                    searched_queries.add(query.lower().strip())  # Track new query
                    results = call_google_search(query, "")
                    counter_evidence.extend(results[:5])
                    if len(counter_evidence) >= 5:
                        break
            
                if not counter_evidence:
                    print(f"[COUNTER-SEARCH] Không tìm thấy dẫn chứng mới")
                else:
                    print(f"[COUNTER-SEARCH] Tìm thấy {len(counter_evidence)} dẫn chứng có thể ủng hộ claim")
                    
                    # Tạo evidence bundle mới với counter-evidence
                    counter_bundle = {
                        "layer_1_tools": evidence_bundle.get("layer_1_tools", []),
                        "layer_2_high_trust": counter_evidence[:5],
                        "layer_3_general": evidence_bundle.get("layer_3_general", []),
                        "layer_4_social_low": []
                    }
                    counter_evidence_json = json.dumps(_trim_evidence_bundle(counter_bundle, claim_text=text_input), indent=2, ensure_ascii=False)
                    
                    # JUDGE Round 1.5: Xem xét lại với dẫn chứng mới
                    print(f"[JUDGE] Round 1.5: Xem xét lại với dẫn chứng mới...")
                    
                    counter_prompt = SYNTHESIS_PROMPT.replace("{text_input}", text_input)
                    counter_prompt = counter_prompt.replace("{evidence_bundle_json}", counter_evidence_json)
                    counter_prompt = counter_prompt.replace("{current_date}", current_date)
                    counter_prompt += f"""

[COUNTER-SEARCH EVIDENCE - QUAN TRỌNG]
Đã tìm thêm dẫn chứng từ nguồn tin chính thống. Hãy xem xét lại kết luận.

[NGUYÊN TẮC BẮT BUỘC - ANTI-HALLUCINATION]
1. BẠN BẮT BUỘC phải dựa vào evidence trong bundle, KHÔNG ĐƯỢC tự suy diễn
2. Nếu evidence mới XÁC NHẬN claim (có nguồn uy tín đưa tin) → BẮT BUỘC TIN THẬT
3. "Không tìm thấy evidence" ≠ TIN GIẢ (Innocent until proven guilty)
4. CHỈ kết luận TIN GIẢ nếu có bằng chứng BÁC BỎ TRỰC TIẾP claim
5. Tin quốc tế có thể được Reuters/AP/BBC đưa tin trước báo VN

[CRITIC FEEDBACK TRƯỚC ĐÓ]
{critic_report}
"""
                    
                    counter_text = await call_agent_with_capability_fallback(
                        role="JUDGE",
                        prompt=counter_prompt,
                        temperature=0.1,
                        timeout=25.0
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
    # =========================================================================
    # PHASE 3: UNIFIED RE-SEARCH & CORRECTION
    # =========================================================================
    # SPEED & ACCURACY OPTIMIZATION: Gộp Counter-Search và Self-Correction.
    # Kích hoạt Re-search nếu:
    # 1. JUDGE Round 1 kết luận TIN GIẢ (Tìm dẫn chứng BẢO VỆ)
    # 2. Hoặc JUDGE yêu cầu explicit (needs_more_evidence = True)
    # 3. Hoặc Confidence rất thấp (< 40%)
    # 4. HOẶC Có sự mâu thuẫn lớn giữa CRITIC và JUDGE (Adversarial Mismatch)
    
    conclusion_r1 = normalize_conclusion(judge_result.get("conclusion", ""))
    confidence_r1 = 50
    try:
        conf_val = judge_result.get("confidence_score")
        if conf_val is not None:
            confidence_r1 = int(conf_val)
    except:
        pass
        
    needs_more_r1 = judge_result.get("needs_more_evidence", False)
    if not isinstance(needs_more_r1, bool):
        needs_more_r1 = str(needs_more_r1).lower() == "true"
        
    critic_conclusion = critic_parsed.get("conclusion", {})
    critic_found_issues = critic_conclusion.get("issues_found", False) if isinstance(critic_conclusion, dict) else False
    # Mẫu thuẫn: CRITIC bảo OK nhưng JUDGE bảo SAI, hoặc ngược lại
    adversarial_mismatch = (critic_found_issues and conclusion_r1 == "TIN THẬT") or (not critic_found_issues and conclusion_r1 == "TIN GIẢ")
    
    is_weather = "thời tiết" in judge_result.get("claim_type", "").lower()
    
    # =========================================================================
    # LATENCY OPTIMIZATION: Skip Round 2 if confidence > 85%
    # High confidence means JUDGE is already sure, no need for re-search
    # =========================================================================
    high_confidence_skip = confidence_r1 >= 85
    if high_confidence_skip:
        print(f"[LATENCY-SKIP] Confidence {confidence_r1}% >= 85%, skipping re-search phase")
    
    should_unified_research = (
        ENABLE_SELF_CORRECTION and 
        not high_confidence_skip and (  # NEW: Skip if high confidence
            (conclusion_r1 == "TIN GIẢ" and ENABLE_COUNTER_SEARCH) # Phase 2.5 logic
            or needs_more_r1 # Phase 3 logic
            or confidence_r1 < 40 # Phase 3 logic
            or adversarial_mismatch # New logic
        ) and not is_weather
    )
    
    if should_unified_research:
        print(f"\n[UNIFIED-RE-SEARCH] Kích hoạt (REASON: {'TIN GIẢ' if conclusion_r1 == 'TIN GIẢ' else 'Needs More' if needs_more_r1 else 'Low Conf' if confidence_r1 < 40 else 'Adversarial Mismatch'})")
        
        # Thu thập tất cả queries tiềm năng
        unified_queries = []
        
        # 1. Queries từ JUDGE
        unified_queries.extend(judge_result.get("additional_search_queries", []))
        unified_queries.extend(judge_result.get("verification_search_queries", []))
        
        # 2. Nếu là TIN GIẢ, thêm các queries mang tính "bảo vệ" (Support Search)
        if conclusion_r1 == "TIN GIẢ":
            # IMPROVED: Multi-language support
            from app.search import _is_international_event, _extract_english_query
            
            unified_queries.append(f"{text_input} tin tức chính thống")
            
            if _is_international_event(text_input):
                en_text = _extract_english_query(text_input)
                if en_text and len(en_text) > 10:
                    unified_queries.append(f"{en_text} confirmed Reuters AP")
                    unified_queries.append(f"{en_text} official news")
            else:
                unified_queries.append(f"{text_input} official news")
            
        # 3. Fallback queries
        if not unified_queries:
            unified_queries = [f"{text_input} fact check", f"{text_input} news"]
            
        # Unique and limit queries (giới hạn 3 queries để nhanh)
        unique_queries = []
        for q in unified_queries:
            if q and q not in unique_queries:
                unique_queries.append(q)
        unique_queries = unique_queries[:3]
        
        print(f"[UNIFIED-RE-SEARCH] Queries: {unique_queries}")
        
        try:
            # Execute search
            re_search_plan = {
                "required_tools": [{
                    "tool_name": "search",
                    "parameters": {"queries": unique_queries}
                }]
            }
            new_evidence = await execute_tool_plan(re_search_plan, site_query_string, flash_mode)
            
            # Merge evidence (safe initialization)
            for layer in ["layer_2_high_trust", "layer_3_general", "layer_4_social_low"]:
                if layer not in evidence_bundle: evidence_bundle[layer] = []
                evidence_bundle[layer].extend(new_evidence.get(layer, []))
            
            # Remove duplicates by URL
            seen_urls = {item.get("url") or item.get("link") for item in (evidence_bundle.get("layer_2_high_trust") or [])}
            # Trim evidence
            trimmed_bundle_v2 = _trim_evidence_bundle(evidence_bundle, claim_text=text_input)
            evidence_bundle_json_v2 = json.dumps(trimmed_bundle_v2, indent=2, ensure_ascii=False)
            
            # Re-Run JUDGE Round 2
            print(f"\n[JUDGE] Bắt đầu phán quyết Round 2 (Final)...")
            judge_prompt_v2 = SYNTHESIS_PROMPT.replace("{text_input}", text_input)
            judge_prompt_v2 = judge_prompt_v2.replace("{evidence_bundle_json}", evidence_bundle_json_v2)
            judge_prompt_v2 = judge_prompt_v2.replace("{current_date}", current_date)
            judge_prompt_v2 += f"\n\n[Ý KIẾN CRITIC & KẾT QUẢ R1]:\nCRITIC: {critic_report}\nR1 CONCLUSION: {conclusion_r1} ({confidence_r1}%)\n\n[INSTRUCTION]: Hãy xem xét bằng chứng mới được cập nhật để đưa ra kết luận cuối cùng chính xác nhất."
            
            judge_result_r1_backup = judge_result.copy()
            
            judge_text_v2 = await call_agent_with_capability_fallback(
                role="JUDGE",
                prompt=judge_prompt_v2,
                temperature=0.1,
                timeout=80.0
            )
            
            judge_result_r2 = _parse_json_from_text(judge_text_v2)
            
            # Adapter Round 2
            verdict_meta_v2 = judge_result_r2.get("verdict_metadata")
            if verdict_meta_v2:
                judge_result_r2["conclusion"] = verdict_meta_v2.get("conclusion")
                judge_result_r2["confidence_score"] = verdict_meta_v2.get("probability_score")
                
                exec_summary = judge_result_r2.get("executive_summary") or {}
                dialectical = judge_result_r2.get("dialectical_analysis") or {}
                synthesis = dialectical.get("synthesis") or exec_summary.get("bluf")
                
                combined_reason = ""
                citations = judge_result_r2.get("key_evidence_citations") or []
                if citations:
                    cite = citations[0]
                    combined_reason = f"Cập nhật bằng chứng mới từ {cite.get('source')}: \"{cite.get('quote', '')[:100]}...\". "
                
                judge_result_r2["reason"] = (combined_reason + (synthesis or "")).strip()

            else:
                # Fallback flat schema R2
                if not judge_result_r2.get("conclusion"):
                    judge_result_r2["conclusion"] = judge_result_r2.get("final_conclusion") or judge_result_r2.get("verdict")
                if not judge_result_r2.get("reason"):
                    judge_result_r2["reason"] = judge_result_r2.get("reasoning") or judge_result_r2.get("explanation")
            
            # Cập nhật kết quả nếu R2 hợp lệ
            if judge_result_r2.get("conclusion"):
                judge_result = judge_result_r2
                judge_result["cached"] = False
                print(f"[JUDGE] Round 2 Success: {judge_result.get('conclusion')} ({judge_result.get('confidence_score')}%)")
            else:
                print("[JUDGE] Round 2 failed or invalid, keeping Round 1 results.")
                judge_result = judge_result_r1_backup
                
        except Exception as e:
            print(f"[UNIFIED-RE-SEARCH] Error: {e}")
            judge_result = judge_result_r1_backup
    else:
        print("[SELF-CORRECTION] Không kích hoạt các vòng phụ (Fast Lane).")

    # =========================================================================
    # POST-PROCESSING: TRUSTED SOURCE OVERRIDE (Reduce False Positive Rate)
    # =========================================================================
    # If claim has trusted source prefix (AP, Reuters, BBC, VnExpress) and 
    # JUDGE returned TIN GIẢ but no strong contradiction found → Override to TIN THẬT
    
    if judge_result and _has_trusted_source_citation(text_input):
        current_conclusion = normalize_conclusion(judge_result.get("conclusion", ""))
        reason_text = (judge_result.get("reason") or "").lower()
        
        # Check if there's a STRONG contradiction in the reason
        strong_contradiction_keywords = [
            "bác bỏ", "debunked", "sai sự thật", "fake", "hoax", "lừa đảo",
            "không tồn tại", "không xác nhận", "không có thật", "contrary evidence"
        ]
        has_strong_contradiction = any(kw in reason_text for kw in strong_contradiction_keywords)
        
        if current_conclusion == "TIN GIẢ" and not has_strong_contradiction:
            # Extract source name for logging
            source_name = "Trusted Source"
            for prefix in TRUSTED_SOURCE_PREFIXES:
                if text_input.lower().strip().startswith(prefix):
                    source_name = prefix.replace("theo ", "").replace(":", "").replace("đưa tin", "").strip().title()
                    break
            
            print(f"[TRUSTED-SOURCE-OVERRIDE] Claim có nguồn {source_name}, không có phản chứng mạnh → Override TIN GIẢ → TIN THẬT")
            judge_result["conclusion"] = "TIN THẬT"
            judge_result["confidence_score"] = 85  # HIGH confidence for trusted source
            judge_result["reason"] = (
                f"Claim trích dẫn nguồn uy tín ({source_name}). "
                f"Không tìm thấy bằng chứng bác bỏ cụ thể nên ưu tiên TIN THẬT. "
                f"[Gốc: {judge_result.get('reason', '')}]"
            )
        elif current_conclusion == "TIN THẬT":
            # BOOST: If LLM already returned TIN THẬT for trusted source, boost confidence
            current_conf = judge_result.get("confidence_score", 70)
            # Boost by 15% for trusted source, max 90%
            boosted_conf = min(current_conf + 15, 90)
            if boosted_conf > current_conf:
                print(f"[TRUSTED-SOURCE-BOOST] Claim có nguồn uy tín, boost confidence {current_conf}% → {boosted_conf}%")
                judge_result["confidence_score"] = boosted_conf
    
    # Post-processing normalization
    if judge_result:
        # Map old schema keys if needed (fallback)
        if "final_conclusion" in judge_result and "conclusion" not in judge_result:
            judge_result["conclusion"] = judge_result["final_conclusion"]
            
        judge_result["conclusion"] = normalize_conclusion(judge_result.get("conclusion"))
        
        # =========================================================================
        # FIX: Ensure evidence_link is populated from evidence bundle
        # =========================================================================
        if not judge_result.get("evidence_link"):
            # Extract first evidence URL from bundle
            for layer in ["layer_2_high_trust", "layer_3_general", "layer_1_tools", "layer_4_social_low"]:
                items = evidence_bundle.get(layer, [])
                for item in items:
                    url = item.get("url") or item.get("link")
                    if url:
                        judge_result["evidence_link"] = url
                        break
                if judge_result.get("evidence_link"):
                    break
        
        return judge_result

    # Fallback final
    return _heuristic_summarize(text_input, evidence_bundle, current_date)

