# SO SÁNH HỆ THỐNG FACT-CHECKING

## 1. BẢNG SO SÁNH SỐ LIỆU & HIỆU SUẤT (QUANTITATIVE METRICS)

Dữ liệu được tổng hợp từ 1001 mẫu thử nghiệm (500 Thật / 501 Giả).

| Chỉ số (Metrics) | Hệ thống 1 (Multi-Source) | Hệ thống 2 (Multi-Agent CoT) | Phân tích ý nghĩa |
| --- | --- | --- | --- |
| **Độ chính xác (Accuracy)** | **65.03%** | **94.91%** | Hệ thống 2 giảm sai sót gấp 6 lần nhờ multi-agent + CoT. |
| **False Negative Rate** | **30.94%** | **2.99%** | HT1 thiếu CRITIC agent nên dễ bị bypass bởi tin giả tinh vi. |
| **False Positive Rate** | 39.00% | 7.20% | HT2 có FILTER agent loại nguồn nhiễu trước khi JUDGE. |
| **Latency** | **~49 giây** | **~107 giây** | Trade-off: chậm 2x để đạt độ chính xác thương mại. |
| **Zombie News Detection** | 35% | 90% | HT2 có temporal reasoning mạnh hơn trong CoT prompt. |
| **Chi phí Token** | 1x | ~2.5x | Do CoT prompt dài + nhiều agent xử lý song song. |

---

## 2. TẠI SAO HỆ THỐNG 2 LÀ "MULTI-AGENT" CÒN HỆ THỐNG 1 KHÔNG PHẢI?

### Định nghĩa Agent trong AI

Một **AI Agent** là một hệ thống có khả năng:
1. **Tự chủ (Autonomy)**: Tự đưa ra quyết định mà không cần hướng dẫn từng bước
2. **Chuyên biệt (Specialization)**: Có vai trò và mục tiêu riêng biệt
3. **Tương tác (Interaction)**: Giao tiếp với các agent khác để hoàn thành nhiệm vụ
4. **Phản hồi (Feedback Loop)**: Nhận kết quả từ agent khác và điều chỉnh hành vi

### So sánh kiến trúc

| Đặc điểm | Hệ thống 1 (Pipeline) | Hệ thống 2 (Multi-Agent) |
|----------|----------------------|--------------------------|
| **Số lượng LLM calls** | 2 (Planner + Judge) | 4 (Planner + Filter + Critic + Judge) |
| **Vai trò mỗi LLM** | Chung chung | Chuyên biệt hóa cao |
| **Giao tiếp giữa LLM** | Một chiều (→) | Đa chiều (↔) |
| **Quyết định tự chủ** | Không | Có (Critic có thể yêu cầu search thêm) |
| **Phản biện nội bộ** | Không | Có (Critic challenge Judge) |

### Tại sao gọi là "Agent"?

**Hệ thống 1: KHÔNG phải Agent** vì:
- Mỗi bước chỉ làm 1 việc cố định, không tự quyết định
- Không có sự tương tác/phản hồi giữa các bước
- Luồng xử lý là tuyến tính, không thể quay lại

**Hệ thống 2: LÀ Multi-Agent** vì:
- **FILTER Agent**: Tự quyết định giữ/bỏ evidence nào (không cần rule cứng)
- **CRITIC Agent**: Tự chủ tìm counter-evidence, có thể yêu cầu search thêm
- **JUDGE Agent**: Nhận input từ cả FILTER và CRITIC, cân nhắc cả 2 quan điểm
- Có **feedback loop**: Nếu CRITIC tìm thấy phản chứng mạnh, JUDGE phải xem xét lại

