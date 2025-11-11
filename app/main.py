# app/main.py (Đã được cấu trúc lại theo kiến trúc Agent)

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import traceback
import logging
from dotenv import load_dotenv
import datetime
import json

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import các module cơ sở
from app.kb import init_kb, search_knowledge_base, add_to_knowledge_base
from app.search import get_site_query
from app.ranker import load_ranker_config
from app.feedback import init_feedback_db, log_human_feedback

# --- Import các Agent MỚI ---
from app.agent_planner import load_planner_prompt, create_action_plan
from app.tool_executor import execute_tool_plan, enrich_plan_with_evidence
from app.agent_synthesizer import load_synthesis_prompt, execute_final_analysis
# ------------------------------

# Weather extraction for GUI
from app.weather import extract_weather_info

app = FastAPI(title="ZeroFake V2.0 - Agent Architecture")

# CORS middleware (Giữ nguyên)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Biến toàn cục
SITE_QUERY_STRING = ""


def _sanitize_check_response(obj: dict) -> dict:
    """Đảm bảo các trường CheckResponse là string, tránh None gây lỗi Pydantic."""
    if obj is None:
        obj = {}
    for k in ["conclusion", "reason", "style_analysis", "key_evidence_snippet", "key_evidence_source"]:
        v = obj.get(k)
        if v is None:
            obj[k] = ""
        elif not isinstance(v, str):
            try:
                obj[k] = str(v)
            except Exception:
                obj[k] = ""
    if "cached" not in obj or obj.get("cached") is None:
        obj["cached"] = False
    return obj


@app.on_event("startup")
async def startup_event():
    """Khởi tạo các module khi server start"""
    global SITE_QUERY_STRING
    
    load_dotenv()
    
    # Khởi tạo các module cơ sở
    init_kb()
    init_feedback_db()
    load_ranker_config()
    
    # --- Tải prompt cho các Agent ---
    load_planner_prompt("planner_prompt.txt")
    load_synthesis_prompt("synthesis_prompt.txt")
    # ---------------------------------
    
    try:
        # Lấy site query từ config
        SITE_QUERY_STRING = get_site_query("config.json")
    except Exception as e:
        logger.warning(f"Không thể tạo site query string: {e}")
        SITE_QUERY_STRING = ""  # Fallback
    
    print("ZeroFake V2.0 (Agent) đã sẵn sàng!")


# Pydantic Models (Giữ nguyên)
class CheckRequest(BaseModel):
    text: str


class CheckResponse(BaseModel):
    conclusion: str
    reason: str
    style_analysis: str
    key_evidence_snippet: str
    key_evidence_source: str
    cached: bool = False


class FeedbackRequest(BaseModel):
    original_text: str
    gemini_conclusion: str
    gemini_reason: str
    human_correction: str
    notes: str = ""


# GUI helper: extract location from text for OpenWeather usage
class ExtractLocationRequest(BaseModel):
    text: str

class ExtractLocationResponse(BaseModel):
    city: str | None
    country: str | None
    lat: float | None
    lon: float | None
    canonical: str | None
    success: bool


@app.post("/extract_location", response_model=ExtractLocationResponse)
async def extract_location_endpoint(request: ExtractLocationRequest):
    try:
        info = await asyncio.to_thread(extract_weather_info, request.text)
        if not info or not info.get("city"):
            return ExtractLocationResponse(city=None, country=None, lat=None, lon=None, canonical=None, success=False)
        city = info.get("city")
        country = info.get("country")
        canonical = f"{city}, {country}" if country else city
        return ExtractLocationResponse(city=city, country=country, lat=info.get("lat"), lon=info.get("lon"), canonical=canonical, success=True)
    except Exception as e:
        logger.warning(f"extract_location error: {e}")
        return ExtractLocationResponse(city=None, country=None, lat=None, lon=None, canonical=None, success=False)


