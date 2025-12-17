# app/main.py (Restructured with Agent Architecture)

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import traceback
import logging
import signal
import sys
import os
from dotenv import load_dotenv
import datetime
import json
from urllib.parse import urlparse

# Setup logging - suppress CancelledError and KeyboardInterrupt during shutdown
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress CancelledError and KeyboardInterrupt in asyncio
import warnings
warnings.filterwarnings('ignore', category=RuntimeWarning, message='.*CancelledError.*')

# Import base modules
from app.kb import init_kb, search_knowledge_base, add_to_knowledge_base
from app.search import get_site_query
from app.ranker import load_ranker_config
from app.feedback import init_feedback_db, log_human_feedback

# --- Import NEW Agents ---
from app.agent_planner import load_planner_prompt, create_action_plan
from app.tool_executor import execute_tool_plan, enrich_plan_with_evidence
from app.agent_synthesizer import load_synthesis_prompt, execute_final_analysis
# ------------------------------

# (MODIFIED) Only import detection function
from app.weather import extract_weather_info

app = FastAPI(title="ZeroFake v1.1 - Agent Architecture (DDG Search-Only)")

# CORS middleware (Keep as is)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variable
SITE_QUERY_STRING = "" # (MODIFIED) Will be set to "" (empty)


def _sanitize_check_response(obj: dict) -> dict:
    """Ensure CheckResponse fields are strings, avoid None causing Pydantic errors."""
    if obj is None:
        obj = {}
    for k in ["conclusion", "reason", "style_analysis", "key_evidence_snippet", "key_evidence_source", "evidence_link"]:
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


def _convert_planner_findings_to_evidence(findings: list[dict]) -> list[dict]:
    """Convert Agent 1 browse findings into L2 evidence items."""
    converted = []
    if not isinstance(findings, list):
        return converted
    seen_urls = set()
    today = datetime.date.today()

    for item in findings:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        source = item.get("source")
        if not source:
            domain = urlparse(url).netloc.replace("www.", "")
            source = domain or "unknown"

        summary = item.get("summary") or item.get("title") or ""
        if not summary:
            continue

        date_str = item.get("published_date")
        parsed_date = None
        is_old = False
        if date_str:
            try:
                parsed_date = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
                item_date = datetime.datetime.strptime(parsed_date, "%Y-%m-%d").date()
                if (today - item_date).days > 365:
                    is_old = True
            except Exception:
                parsed_date = None

        confidence = (item.get("confidence") or "").lower()
        rank_score = 0.9
        if confidence == "medium":
            rank_score = 0.8
        elif confidence == "low":
            rank_score = 0.7

        converted.append({
            "source": source,
            "url": url,
            "snippet": summary,
            "rank_score": rank_score,
            "date": parsed_date,
            "is_old": is_old,
            "origin": "planner_browse",
        })

    return converted


def _merge_planner_findings_into_bundle(evidence_bundle: dict, planner_findings: list[dict]) -> dict:
    """Inject Agent 1 browse findings into the evidence bundle before Agent 2."""
    if not planner_findings:
        return evidence_bundle

    evidence_bundle = evidence_bundle or {
        "layer_1_tools": [],
        "layer_2_high_trust": [],
        "layer_3_general": [],
        "layer_4_social_low": [],
    }

    converted = _convert_planner_findings_to_evidence(planner_findings)
    if not converted:
        return evidence_bundle

    existing_urls = {
        item.get("url")
        for item in (evidence_bundle.get("layer_2_high_trust") or [])
    }

    new_items = []
    for item in converted:
        if item["url"] in existing_urls:
            continue
        existing_urls.add(item["url"])
        new_items.append(item)

    if new_items:
        evidence_bundle.setdefault("layer_2_high_trust", [])
        evidence_bundle["layer_2_high_trust"] = new_items + evidence_bundle["layer_2_high_trust"]
        logger.info(f"Planner browse findings injected: {len(new_items)} item(s).")

    return evidence_bundle