```
HỆ THỐNG 1: Pipeline đơn giản
┌────────┐    ┌────────┐    ┌────────┐
│PLANNER │ -> │ SEARCH │ -> │ JUDGE  │  -> OUTPUT
└────────┘    └────────┘    └────────┘
   (LLM)       (Tools)        (LLM)

HỆ THỐNG 2: Multi-Agent với tương tác
┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐
│PLANNER │ -> │ SEARCH │ -> │ FILTER │ -> │ CRITIC │ -> │ JUDGE  │ -> OUTPUT
└────────┘    └────────┘    └────────┘    └────────┘    └────────┘
   (LLM)       (Tools)        (LLM)         (LLM)         (LLM)
                               │             │              ↑
                               │    "Tôi tìm thấy          │
                               │    counter-evidence!"     │
                               └───────────────────────────┘
                                    (Feedback Loop)
```

---

## 3. VAI TRÒ CỦA TỪNG MODEL (LLM) TRONG HỆ THỐNG 2

### Bảng chi tiết công dụng từng Model

| Agent | Model sử dụng | Công dụng chính | Tại sao cần riêng? |
|-------|---------------|-----------------|-------------------|
| **PLANNER** | Gemini 2.0 Flash | Phân tích claim, tạo search queries, phân loại luồng tin | Cần model mạnh để hiểu ngữ cảnh tiếng Việt, sửa lỗi chính tả |
| **FILTER** | Llama 8B / Gemma 12B | Lọc bỏ nguồn rác, duplicate, spam | Model nhỏ đủ để classify, tiết kiệm cost |
| **CRITIC** | Gemini 2.0 Flash | Tìm counter-evidence, adversarial thinking, challenge hypothesis | Cần model mạnh để suy luận phản biện |
| **JUDGE** | Gemini 2.0 Flash | Tổng hợp tất cả evidence, áp dụng 5-principle framework, đưa verdict | Model mạnh nhất cho quyết định cuối cùng |

### Tại sao cần 4 Model thay vì 1?

#### 1. **Separation of Concerns** (Phân tách trách nhiệm)
```
1 Model làm tất cả:
┌─────────────────────────────────────────────────┐
│  "Hãy lọc evidence, tìm counter-evidence,       │
│   rồi kết luận luôn đi!"                        │
│                                                 │
│  -> Model bị overload, dễ skip bước quan trọng  │
│  -> Không thể debug từng bước                   │
│  -> Output không nhất quán                      │
└─────────────────────────────────────────────────┘

4 Model chuyên biệt:
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│ FILTER   │  │ CRITIC   │  │  JUDGE   │  │ PLANNER  │
│ "Chỉ lọc │  │ "Chỉ tìm │  │ "Chỉ kết │  │ "Chỉ tạo │
│  rác"    │  │ phản     │  │  luận"   │  │  query"  │
│          │  │ chứng"   │  │          │  │          │
└──────────┘  └──────────┘  └──────────┘  └──────────┘
   -> Mỗi model tập trung 100% vào 1 nhiệm vụ
   -> Có thể debug từng bước
   -> Output nhất quán, có thể verify
```

#### 2. **Adversarial Design** (Thiết kế đối kháng)

Đây là lý do QUAN TRỌNG NHẤT khiến Hệ thống 2 vượt trội:

```
Hệ thống 1: Judge tự xác nhận chính mình
┌─────────────────────────────────────────────────┐
│ JUDGE: "Có 3 nguồn nói Bitcoin = 100k"          │
│        "Vậy là TIN THẬT!"                       │
│                                                 │
│ Vấn đề: Không ai challenge, không ai kiểm tra  │
│         -> Dễ bị lừa bởi tin giả có nguồn fake  │
└─────────────────────────────────────────────────┘

Hệ thống 2: Critic challenge Judge
┌─────────────────────────────────────────────────┐
│ CRITIC: "Khoan! Tôi tìm thấy Reuters nói        │
│          Bitcoin chưa bao giờ đạt 100k!"        │
│                                                 │
│ JUDGE:  "Hmm, để tôi xem lại... 3 nguồn kia    │
│          đều là blog cá nhân, còn Reuters là   │
│          Tier 1. Vậy kết luận: TIN GIẢ!"       │
└─────────────────────────────────────────────────┘
```