@app.post("/check_news", response_model=CheckResponse)
async def handle_check_news(request: CheckRequest, background_tasks: BackgroundTasks):
    """
    Endpoint chính (Agent Workflow):
    Input -> Agent 1 (Flash) lập kế hoạch + thu thập search (embedded) ->
    (Nếu claim là thời tiết) gọi OpenWeather theo metadata -> Agent 2 (Pro) tổng hợp.
    """
    try:
        # Bước 1: Kiểm tra KB Cache (Giữ nguyên)
        logger.info("Kiểm tra KB cache...")
        cached_result = await asyncio.to_thread(search_knowledge_base, request.text)
        if cached_result:
            logger.info("Tìm thấy trong cache!")
            return CheckResponse(**_sanitize_check_response(cached_result))
        
        # Bước 2: Agent 1 (Planner) tạo kế hoạch (có thể kèm embedded evidence để tiết kiệm request)
        logger.info("Agent 1 (Planner) đang tạo kế hoạch...")
        plan = await create_action_plan(request.text)
        logger.info(f"Kế hoạch: {json.dumps(plan, ensure_ascii=False, indent=2)}")

        # Bước 3: Thu thập bằng chứng
        embedded = plan.get("embedded_evidence") if isinstance(plan, dict) else None
        if embedded and isinstance(embedded, dict):
            logger.info("Dùng embedded_evidence từ Planner (bỏ qua Executor search) để tiết kiệm quota.")
            evidence_bundle = {
                "layer_1_tools": [],
                "layer_2_high_trust": embedded.get("layer_2_high_trust", []) or [],
                "layer_3_general": embedded.get("layer_3_general", []) or [],
                "layer_4_social_low": embedded.get("layer_4_social_low", []) or [],
            }
            # Nếu kế hoạch có module weather, chạy riêng weather và hợp nhất Layer 1
            weather_modules = [m for m in (plan.get("required_tools") or []) if (m or {}).get("tool_name") == "weather"]
            if weather_modules:
                weather_only_plan = {"required_tools": weather_modules}
                logger.info("Thực thi weather theo metadata từ Planner...")
                weather_bundle = await execute_tool_plan(weather_only_plan, SITE_QUERY_STRING)
                if isinstance(weather_bundle, dict):
                    for it in (weather_bundle.get("layer_1_tools") or []):
                        evidence_bundle["layer_1_tools"].append(it)
        else:
            logger.info("Tool Executor đang thu thập bằng chứng...")
            evidence_bundle = await execute_tool_plan(plan, SITE_QUERY_STRING)

        # Enrich kế hoạch với bằng chứng thu được
        enriched_plan = enrich_plan_with_evidence(plan, evidence_bundle)
        logger.info(f"Kế hoạch (đã làm giàu): {json.dumps(enriched_plan, ensure_ascii=False, indent=2)}")
        
        # Bước 4: Agent 2 (Synthesizer) đưa ra phán quyết
        logger.info("Agent 2 (Synthesizer) đang tổng hợp...")
        current_date = datetime.datetime.now().strftime('%Y-%m-%d')
        gemini_result = await execute_final_analysis(request.text, evidence_bundle, current_date)
        gemini_result = _sanitize_check_response(gemini_result)
        logger.info(f"Kết quả Agent 2: {gemini_result.get('conclusion', 'N/A')}")
        
        # Bước 5: Cập nhật KB có điều kiện
        plan_volatility = plan.get('volatility', 'medium')
        if gemini_result.get("conclusion") and plan_volatility in ['static', 'low']:
            logger.info(f"Đang lưu kết quả (Volatility: {plan_volatility}) vào KB...")
            try:
                background_tasks.add_task(add_to_knowledge_base, request.text, gemini_result)
            except Exception as e:
                logger.warning(f"Lỗi cập nhật KB (không nghiêm trọng): {str(e)}")
        else:
            logger.info(f"Bỏ qua lưu KB (Volatility: {plan_volatility}). Tin này thay đổi nhanh.")
        
        return CheckResponse(**gemini_result)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi không xác định trong handle_check_news: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Lỗi không xác định: {str(e)}")


# Endpoint /feedback và / (Giữ nguyên)
@app.post("/feedback")
async def handle_feedback(request: FeedbackRequest):
    """
    Endpoint: Ghi nhận phản hồi từ người dùng
    """
    await asyncio.to_thread(
        log_human_feedback,
        request.original_text,
        request.gemini_conclusion,
        request.gemini_reason,
        request.human_correction,
        request.notes
    )
    return {"status": "success", "message": "Đã ghi nhận phảnhaal"}


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "version": "2.0-Agent",
        "name": "ZeroFake"
    }