@app.on_event("startup")
async def startup_event():
    """Initialize modules when server starts"""
    global SITE_QUERY_STRING
    
    load_dotenv()
    
    # Initialize base modules
    init_kb()
    init_feedback_db()
    load_ranker_config()
    
    # --- Load prompts for Agents ---
    load_planner_prompt("planner_prompt.txt")
    load_synthesis_prompt("synthesis_prompt.txt")
    # ---------------------------------
    
    try:
        # (MODIFIED) Get site query (will be empty to search entire web)
        SITE_QUERY_STRING = get_site_query("config.json")
    except Exception as e:
        logger.warning(f"Could not create site query string: {e}")
        SITE_QUERY_STRING = ""  # Fallback
    
    print(f"ZeroFake v1.1 (Agent, DDG Search-Only) is ready! Site Query: '[{SITE_QUERY_STRING}]'")


@app.on_event("shutdown")
async def shutdown_event():
    """Handle graceful shutdown"""
    try:
        logger.info("Server is shutting down gracefully...")
        # Can add cleanup code here if needed
    except (asyncio.CancelledError, KeyboardInterrupt):
        # Ignore CancelledError and KeyboardInterrupt during shutdown - this is normal behavior
        pass
    except Exception as e:
        logger.warning(f"Error in shutdown event: {e}")


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    if os.name == "nt":
        logger.info("Signal handlers are skipped on Windows (managed by Uvicorn).")
        return

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        try:
            loop = asyncio.get_event_loop()
            loop.stop()
        except RuntimeError:
            sys.exit(0)
    
    # Only setup on Unix-like systems (Windows doesn't support signal.SIGTERM)
    if hasattr(signal, 'SIGTERM'):
        try:
            signal.signal(signal.SIGTERM, signal_handler)
        except (ValueError, OSError):
            # Signal handler may not work in some environments
            pass
    if hasattr(signal, 'SIGINT'):
        try:
            signal.signal(signal.SIGINT, signal_handler)
        except (ValueError, OSError):
            # Signal handler may not work in some environments
            pass


# Setup signal handlers when module is imported
try:
    setup_signal_handlers()
except Exception:
    # Ignore if cannot setup signal handlers
    pass


# Pydantic Models (Keep as is)
class CheckRequest(BaseModel):
    text: str
    flash_mode: bool = False
    agent1_model: str | None = None
    agent2_model: str | None = None


class CheckResponse(BaseModel):
    conclusion: str
    reason: str
    style_analysis: str
    key_evidence_snippet: str
    key_evidence_source: str
    evidence_link: str = ""
    cached: bool = False


class FeedbackRequest(BaseModel):
    original_text: str
    gemini_conclusion: str
    gemini_reason: str
    human_correction: str
    notes: str = ""


# (MODIFIED) GUI helper: Only extract location name
class ExtractLocationRequest(BaseModel):
    text: str

class ExtractLocationResponse(BaseModel):
    city: str | None
    # (REMOVED) country, lat, lon, canonical
    success: bool


@app.post("/extract_location", response_model=ExtractLocationResponse)
async def extract_location_endpoint(request: ExtractLocationRequest):
    """
    (MODIFIED) This endpoint only returns location NAME (if detected)
    """
    try:
        info = await asyncio.to_thread(extract_weather_info, request.text)
        if not info or not info.get("city"):
            return ExtractLocationResponse(city=None, success=False)
        city = info.get("city")
        return ExtractLocationResponse(city=city, success=True)
    except Exception as e:
        logger.warning(f"extract_location error: {e}")
        return ExtractLocationResponse(city=None, success=False)


def _is_flash_model(model_name: str | None) -> bool:
    if not model_name:
        return False
    normalized = model_name.lower()
    return "gemini" in normalized and "flash" in normalized


