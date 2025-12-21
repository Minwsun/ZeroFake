# ZeroFake v2.1

**Advanced AI-powered Fake News Detection System with Dual Flow Architecture**

---

## Objective

ZeroFake is a real-time fact-checking system that verifies news claims as:
- **TIN THAT** (TRUE NEWS)
- **TIN GIA** (FAKE NEWS)

The system uses a multi-agent cognitive architecture with:
- **Dual Flow Routing** (Recent News vs Old Info)
- **Google Fact Check API** integration
- **Adversarial CRITIC-JUDGE debate**
- **Presumption of Truth** principle

---

## Architecture

### System Flow Diagram

```
                         ┌─────────────────┐
                         │   INPUT CLAIM   │
                         └────────┬────────┘
                                  ▼
                         ┌─────────────────┐
                         │    PLANNER      │
                         │ (Generate 5+    │
                         │  search queries)│
                         └────────┬────────┘
                                  ▼
                    ┌─────────────────────────┐
                    │       Info Age?         │
                    └─────────────┬───────────┘
                                  │
            ┌─────────────────────┴─────────────────────┐
            ▼                                           ▼
    ┌───────────────┐                         ┌───────────────┐
    │  RECENT NEWS  │                         │   OLD INFO    │
    │   (≤3 days)   │                         │   (>3 days)   │
    └───────┬───────┘                         └───────┬───────┘
            │                                         │
            ▼                                         ▼
    ┌───────────────┐                         ┌───────────────┐
    │    SEARCH     │                         │  FACT CHECK   │
    │  (DDG News)   │                         │     API       │
    └───────┬───────┘                         └───────┬───────┘
            │                                         │
            ▼                               ┌─────────┴─────────┐
    ┌───────────────┐                       ▼                   ▼
    │    CRITIC     │               ┌─────────────┐     ┌─────────────┐
    │  (Adversarial)│               │ Has Result  │     │  No Result  │
    └───────┬───────┘               │   ≥70%      │     │             │
            │                       └──────┬──────┘     └──────┬──────┘
            │                              │                   │
            │                              │ Skip Search       │
            │                              │ Skip CRITIC       ▼
            │                              │            ┌─────────────┐
            │                              │            │   SEARCH    │
            │                              │            └──────┬──────┘
            │                              │                   ▼
            │                              │            ┌─────────────┐
            │                              │            │   CRITIC    │
            │                              │            └──────┬──────┘
            │                              │                   │
            └──────────────────────────────┴───────────────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │     JUDGE       │
                         │ (Final Verdict) │
                         └────────┬────────┘
                                  ▼
                         ┌─────────────────┐
                         │     OUTPUT      │
                         │ TIN THAT/TIN GIA│
                         └─────────────────┘
```

---

## API Keys Required

All API keys are configured in `.env` file:

```env
# ============================================
# REQUIRED APIs
# ============================================

# Google Gemini API (PLANNER, CRITIC, JUDGE)
GEMINI_API_KEY=AIza...

# Google Fact Check Tools API (Fake news verification)
GOOGLE_FACT_CHECK_API_KEY=AIza...

# OpenWeather API (Weather claims)
OPENWEATHER_API_KEY=...

# ============================================
# CEREBRAS APIs (Primary models - 4 keys for rotation)
# ============================================
CEREBRAS_API_KEY_1=csk_...
CEREBRAS_API_KEY_2=csk_...
CEREBRAS_API_KEY_3=csk_...
CEREBRAS_API_KEY_4=csk_...

# ============================================
# GROQ APIs (Fallback models - 4 keys for rotation)
# ============================================
GROQ_API_KEY_1=gsk_...
GROQ_API_KEY_2=gsk_...
GROQ_API_KEY_3=gsk_...
GROQ_API_KEY_4=gsk_...
```

---

## Key Features

### 1. Dual Flow System

| Flow Type | Condition | Action |
|-----------|-----------|--------|
| **RECENT NEWS** | Claim within 3 days | Search -> CRITIC -> JUDGE |
| **OLD INFO** | Claim older than 3 days | Fact Check API first |
| Fact Check >=70% | High confidence verdict | Skip Search + CRITIC -> JUDGE |
| Fact Check miss | No results found | Fallback: Search -> CRITIC -> JUDGE |

