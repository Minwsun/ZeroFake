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
    ModelClientError,
    RateLimitError,
)


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
    (ĐÃ SỬA ĐỔI)
    Logic dự phòng khi LLM thất bại, sử dụng Lớp 1 (OpenWeather API) cho tin thời tiết.
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

    # Yêu cầu chặt chẽ: cần >=2 nguồn Lớp 2 đồng thuận để kết luận TIN THẬT
    if len(l2) >= 2:
        top = l2[0]
        return {
            "conclusion": "TIN THẬT",
            "reason": _as_str(f"Heuristic: Có từ 2 nguồn LỚP 2 uy tín gần đây, ví dụ {top.get('source')} ({top.get('date')})."),
            "style_analysis": "",
            "key_evidence_snippet": _as_str(top.get("snippet")),
            "key_evidence_source": _as_str(top.get("source")),
            "evidence_link": _as_str(top.get("url") or top.get("link")),
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
                "conclusion": "GÂY HIỂU LẦM",
                "reason": reason,
                "style_analysis": "",
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
                "conclusion": "GÂY HIỂU LẦM",
                "reason": reason,
                "style_analysis": "",
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
                "conclusion": "GÂY HIỂU LẦM",
                "reason": reason,
                "style_analysis": "",
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
                    "conclusion": "GÂY HIỂU LẦM",
                    "reason": reason,
                    "style_analysis": "",
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
    Gọi Agent 2 để tổng hợp bằng chứng; cắt gọn evidence; dynamic model picking; retry nhẹ; heuristic fallback.
    """
    if not SYNTHESIS_PROMPT:
        raise ValueError("Synthesis prompt (prompt 2) chưa được tải.")

    # Trim evidence before sending
    trimmed_bundle = _trim_evidence_bundle(evidence_bundle)
    evidence_bundle_json = json.dumps(trimmed_bundle, indent=2, ensure_ascii=False)

    # Prompt
    prompt = SYNTHESIS_PROMPT
    prompt = prompt.replace("{evidence_bundle_json}", evidence_bundle_json)
    prompt = prompt.replace("{text_input}", text_input)
    prompt = prompt.replace("{current_date}", current_date)

    model_name = _normalize_agent2_model(model_key)
    
    # Fallback chain for Agent 2: user_model -> gemini flash -> gemma 27B -> gemma 12B
    fallback_chain = [
        model_name,  # Try user's selected model first
        "models/gemini-2.5-flash",
        "models/gemma-3-27b-it",
        "models/gemma-3-12b-it",
    ]
    # Remove duplicates while preserving order
    seen = set()
    fallback_chain = [x for x in fallback_chain if not (x in seen or seen.add(x))]
    
    if not GEMINI_API_KEY:
        raise ModelClientError("GEMINI_API_KEY is not configured.")
    
    text_response = ""
    last_error = None
    
    for fallback_model in fallback_chain:
        try:
            provider = _detect_agent2_provider(fallback_model)
            if provider != "gemini":
                continue  # Skip non-gemini models
            
            print(f"Synthesizer: trying model '{fallback_model}' (provider={provider})")
            timeout = None if flash_mode else 45.0
            text_response = await call_gemini_model(
                fallback_model,
                prompt,
                timeout=timeout,
                safety_settings=SAFETY_SETTINGS,
            )
            
            # If we got text, try to parse it
            result_json = _parse_json_from_text(text_response or "")
            if result_json:
                print(f"Synthesizer: Successfully generated verdict with model '{fallback_model}'")
                break  # Success, exit loop
        except Exception as exc:
            last_error = exc
            print(f"Synthesizer: Error using model '{fallback_model}': {exc}")
            text_response = ""
            continue

    result_json = _parse_json_from_text(text_response or "")
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

                        print(f"Synthesizer: Re-analysis complete with additional evidence (link: {top_link})")
                        return updated_result
                except Exception as e:
                    print(f"Synthesizer: Error during re-analysis: {e}")
                    # Fall through to return original result
        
        # Remove additional_search_queries from final result (internal use only)
        result_json.pop("additional_search_queries", None)
        result_json["cached"] = False

        # (NEW) Extract evidence_link from the best evidence item
        top_link = ""
        if evidence_bundle.get("layer_2_high_trust"):
            top_link = evidence_bundle["layer_2_high_trust"][0].get("url") or ""
        elif evidence_bundle.get("layer_3_general"):
            top_link = evidence_bundle["layer_3_general"][0].get("url") or ""
        result_json["evidence_link"] = top_link

        return result_json

    print("Lỗi khi gọi Agent 2 (Synthesizer): Model response invalid or empty.")
    # (SỬA ĐỔI) Gọi hàm fallback đã được cập nhật
    return _heuristic_summarize(text_input, trimmed_bundle, current_date)