@app.post("/check_news", response_model=CheckResponse)
async def handle_check_news(request: CheckRequest, background_tasks: BackgroundTasks):
    """
    Main endpoint (Agent Workflow):
    Input -> Agent 1 (learnlm Planner) creates plan
    -> Tool Executor (DuckDuckGo search) -> Agent 2 (learnlm Synthesizer) synthesizes.
    Overall timeout: 100 seconds (unless flash mode is enabled).
    """
    agent1_model = request.agent1_model or "models/gemini-2.5-flash"
    agent2_model = request.agent2_model or "models/gemini-2.5-flash"

    flash_mode = request.flash_mode or (_is_flash_model(agent1_model) and _is_flash_model(agent2_model))

    if flash_mode:
        return await _handle_check_news_internal(
            request,
            background_tasks,
            agent1_model=agent1_model,
            agent2_model=agent2_model,
            flash_mode=flash_mode,
        )
    try:
        return await asyncio.wait_for(
            _handle_check_news_internal(
                request,
                background_tasks,
                agent1_model=agent1_model,
                agent2_model=agent2_model,
                flash_mode=flash_mode,
            ),
            timeout=100.0,
        )
    except asyncio.TimeoutError:
        logger.error("Overall timeout when processing check_news")
        raise HTTPException(status_code=504, detail="Request timeout - system response too slow")


async def _handle_check_news_internal(
    request: CheckRequest,
    background_tasks: BackgroundTasks,
    *,
    agent1_model: str,
    agent2_model: str,
    flash_mode: bool,
):
    """Internal handler for check_news"""
    try:
        # Step 1: Check KB Cache (Keep as is)
        logger.info("Checking KB cache...")
        cached_result = await asyncio.to_thread(search_knowledge_base, request.text)
        if cached_result:
            logger.info("Found in cache!")
            return CheckResponse(**_sanitize_check_response(cached_result))
        
        # Step 2: Agent 1 (Planner) creates plan
        logger.info("Agent 1 (Planner) is creating plan...")
        plan = await create_action_plan(
            request.text,
            model_key=agent1_model,
            flash_mode=flash_mode,
        )
        logger.info(f"Plan: {json.dumps(plan, ensure_ascii=False, indent=2)}")
        planner_findings = plan.get("browse_findings") if isinstance(plan.get("browse_findings"), list) else []
        if planner_findings:
            logger.info(f"Planner provided {len(planner_findings)} browse finding(s) via Gemini Flash.")
        
        # Step 3: Collect evidence (always run DDG search)
        logger.info("Tool Executor (DDG Search) is collecting evidence...")
        evidence_bundle = await execute_tool_plan(plan, SITE_QUERY_STRING, flash_mode=flash_mode)
        evidence_bundle = _merge_planner_findings_into_bundle(evidence_bundle, planner_findings)

        # Enrich plan with collected evidence
        enriched_plan = enrich_plan_with_evidence(plan, evidence_bundle)
        logger.info(f"Plan (enriched): {json.dumps(enriched_plan, ensure_ascii=False, indent=2)}")
        
        # Step 4: Agent 2 (Synthesizer) makes judgment
        logger.info("Agent 2 (Synthesizer) is synthesizing...")
        current_date = datetime.datetime.now().strftime('%Y-%m-%d')
        gemini_result = await execute_final_analysis(
            request.text,
            evidence_bundle,
            current_date,
            model_key=agent2_model,
            flash_mode=flash_mode,
        )
        gemini_result = _sanitize_check_response(gemini_result)
        logger.info(f"Agent 2 result: {gemini_result.get('conclusion', 'N/A')}")
        
        # Step 5: Conditionally update KB (Keep as is)
        plan_volatility = plan.get('volatility', 'medium')
        if gemini_result.get("conclusion") and plan_volatility in ['static', 'low']:
            logger.info(f"Saving result (Volatility: {plan_volatility}) to KB...")
            try:
                background_tasks.add_task(add_to_knowledge_base, request.text, gemini_result)
            except Exception as e:
                logger.warning(f"KB update error (not critical): {str(e)}")
        else:
            logger.info(f"Skipping KB save (Volatility: {plan_volatility}). This news changes quickly.")
        
        return CheckResponse(**gemini_result)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unknown error in handle_check_news: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Unknown error: {str(e)}")


# Endpoint /feedback and / (Keep as is)
@app.post("/feedback")
async def handle_feedback(request: FeedbackRequest):
    """
    Endpoint: Record feedback from user
    """
    await asyncio.to_thread(
        log_human_feedback,
        request.original_text,
        request.gemini_conclusion,
        request.gemini_reason,
        request.human_correction,
        request.notes
    )
    return {"status": "success", "message": "Feedback recorded"}


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "version": "1.1-Agent (DDG Search-Only)",
        "name": "ZeroFake"
    }