### 2. Google Fact Check API Integration

- **Multi-query search**: 3 English + 3 Vietnamese queries per claim
- **High confidence skip**: If verdict >=70%, skip Search + CRITIC for speed
- **Combined analysis**: JUDGE considers Fact Check evidence directly

### 3. News Search Strategy

Using `DDGS().news()` for actual news articles:

1. **Priority 1**: Vietnamese news (region: vi-vn)
2. **Priority 2**: International news (region: wt-wt)
3. **Fallback**: Web search if < 5 news results

### 4. Multi-Agent Cognitive System

| Agent | Role | Model (Primary -> Fallback) |
|-------|------|------------------------------|
| **PLANNER** | Generate 5+ search queries | Qwen 3 32B (Cerebras) -> Llama 8B -> Gemma |
| **CRITIC** | Adversarial analysis, find weaknesses | Qwen 3 32B (Cerebras) -> Llama 8B -> Gemma |
| **JUDGE** | Final verdict with Bayesian reasoning | Llama 3.3 70B (Cerebras) -> Llama 3.3 70B (Groq) -> Gemma |

### 5. Binary Source Ranking

| Source Type | Score | Classification |
|-------------|-------|----------------|
| Government (.gov) | 0.95 | USABLE |
| Major News (Reuters, BBC, AP) | 0.95 | USABLE |
| Quality News (VnExpress, VTV) | 0.90 | USABLE |
| Default Sources | 0.55 | USABLE |
| Social Media | 0.30 | BLOCKED |
| Tabloids/UGC | 0.10 | BLOCKED |

> **Binary Rule**: Score >= 0.5 = USABLE (layer_2), Score < 0.5 = BLOCKED (layer_4)

---

## Installation

### Requirements
- Python 3.10+ (Python 3.11/3.12 recommended)
- Windows/Linux/macOS

### Setup

```bash
# Clone repository
git clone https://github.com/Minwsun/ZeroFake.git
cd ZeroFake

# Install dependencies
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env with your API keys (see above)
```

---

## Project Structure

```
app/
├── main.py              # FastAPI server + orchestrator
├── agent_planner.py     # PLANNER agent (query generation)
├── agent_synthesizer.py # CRITIC + JUDGE agents
├── fact_check.py        # Google Fact Check API integration
├── search.py            # DDGS().news() + web search
├── ranker.py            # Source trust ranking
├── model_clients.py     # Multi-API model clients
├── weather.py           # OpenWeather API
├── tool_executor.py     # Tool orchestration + date routing
└── trusted_domains.json # 380+ trusted domains

prompts/
├── planner_prompt.txt   # PLANNER instructions (5+ queries)
├── critic_prompt.txt    # CRITIC adversarial prompt
└── synthesis_prompt.txt # JUDGE Bayesian reasoning

evaluation/
├── test_dataset_1000.json  # 1000 test samples (500 true, 500 fake)
└── run_evaluation.py       # Evaluation script

gui/
└── main_gui.py          # PyQt6 Dark Mode GUI
```

---

## Evaluation

### Test Dataset
- **500 TRUE news**: Real events from 2024-2025
- **500 FAKE news**: Zombie news, fabrication, conspiracy theories, scams

### Metrics
- Accuracy, Precision, Recall, F1 Score
- Confusion Matrix (TIN THAT vs TIN GIA)
- False Positive/Negative Rate

---

## Recent Updates (v2.1)

### December 2024
- **Optimized Dual Flow**: Old info (>3 days) with Fact Check verdict >=70% skips Search + CRITIC
- **Smart Search Skip**: Saves latency when Fact Check API has high confidence result
- **Google Fact Check API**: Multi-query (EN + VN) integration
- **DDGS().news()**: Proper news search instead of web search
- **PLANNER 5+ queries**: Better search coverage (backup if Fact Check fails)
- **FAISS KB Cache**: Semantic deduplication to avoid duplicate queries (98% similarity threshold)
- **Cerebras + Groq**: Multi-key API rotation (4 keys each)

---

## Author

**Nguyen Nhat Minh**  
GitHub: [@Minwsun](https://github.com/Minwsun)  
Repository: https://github.com/Minwsun/ZeroFake