---

## 4. TẠI SAO MULTI-AGENT TỐT HƠN VÀ TỐT HƠN BAO NHIÊU?

### Bảng so sánh hiệu quả

| Metric | Hệ thống 1 (1 flow) | Hệ thống 2 (4 agents) | Cải thiện |
|--------|---------------------|----------------------|-----------|
| **Accuracy** | 65.03% | 94.91% | **+29.88%** (tăng 46%) |
| **False Negative** | 30.94% | 2.99% | **-27.95%** (giảm 90%) |
| **False Positive** | 39.00% | 7.20% | **-31.80%** (giảm 82%) |
| **Zombie News** | 35% | 90% | **+55%** (tăng 157%) |

### Phân tích tại sao tốt hơn

#### A. FILTER Agent giảm 82% False Positive

```
VẤN ĐỀ Ở HỆ THỐNG 1:
- Search trả về 20 kết quả, bao gồm spam, blog, meme
- Judge nhìn thấy "Tin giả" trong 1 bài meme về Bitcoin
- Judge kết luận: "TIN GIẢ" (SAI! Đây chỉ là meme đùa)

GIẢI PHÁP Ở HỆ THỐNG 2:
- Search trả về 20 kết quả
- FILTER loại bỏ meme, spam, chỉ giữ 5 nguồn uy tín
- Judge không bao giờ nhìn thấy meme
- Judge kết luận dựa trên Reuters, BBC: "TIN THẬT" (ĐÚNG!)
```

**Tác động**: FPR giảm từ 39% → 7.2% 

#### B. CRITIC Agent giảm 90% False Negative

```
VẤN ĐỀ Ở HỆ THỐNG 1:
- Tin giả có 3 nguồn "xác nhận" (đều là trang scam)
- Judge chỉ đếm số lượng nguồn: "3 nguồn = đủ tin cậy"
- Kết luận: "TIN THẬT" (SAI! Đây là lừa đảo)

GIẢI PHÁP Ở HỆ THỐNG 2:
- CRITIC chủ động tìm kiếm: "Có ai nói điều ngược lại không?"
- CRITIC tìm thấy: "Báo Tuổi Trẻ cảnh báo đây là chiêu lừa đảo"
- JUDGE nhận được cả 2 phía: 3 nguồn ủng hộ vs 1 nguồn Tier 1 phản bác
- Kết luận: "TIN GIẢ" vì Tier 1 > 3 nguồn Tier 4 (ĐÚNG!)
```

**Tác động**: FNR giảm từ 30.94% → 2.99%

#### C. CoT Prompting tăng Explainability

```
HỆ THỐNG 1 OUTPUT:
{
  "conclusion": "TIN GIẢ",
  "reason": "Không tìm thấy nguồn xác nhận",
  "confidence": 70
}
-> Người dùng: "Tại sao? Tôi thấy có nguồn mà?"

HỆ THỐNG 2 OUTPUT:
{
  "thinking_process": {
    "temporal": "Claim nói 'hôm nay' nhưng evidence từ 2020 -> Mâu thuẫn",
    "source": "3 nguồn ủng hộ đều là blog cá nhân (Tier 4)",
    "counter": "CRITIC tìm thấy Reuters phản bác (Tier 1)",
    "pattern": "URL có dấu hiệu scam: typosquatting vnexpress → vn-express"
  },
  "conclusion": "TIN GIẢ",
  "evidence_chain": ["reuters.com/...", "tuoitre.vn/..."]
}
-> Người dùng hiểu TẠI SAO và TIN TƯỞNG kết quả
```

---

## 5. SO SÁNH CẤU TRÚC HỆ THỐNG (ARCHITECTURE)

### Hệ thống 1: Single-Flow Pipeline

*Mô hình "Đa nguồn": Thu thập từ nhiều API, phân tầng độ tin cậy, kết luận dựa trên consensus.*

