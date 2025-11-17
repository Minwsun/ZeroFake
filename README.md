# ZeroFake v1.1

Real-time fake news detection and verification system, prioritizing trusted sources and global weather API data.

---

## 1) Objective
ZeroFake helps quickly verify whether a news article/post is: "TIN THẬT" (TRUE NEWS) | "TIN GIẢ" (FAKE NEWS) | "GÂY HIỂU LẦM" (MISLEADING). The system operates fully API-Native, requiring no local training.

## 2) Architecture Overview
- **Frontend**: PyQt6 GUI (Dark Mode), non-blocking with QThread
- **Backend**: FastAPI (Python), asynchronous pipeline
- **Integrated Services**:
  - DuckDuckGo Search (web search for news articles)
  - AI Agent System (multi-agent architecture for planning and synthesis)
  - OpenWeatherMap API (global weather: current + forecast, with global geocoding)
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
   - Selects appropriate tools (weather API, web search)
4. **Tool Executor**: Executes planned tools:
   - Weather claims: Calls OpenWeather API for current/forecast data
   - Other claims: Performs DuckDuckGo web search
5. **Agent 2 (Synthesizer)**: Analyzes evidence and generates final conclusion:
   - Compares input with collected evidence
   - Applies verification rules
   - Returns conclusion with reasoning
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
GEMINI_API_KEY=...                  # Gemini models (Agents 1 & 2)
OPENROUTER_API_KEY=...              # OpenRouter models (Claude, etc.)
# Optional overrides for OpenRouter metadata
# OPENROUTER_SITE_URL=https://zerofake.local
# OPENROUTER_APP_NAME=ZeroFake Fact Checker
OPENWEATHER_API_KEY=...             # OpenWeather API Key
```

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
  agent_planner.py     # Agent 1: Planning agent
  agent_synthesizer.py # Agent 2: Synthesis agent
  tool_executor.py     # Tool execution engine
  kb.py                # KB Cache (SQLite + FAISS)
  search.py            # DuckDuckGo search
  ranker.py            # Source ranker
  weather.py           # Geocoding + weather current/forecast (global)
  feedback.py          # Feedback loop (Relevant Retrieval)
planner_prompt.txt     # Prompt for Agent 1
synthesis_prompt.txt   # Prompt for Agent 2
config.json            # Source ranker configuration
gui/main_gui.py        # PyQt6 GUI (Dark Mode)
```

## 6) Key Features
- **Multi-Agent Architecture**: Two-agent system for planning and synthesis
- **Global Weather Support**: OpenWeatherMap API with geocoding for worldwide locations
- **Intelligent Caching**: FAISS-based knowledge base for fast retrieval
- **Feedback Learning**: System learns from user corrections
- **Comprehensive Claim Types**: Supports 11+ news categories (Politics, Economy, Health, Weather, Sports, etc.)
- **Bilingual Input**: Supports both English and Vietnamese input

---

Author: Nguyễn Nhật Minh
