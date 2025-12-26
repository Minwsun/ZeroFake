# SO SÁNH HỆ THỐNG FACT-CHECKING

## 1. BẢNG SO SÁNH SỐ LIỆU & HIỆU SUẤT (QUANTITATIVE METRICS)

Dữ liệu được tổng hợp từ 1001 mẫu thử nghiệm (500 Thật / 501 Giả).

| Chỉ số (Metrics) | Hệ thống 1 (Multi-Source) | Hệ thống 2 (Adversarial CoT) | Phân tích ý nghĩa |
| --- | --- | --- | --- |
| **Độ chính xác (Accuracy)** | **65.03%** | **94.91%** | Hệ thống 2 giảm sai sót gấp 6 lần nhờ CoT + CRITIC. |
| **False Negative Rate** | **30.94%** | **2.99%** | HT1 thiếu adversarial check nên dễ bị bypass. |
| **False Positive Rate** | 39.00% | 7.20% | HT2 có FILTER loại nguồn nhiễu trước JUDGE. |
| **Latency** | **~49 giây** | **~107 giây** | Trade-off: chậm 2x để đạt độ chính xác thương mại. |
| **Zombie News Detection** | 35% | 90% | HT2 có temporal reasoning mạnh hơn trong CoT. |
| **Chi phí Token** | 1x | ~2.5x | Do CoT prompt dài + nhiều bước xử lý. |

---

## 2. SO SÁNH CẤU TRÚC HỆ THỐNG (SYSTEM ARCHITECTURE)

### Hệ thống 1: Multi-Source Verification Pipeline

*Mô hình "Đa nguồn": Thu thập từ nhiều API, phân tầng độ tin cậy, kết luận dựa trên consensus.*

```
                         ┌─────────────────┐
                         │   INPUT CLAIM   │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │    PLANNER      │
                         │ (Structured     │
                         │  Output + NER)  │
                         └────────┬────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │   MULTI-SOURCE SEARCH   │
                    │  DuckDuckGo + GNews +   │
                    │  Wikipedia + Fact API   │
                    └─────────────┬───────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │    SOURCE TIERING       │
                    │  Tier 1: Official APIs  │
                    │  Tier 2: Reuters, BBC   │
                    │  Tier 3: Forums, Blogs  │
                    │  Tier 4: Social Media   │
                    └─────────────┬───────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │     JUDGE       │
                         │ (Rule-based     │
                         │  Synthesis)     │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │     OUTPUT      │
                         │ TIN THAT/TIN GIA│
                         └─────────────────┘
```

---

### Hệ thống 2: Adversarial Chain-of-Thought Pipeline

*Mô hình "Đa nghi có kiểm soát": Lọc nhiễu, phản biện chủ động, suy luận từng bước.*

```
                         ┌─────────────────┐
                         │   INPUT CLAIM   │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │    PLANNER      │
                         │ (Generate 5-8   │
                         │  diverse queries│
                         │  + CoT planning)│
                         └────────┬────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │     TEMPORAL ROUTER     │
                    │       Info Age?         │
                    └─────────────┬───────────┘
                                  │
            ┌─────────────────────┴─────────────────────┐
            │                                           │
            ▼                                           ▼
    ┌───────────────┐                         ┌───────────────┐
    │  RECENT NEWS  │                         │   OLD INFO    │
    │   (≤3 days)   │                         │   (>3 days)   │
    └───────┬───────┘                         └───────┬───────┘
            │                                         │
            ▼                                         ▼
    ┌───────────────┐                         ┌───────────────┐
    │    SEARCH     │                         │  FACT CHECK   │
    │  (Multi-src)  │                         │     API       │
    └───────┬───────┘                         └───────┬───────┘
            │                                         │
            ▼                               ┌─────────┴─────────┐
    ┌───────────────┐                       │                   │
    │    FILTER     │                       ▼                   ▼
    │  (Llama 8B)   │               ┌─────────────┐     ┌─────────────┐
    │ Remove junk   │               │ Has Result  │     │  No Result  │
    └───────┬───────┘               │   ≥70%      │     │             │
            │                       └──────┬──────┘     └──────┬──────┘
            ▼                              │                   │
    ┌───────────────┐                      │ Skip CRITIC       ▼
    │    CRITIC     │                      │            ┌─────────────┐
    │  (Adversarial │                      │            │   SEARCH    │
    │   Thinking)   │                      │            └──────┬──────┘
    └───────┬───────┘                      │                   │
            │                              │                   ▼
            │                              │            ┌─────────────┐
            │                              │            │   FILTER    │
            │                              │            └──────┬──────┘
            │                              │                   │
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
                         │ (CoT Reasoning  │
                         │  5-Principles)  │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │     OUTPUT      │
                         │ TIN THAT/TIN GIA│
                         │ + thinking_log  │
                         └─────────────────┘
```

---

## 3. SO SÁNH KỸ THUẬT PROMPT (PROMPT ENGINEERING)

### A. Module PLANNER

| Aspect | Hệ thống 1 | Hệ thống 2 |
| --- | --- | --- |
| **Loại Prompt** | Structured Output | Structured Output + CoT |
| **Cấu trúc** | "Extract entities, generate 2-3 queries" | "Step 1: Normalize spelling<br>Step 2: Classify claim type<br>Step 3: Extract all entities<br>Step 4: Generate 5-8 diverse queries<br>Step 5: Identify temporal hints" |
| **Query Style** | Entity-based only | Entity + Context + Negation + Verification |
| **Output** | `{entities, queries, tools}` | `{normalized_claim, entities, diverse_queries, temporal_analysis}` |