```
                         ┌─────────────────┐
                         │   INPUT CLAIM   │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │    PLANNER      │
                         │   [Gemini 2.0]  │
                         │ (Structured     │
                         │  Output + NER)  │
                         └────────┬────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │   MULTI-SOURCE SEARCH   │
                    │  DuckDuckGo + GNews +   │
                    │  Wikipedia + Fact API   │
                    │       [Tools]           │
                    └─────────────┬───────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │    SOURCE TIERING       │
                    │  Tier 1: Official APIs  │
                    │  Tier 2: Reuters, BBC   │
                    │  Tier 3: Forums, Blogs  │
                    │  Tier 4: Social Media   │
                    │    [Rule-based Code]    │
                    └─────────────┬───────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │     JUDGE       │
                         │   [Gemini 2.0]  │
                         │ (Rule-based     │
                         │  Synthesis)     │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │     OUTPUT      │
                         │ TIN THAT/TIN GIA│
                         └─────────────────┘

Tổng: 2 LLM calls (Planner + Judge)
```

---

### Hệ thống 2: Multi-Agent Pipeline

*Mô hình "Đa Agent": 4 agent chuyên biệt phối hợp, có phản biện nội bộ.*

```
                         ┌─────────────────┐
                         │   INPUT CLAIM   │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │    PLANNER      │
                         │   [Gemini 2.0]  │
                         │ (Generate 5-8   │
                         │  diverse queries│
                         │  + CoT planning)│
                         └────────┬────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │     TEMPORAL ROUTER     │
                    │       Info Age?         │
                    │     [Rule-based]        │
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
    │    [Tools]    │                         │    [Tools]    │
    └───────┬───────┘                         └───────┬───────┘
            │                                         │
            ▼                               ┌─────────┴─────────┐
    ┌───────────────┐                       │                   │
    │    FILTER     │                       ▼                   ▼
    │ [Llama 8B /   │               ┌─────────────┐     ┌─────────────┐
    │  Gemma 12B]   │               │ Has Result  │     │  No Result  │
    │ Remove junk   │               │   ≥70%      │     │             │
    └───────┬───────┘               └──────┬──────┘     └──────┬──────┘
            │                              │                   │
            ▼                              │ Skip CRITIC       ▼
    ┌───────────────┐                      │            ┌─────────────┐
    │    CRITIC     │                      │            │   SEARCH    │
    │ [Gemini 2.0]  │                      │            └──────┬──────┘
    │ (Adversarial  │                      │                   │
    │  Thinking)    │                      │                   ▼
    └───────┬───────┘                      │            ┌─────────────┐
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
                         │   [Gemini 2.0]  │
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

Tổng: 4 LLM calls (Planner + Filter + Critic + Judge)
```

---

## 6. SO SÁNH KỸ THUẬT PROMPT (PROMPT ENGINEERING)

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

## 7. BẢNG TỔNG KẾT

| Tiêu chí | Hệ thống 1 | Hệ thống 2 | Ghi chú |
|----------|------------|------------|---------|
| **Kiến trúc** | Single-flow Pipeline | Multi-Agent System | HT2 là agentic AI |
| **Số LLM calls** | 2 | 4 | Trade-off: cost vs accuracy |
| **Agents chuyên biệt** | Không | Có (FILTER, CRITIC) | Separation of concerns |
| **Adversarial Design** | Không | Có | CRITIC challenge JUDGE |
| **Prompt Style** | Structured Output | Structured + CoT | CoT tăng reasoning |
| **Reasoning** | Implicit | Explicit (5-Principle) | Explainable AI |
| **Feedback Loop** | Không | Có | Agent tương tác nhau |
| **Accuracy** | 65% | 95% | **+30%** |
| **FNR** | 31% | 3% | **-90%** |
| **FPR** | 39% | 7% | **-82%** |
| **Speed** | Nhanh (~49s) | Chậm (~107s) | Trade-off cần thiết |
| **Best For** | Real-time, high volume | High-stakes verification | Tùy use case |
