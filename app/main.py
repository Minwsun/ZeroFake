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


@app.post("/check_news", response_model=CheckResponse)
async def handle_check_news(request: CheckRequest, background_tasks: BackgroundTasks):
    """
    Endpoint chính (Agent Workflow):
    Cache -> Agent 1 (Plan) -> Tool Executor (Gather) -> Agent 2 (Synthesize) -> Update Cache (Conditional)
    """
    try:
        # Bước 1: Kiểm tra KB Cache (Giữ nguyên)
        logger.info("Kiểm tra KB cache...")
        cached_result = await asyncio.to_thread(search_knowledge_base, request.text)
        if cached_result:
            logger.info("Tìm thấy trong cache!")
            return CheckResponse(**cached_result)
        
        # --- Bắt đầu Workflow Agent Mới ---
        
        # Bước 2: Agent 1 (Planner) tạo kế hoạch
        logger.info("Agent 1 (Planner) đang tạo kế hoạch...")
        plan = await create_action_plan(request.text)
        logger.info(f"Kế hoạch: {json.dumps(plan, ensure_ascii=False, indent=2)}")

        # Bước 3: Tool Executor thi hành kế hoạch
        logger.info("Tool Executor đang thu thập bằng chứng...")
        evidence_bundle = await execute_tool_plan(plan, SITE_QUERY_STRING)

        # Làm giàu kế hoạch từ Gói Bằng Chứng theo ưu tiên Lớp 1 -> 2 -> 3
        enriched_plan = enrich_plan_with_evidence(plan, evidence_bundle)
        logger.info(f"Kế hoạch (đã làm giàu): {json.dumps(enriched_plan, ensure_ascii=False, indent=2)}")
        
        # Bước 4: Agent 2 (Synthesizer) đưa ra phán quyết
        logger.info("Agent 2 (Synthesizer) đang tổng hợp...")
        current_date = datetime.datetime.now().strftime('%Y-%m-%d')
        gemini_result = await execute_final_analysis(request.text, evidence_bundle, current_date)
        logger.info(f"Kết quả Agent 2: {gemini_result.get('conclusion', 'N/A')}")
        
        # --- Bước 5: Cập nhật KB có điều kiện (THEO YÊU CẦU) ---
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
