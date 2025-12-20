# ZeroFake v2.0

Advanced AI-powered Fake News Detection System with Multi-Agent Architecture.

---

## 1) Objective
ZeroFake is a real-time fact-checking system that verifies news claims as: **"TIN THẬT" (TRUE)** or **"TIN GIẢ" (FAKE)**. The system uses a multi-agent cognitive architecture with adversarial debate to ensure accurate verification.

## 2) Architecture Overview

### Core Pipeline
```
INPUT → PLANNER → SEARCH → CRITIC → JUDGE → OUTPUT
```

### Components
- **Frontend**: PyQt6 GUI (Dark Mode), non-blocking with QThread
- **Backend**: FastAPI (Python), fully asynchronous
- **AI Agents**:
  - **PLANNER**: Analyzes claims, generates search queries
  - **CRITIC**: Adversarial agent that challenges evidence
  - **JUDGE**: Final verdict using Bayesian reasoning
- **AI Models**:
  - Groq API: Llama 3.1/3.3 (8B, 70B), Llama Guard
  - Google AI: Gemini Flash, Gemma 3 (4B, 12B, 27B)
  - Cerebras API: Llama 3.1/3.3 (for high-speed inference)
- **Search**: SearXNG (Google-only) with Cloudflare WARP proxy
- **Weather**: OpenWeatherMap API (global coverage)
- **Storage**: SQLite + FAISS (KB Cache + Feedback Learning)

## 3) Key Features

### Multi-Agent Cognitive Architecture
- **Popperian Falsification**: CRITIC attempts to falsify claims
- **Adversarial Dialectic**: Red Team vs Blue Team debate
- **Presumption of Truth**: Claims are true unless proven false
- **Internal Reasoning**: KNOWLEDGE claims can use AI's internal knowledge

### Source Trust System
| Source Type | Trust Score | Status |
|-------------|-------------|--------|
| Government (.gov) | 0.95 | ✅ Trusted |
| Tier 0 (Major News) | 0.95 | ✅ Trusted |
| Tier 1 (Quality News) | 0.90 | ✅ Trusted |
| Education (.edu) | 0.85 | ✅ Trusted |
| Default Sources | 0.55 | ✅ Accepted |
| Social Media | 0.30 | ⚠️ Low Trust |
| Tabloids | 0.10 | ❌ Rejected |

### Claim Classification
- **KNOWLEDGE**: Facts, history, science → Can use internal reasoning
- **NEWS**: Current events, breaking news → Requires external evidence

### Robust Fallback System
- Multi-key API rotation for rate limit handling
- Automatic model fallback (Groq → Gemini → Cerebras)
- 429 error recovery with exponential backoff

## 4) Installation

### Requirements
- Python 3.10+ (recommended 3.11/3.12)

### Setup
```bash
# Clone repository
git clone https://github.com/Minwsun/ZeroFake.git
cd ZeroFake

# Install dependencies
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env with your API keys

# Start SearXNG (required for search)
docker-compose -f docker-compose.searxng.yml up -d
```

### API Keys (.env)
```env
GROQ_API_KEY=...           # Groq API (Llama models)
GEMINI_API_KEY=...         # Google AI (Gemini/Gemma)
OPENWEATHER_API_KEY=...    # Weather verification
SEARXNG_URL=http://localhost:8080  # Self-hosted SearXNG
WARP_ENABLED=false         # Optional: Enable Cloudflare WARP
```

## 5) Running

### Quick Start (Windows)
```bash
# Double-click run_app.bat
# Or use scripts_bat/run_gui.bat
```

### Manual Start
```bash
# Terminal 1: Backend server
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Terminal 2: GUI
python gui/main_gui.py
```

### Endpoints
- Health check: http://127.0.0.1:8000/
- API docs: http://127.0.0.1:8000/docs

## 6) Directory Structure
```
app/
  main.py              # FastAPI server
  agent_planner.py     # PLANNER agent
  agent_synthesizer.py # CRITIC + JUDGE agents
  model_clients.py     # Multi-API model clients
  ranker.py            # Source trust ranking
  search.py            # SearXNG (Google) + WARP proxy
  weather.py           # Weather API integration
  trusted_domains.json # 380+ trusted domains

prompts/
  planner_prompt.txt   # PLANNER instructions
  critic_prompt.txt    # CRITIC adversarial prompt
  synthesis_prompt.txt # JUDGE Bayesian reasoning

gui/
  main_gui.py          # PyQt6 Dark Mode GUI

evaluation/
  test_dataset_1000.json  # 1000 realistic test samples
  run_evaluation.py       # Evaluation script
```

## 7) Evaluation

### Test Dataset
- 500 TRUE news (real events 2024-2025)
- 500 FAKE news (zombie news, fabrication, scams, conspiracy)

### Run Evaluation
```bash
# Ensure server is running first
python evaluation/run_evaluation.py
```

### Metrics
- Accuracy, Precision, Recall, F1 Score
- Confusion Matrix (TIN THẬT vs TIN GIẢ)
- False Positive/Negative Rate

## 8) Recent Updates (v2.0)

### December 2024
- ✅ Removed all guard systems (FAST_CLASSIFIER, CRITIC_GUARD, OUTPUT_GUARD)
- ✅ Added CRITIC agent with adversarial capabilities
- ✅ JUDGE uses Bayesian reasoning with Presumption of Truth
- ✅ KNOWLEDGE vs NEWS claim classification
- ✅ Internal reasoning for KNOWLEDGE claims
- ✅ Expanded trusted sources (380+ domains worldwide)
- ✅ Source ranking: Accept normal sources, reject tabloids/UGC
- ✅ Realistic test dataset (1000 samples)
- ✅ Migrated from DuckDuckGo to SearXNG (Google-only)
- ✅ Cloudflare WARP proxy support for rate limit bypass
- ✅ Self-hosted SearXNG with Docker Compose

---

**Author**: Nguyễn Nhật Minh  
**Repository**: https://github.com/Minwsun/ZeroFake