**Ví dụ Prompt - Hệ thống 1:**
```
You are a fact-check planner. Given a claim, extract entities and generate search queries.

Claim: "gia btc hom nay la 100k"
Output JSON: {entities: [...], queries: [...], required_tools: [...]}
```

**Ví dụ Prompt - Hệ thống 2 (CoT):**
```
You are a fact-check planner. Follow these steps carefully:

STEP 1 - NORMALIZE: Fix spelling errors in the claim.
STEP 2 - CLASSIFY: Is this NEWS (recent event) or KNOWLEDGE (general fact)?
STEP 3 - EXTRACT: List all named entities (people, orgs, numbers, dates).
STEP 4 - GENERATE QUERIES: Create 5-8 diverse search queries:
  - Full claim (Vietnamese)
  - Full claim (English translation)
  - Entity-only queries
  - Entity + "news" / "tin tuc"
  - Entity + "official" / "chinh thuc"
  - Verification query: "Is [claim] true?"
STEP 5 - TEMPORAL: Identify any time-sensitive elements.

Claim: "gia btc hom nay la 100k"
Think step by step, then output JSON.
```

---

### B. Module JUDGE

| Aspect | Hệ thống 1 | Hệ thống 2 |
| --- | --- | --- |
| **Loại Prompt** | Rule-based Synthesis | Explicit Chain-of-Thought |
| **Reasoning** | Implicit (hidden) | Explicit (step-by-step visible) |
| **Cấu trúc** | "Based on evidence, conclude verdict" | "Apply 5 principles, show reasoning, then conclude" |
| **Output** | `{verdict, reason, confidence}` | `{thinking_process, verdict, evidence_chain}` |

**Ví dụ Prompt - Hệ thống 1:**
```
You are a fact-check judge. Based on the evidence provided and source trust levels,
determine if the claim is TRUE or FALSE.

Claim: [claim]
Evidence: [evidence_bundle]

Output: {conclusion: "TIN THAT/TIN GIA", reason: "...", confidence: 0-100}
```

**Ví dụ Prompt - Hệ thống 2 (CoT):**
```
You are a fact-check judge. Apply the 5-PRINCIPLE FRAMEWORK step by step:

PRINCIPLE 1 - TEMPORAL CONSISTENCY:
- Compare claim's implied time vs evidence timestamps
- Flag if claim says "moi day" but evidence is from 2020

PRINCIPLE 2 - SOURCE CREDIBILITY:
- Tier 1 (Official APIs) > Tier 2 (Reuters, BBC) > Tier 3 (Blogs) > Tier 4 (Social)
- Require at least 2 Tier 1-2 sources for TRUE verdict

PRINCIPLE 3 - PATTERN DETECTION:
- Check for SCAM signals: "trung thuong", "chuyen khoan ngay"
- Check for ZOMBIE NEWS: "NONG" + old event
- Check for SATIRE: obvious humor markers

PRINCIPLE 4 - SEMANTIC MATCHING:
- Does evidence CONFIRM, CONTRADICT, or NOT ADDRESS the claim?
- Partial match = UNVERIFIED, not TRUE

PRINCIPLE 5 - COUNTER-EVIDENCE WEIGHT:
- If CRITIC found counter-evidence, weigh against supporting evidence
- Strong counter-evidence overrides weak supporting evidence

Claim: [claim]
Evidence: [filtered_evidence]
Critic_Analysis: [critic_output]

THINKING PROCESS: (show your reasoning for each principle)
FINAL VERDICT: TIN THAT / TIN GIA / KHONG XAC DINH
EVIDENCE CHAIN: [list sources used]
```

---

### C. Module FILTER & CRITIC (Chỉ có ở Hệ thống 2)

**FILTER Prompt:**
```
You are an evidence filter. Remove noise and keep only relevant, high-quality sources.

REMOVE if:
- Duplicate content
- Irrelevant to the claim
- Low-trust source (spam, ads, clickbait)
- No factual information

KEEP if:
- Directly addresses the claim
- From trusted news source
- Contains verifiable facts/numbers
- Has clear timestamp

Evidence list: [raw_evidence]
Output: Top 5-10 most relevant evidence items, ranked by quality.
```

**CRITIC Prompt (Adversarial):**
```
You are an adversarial fact-checker. Your job is to CHALLENGE the claim.

TASK 1: Find potential COUNTER-EVIDENCE
- Search for sources that CONTRADICT the claim
- Look for alternative explanations

TASK 2: Identify WEAKNESSES
- What's missing from the evidence?
- Are there logical gaps?
- Could this be a HALF-TRUTH?

TASK 3: Devil's Advocate
- If this claim is FALSE, what would the evidence look like?
- Does current evidence match that pattern?

Claim: [claim]
Supporting Evidence: [filtered_evidence]

Output: {
  counter_evidence: [...],
  weaknesses: [...],
  confidence_adjustment: "increase/decrease/maintain",
  final_assessment: "..."
}
```

---

## 4. BẢNG TỔNG KẾT

| Tiêu chí | Hệ thống 1 | Hệ thống 2 |
|----------|------------|------------|
| **Số bước** | 4 bước | 6-8 bước |
| **Prompt Style** | Structured Output | Structured + CoT |
| **Source Tiering** | Có | Có |
| **Noise Filtering** | Không | Có (FILTER Agent) |
| **Adversarial Check** | Không | Có (CRITIC Agent) |
| **Reasoning** | Implicit | Explicit (5-Principle) |
| **Temporal Logic** | Basic | Advanced (Temporal Router) |
| **Explainability** | Trung bình | Cao (thinking_process) |
| **Speed** | Nhanh (~49s) | Chậm (~107s) |
| **Accuracy** | 65% | 95% |
| **Best For** | Real-time, high volume | High-stakes verification |
