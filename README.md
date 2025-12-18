# ZeroFake v1.1

Real-time fake news detection and verification system, prioritizing trusted sources and global weather API data.

---

## 1) Objective
ZeroFake helps quickly verify whether a news article/post is: "TIN THẬT" (TRUE NEWS) | "TIN GIẢ" (FAKE NEWS) | "GÂY HIỂU LẦM" (MISLEADING). The system operates fully API-Native, requiring no local training.

## 2) Architecture Overview
- **Frontend**: PyQt6 GUI (Dark Mode), non-blocking with QThread
- **Backend**: FastAPI (Python), asynchronous pipeline
- **Integrated Services**:
  - DuckDuckGo Search (web search for news articles with enhanced query logic)
  - AI Agent System (multi-agent architecture for planning and synthesis)
  - OpenWeatherMap API (global weather: current + forecast, with global geocoding)
- **AI Models**:
  - **Agent 1 (Planner)**: Gemini Flash, Gemma 3 (1B, 4B) with automatic fallback
  - **Agent 2 (Synthesizer)**: Gemini Pro, Gemini Flash, Gemma 3 (4B, 12B, 27B) with automatic fallback
  - All models use Google AI Studio (Gemini API)
- **Storage/Learning**:
  - KB Cache: SQLite + FAISS (remembers verified results)
  - Feedback loop: SQLite + FAISS (Relevant Retrieval: automatically retrieves similar error examples for prompts)

## 3) Workflow
1. GUI sends news text to FastAPI for verification
2. Backend checks KB Cache (FAISS) – if found, returns immediately
3. **Agent 1 (Planner)**: Analyzes input and creates execution plan:
   - Classifies claim type (Politics, Economy, Health, Weather, Sports, etc.)
   - Identifies entities (locations, persons, organizations)
   - Determines time scope (present/future/historical)
   - Generates diverse search queries (original input + enriched queries)
   - Selects appropriate tools (weather API, web search)
   - **Automatic Fallback**: If selected model fails, automatically tries: Gemini Flash → Gemma 3-4B → Gemma 3-1B
4. **Tool Executor**: Executes planned tools:
   - Weather claims: Calls OpenWeather API for current/forecast data
   - Other claims: Performs DuckDuckGo web search with enhanced query logic
   - Prioritizes trusted domains (official sources, mainstream news)
   - Removes tool results if web search finds evidence
5. **Agent 2 (Synthesizer)**: Analyzes evidence and generates final conclusion:
   - Compares input with collected evidence
   - Applies verification rules (including temporal misleading detection)
   - Can request additional search queries if evidence is insufficient
   - Returns conclusion with reasoning
   - **Automatic Fallback**: If selected model fails, automatically tries: Gemini Pro → Gemini Flash → Gemma 3-27B → Gemma 3-12B → Gemma 3-4B
6. Results are saved to KB Cache (background) and returned to GUI
7. Users can provide feedback; system logs and learns from errors

## 4) Installation & Running
### Requirements
- Python 3.10+ (recommended 3.11/3.12/3.13)

### Installation
```bash
pip install -r requirements.txt
```

### API Keys Configuration (.env)
Create a `.env` file in the root directory:
```
GEMINI_API_KEY=...                  # Google AI Studio API key (required for Gemini & Gemma models)
OPENWEATHER_API_KEY=...             # OpenWeather API Key (required for weather verification)
```
**Note**: All AI models (Gemini Flash, Gemini Pro, Gemma 3) use the same `GEMINI_API_KEY` from Google AI Studio.

### Running the Application
- **Windows**: Double-click `run_app.bat` (launches both server and GUI)
- **Or manually**:
  ```bash
  # Terminal 1: Start server
  python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
  
  # Terminal 2: Start GUI
  python gui/main_gui.py
  ```
- **Health check**: http://127.0.0.1:8000/
- **API docs**: http://127.0.0.1:8000/docs

## 5) Directory Structure (simplified)
```
app/
  __init__.py
  main.py              # FastAPI orchestrator
  agent_planner.py     # Agent 1: Planning agent with fallback
  agent_synthesizer.py # Agent 2: Synthesis agent with fallback
  tool_executor.py     # Tool execution engine
  model_clients.py     # Model client utilities (Gemini, etc.)
  kb.py                # KB Cache (SQLite + FAISS)
  search.py            # DuckDuckGo search with enhanced queries
  ranker.py            # Source ranker
  weather.py           # Geocoding + weather current/forecast (global)
  feedback.py          # Feedback loop (Relevant Retrieval)
  trusted_domains.json # Trusted domain tiers (tier0, tier1)
prompts/
  planner_prompt.txt   # Prompt for Agent 1
  synthesis_prompt.txt # Prompt for Agent 2
  critic_prompt.txt    # Prompt for CRITIC agent
tools/
  tool_executor.py     # Tool execution utilities (copy)
scripts_bat/
  run_server.bat       # Start backend server
  run_gui.bat          # Start GUI
  run_evaluation.bat   # Run evaluation
scripts/
  ow_cli.py            # OpenWeather CLI utility
gui/main_gui.py        # PyQt6 GUI (Dark Mode)
evaluation/
  run_evaluation.py    # Evaluation script
  dataset_1200.json    # Test dataset
```

## 6) Key Features
- **Multi-Agent Architecture**: Two-agent system for planning and synthesis
- **Automatic Model Fallback**: Robust fallback mechanism ensures system continues working even if a model fails
- **Model Selection**: 
  - Agent 1: Gemini Flash, Gemma 3 (1B, 4B)
  - Agent 2: Gemini Pro, Gemini Flash, Gemma 3 (4B, 12B, 27B)
- **Trusted Source Prioritization**: System prioritizes official and mainstream sources using tiered domain classification
- **Enhanced Search Logic**: 
  - Multiple query variants (original + enriched queries)
  - Enhanced DuckDuckGo queries with fallback mechanisms
  - Prioritizes recent and trusted sources
- **Temporal Misleading Detection**: Identifies outdated but factually correct information as "GÂY HIỂU LẦM"
- **Global Weather Support**: OpenWeatherMap API with geocoding for worldwide locations
- **Intelligent Caching**: FAISS-based knowledge base for fast retrieval
- **Feedback Learning**: System learns from user corrections
- **Comprehensive Claim Types**: Supports 11+ news categories (Politics, Economy, Health, Weather, Sports, etc.)
- **Bilingual Input**: Supports both English and Vietnamese input
- **Testing Framework**: Automated test data generation and batch testing scripts

## 7) Testing
The system includes automated testing tools:
- **Test Data Generation**: `test/generate_test_data.py` - Generates 1000 test samples using LLM
- **Batch Testing**: `test/run_batch_test.py` - Runs batch tests and calculates metrics (ACC, F1, FNR, FPR, Confusion Matrix)

Run tests:
```bash
# Generate test data
python test/generate_test_data.py

# Run batch tests (ensure server is running)
python test/run_batch_test.py
```

---

Author: Nguyễn Nhật Minh
