# SO SÁNH HỆ THỐNG FACT-CHECKING

## 1. BẢNG SO SÁNH SỐ LIỆU & HIỆU SUẤT (QUANTITATIVE METRICS)

Dữ liệu được tổng hợp từ 1001 mẫu thử nghiệm (500 Thật / 501 Giả).

| Chỉ số (Metrics) | Hệ thống 1 (Cũ - Tốc độ) | Hệ thống 2 (Mới - Chính xác) | Phân tích ý nghĩa |
| --- | --- | --- | --- |
| **Độ chính xác (Accuracy)** | **65.03%** | **94.91%** | Hệ thống mới giảm sai sót gấp 6 lần. |
| **False Negative Rate (Bỏ lọt tin giả)** | **30.94%** (Rất nguy hiểm) | **2.99%** (An toàn cao) | Hệ thống cũ dễ bị lừa bởi trang web giả mạo (Scam). Hệ thống mới chặn gần như tuyệt đối. |
| **False Positive Rate (Vu oan tin thật)** | 39.00% | 7.20% | Hệ thống cũ hay nhầm meme/tin đùa là giả. |
| **Latency (Độ trễ trung bình)** | **~49 giây** | **~107 giây** | **Trade-off:** Chấp nhận chậm hơn 2x để đạt độ tin cậy thương mại. |
| **Khả năng bắt "Zombie News"** | 0% (Thất bại hoàn toàn) | 90% (Thành công) | Hệ thống cũ chỉ bắt keyword, không so sánh ngày tháng. |
| **Chi phí Token (Ước tính)** | 1x (Thấp) | ~2.5x (Cao) | Do prompt dài hơn (CoT) và chạy qua nhiều bước (Filter, Critic). |

---

## 2. SO SÁNH CẤU TRÚC HỆ THỐNG (SYSTEM ARCHITECTURE)

### Hệ thống 1: Tuyến tính (Linear Pipeline)

*Mô hình "Tin tưởng": Nhận input → Tìm kiếm → Kết luận ngay.*

```mermaid
flowchart TD
    subgraph INPUT["USER INPUT"]
        A["'Theo VnExpress: Bitcoin đạt 100k USD'"]
    end

    subgraph PLANNER["AGENT 1: PLANNER"]
        B1["app/agent_planner.py"]
        B2["prompts/planner_prompt_simple.txt"]
        B3["Tasks:
        - Sửa lỗi chính tả -> normalized_claim
        - Phân loại: NEWS / KNOWLEDGE / WEATHER
        - Trích xuất entities
        - Tạo 2-3 search queries"]
        B4["Output: JSON với required_tools"]
    end

    subgraph EXECUTOR["TOOL EXECUTOR"]
        C1["app/tool_executor.py"]
        subgraph TOOLS["Available Tools"]
            T1["SEARCH
            DuckDuckGo
            Google News"]
            T2["WEATHER
            OpenWeather API"]
            T3["FACT CHECK
            Google API"]
        end
        C2["Output: evidence_bundle
        - layer_1_tools: API data
        - layer_2_high_trust: VnExpress, Reuters
        - layer_4_social_low: Facebook, TikTok"]
    end

    subgraph JUDGE["AGENT 3: JUDGE"]
        D1["app/agent_synthesizer.py"]
        D2["prompts/synthesis_prompt_simple.txt"]
        D3["Decision Rules:"]
        D4["TIN THAT when:
        - Evidence từ trusted sources xác nhận
        - AI biết đây là sự kiện đã xảy ra
        - Weather API data khớp với claim"]
        D5["TIN GIA when:
        - Evidence bác bỏ claim
        - ZOMBIE NEWS: 'NONG' + sự kiện cũ
        - SCAM: hứa tiền + yêu cầu thông tin
        - Không tìm thấy evidence xác nhận"]
    end

    subgraph OUTPUT["API RESPONSE"]
        E["{
          'conclusion': 'TIN THAT',
          'reason': 'Bitcoin đạt 100k USD được xác nhận...',
          'confidence': 85,
          'evidence_source': 'reuters.com'
        }"]
    end

    INPUT --> PLANNER
    PLANNER --> EXECUTOR
    EXECUTOR --> JUDGE
    JUDGE --> OUTPUT

    style INPUT fill:#e1f5fe
    style PLANNER fill:#fff3e0
    style EXECUTOR fill:#f3e5f5
    style JUDGE fill:#e8f5e9
    style OUTPUT fill:#fce4ec
```

---

### Hệ thống 2: Vòng lặp & Rẽ nhánh (Conditional Loop & Filter)

*Mô hình "Đa nghi": Làm sạch input, lọc nguồn rác, và phản biện trước khi kết luận.*

```mermaid
flowchart TD
    INPUT["INPUT CLAIM"] --> PLANNER

    subgraph PLANNER["PLANNER"]
        P1["Generate 5+ search queries"]
    end

    PLANNER --> AGE{"Info Age?"}

    AGE -->|"<=3 days"| RECENT["RECENT NEWS"]
    AGE -->|">3 days"| OLD["OLD INFO"]

    subgraph RECENT_FLOW["Recent News Flow"]
        RECENT --> SEARCH1["SEARCH
        Multi-source"]
        SEARCH1 --> FILTER1["FILTER
        Llama 8B
        Remove junk"]
        FILTER1 --> CRITIC1["CRITIC
        Adversarial"]
    end

    subgraph OLD_FLOW["Old Info Flow"]
        OLD --> FACTCHECK["FACT CHECK API"]
        FACTCHECK --> HAS_RESULT{"Has Result >=70%?"}
        HAS_RESULT -->|"Yes"| SKIP["Skip CRITIC"]
        HAS_RESULT -->|"No"| SEARCH2["SEARCH"]
        SEARCH2 --> FILTER2["FILTER"]
        FILTER2 --> CRITIC2["CRITIC"]
    end

    CRITIC1 --> MERGE([" "])
    SKIP --> MERGE
    CRITIC2 --> MERGE

    MERGE --> JUDGE["JUDGE
    Final Verdict"]

    JUDGE --> OUTPUT["OUTPUT
    TIN THAT / TIN GIA"]

    style INPUT fill:#e3f2fd
    style PLANNER fill:#fff8e1
    style AGE fill:#fce4ec
    style RECENT fill:#e8f5e9
    style OLD fill:#f3e5f5
    style JUDGE fill:#e8f5e9
    style OUTPUT fill:#ffebee
```

---

## 3. SO SÁNH KỸ THUẬT PROMPT (PROMPT ENGINEERING)

Sự khác biệt nằm ở tư duy: **Chỉ thị trực tiếp (Direct Instruction)** vs **Chuỗi suy luận (Chain of Thought - CoT)**.

### A. Tại module PLANNER (Lập kế hoạch)

| Aspect | Hệ thống 1 (Cũ) | Hệ thống 2 (Mới) |
| --- | --- | --- |
| **Dạng Prompt** | **Direct Instruction** (Ra lệnh) | **Structured output** (Cấu trúc hóa) |
| **Nội dung** | "Hãy tìm kiếm thông tin cho câu sau." | "Bước 1: Sửa lỗi chính tả.<br>Bước 2: Phân loại luồng tin.<br>Bước 3: Trích xuất Entity.<br>Bước 4: Tạo query đa chiều." |
| **Ví dụ Input** | "gia btc hom nay" (giữ nguyên lỗi) | "gia btc hom nay" -> `normalized: "giá bitcoin hôm nay"` |
| **Hiệu quả** | Dễ tìm sai nếu user gõ sai. | Tìm chính xác nhờ bước chuẩn hóa. |

### B. Tại module JUDGE (Phán quyết)

Đây là nơi "bộ não" thay đổi hoàn toàn.

| Aspect | Hệ thống 1 (Cũ) | Hệ thống 2 (Mới) |
| --- | --- | --- |
| **Kỹ thuật** | **Implicit Reasoning** (Suy luận ngầm) | **Explicit Chain of Thought** (Suy luận từng bước) |
| **Prompt Core** | "Dựa vào bằng chứng, hãy kết luận tin này đúng hay sai." | "Áp dụng 5 nguyên tắc sau:<br>1. Temporal: Kiểm tra mốc thời gian.<br>2. Source: Ưu tiên nguồn Tier 1.<br>3. Pattern: Tìm dấu hiệu lừa đảo...<br>Sau đó mới kết luận." |
| **Output** | `TRUE` / `FALSE` | `Thinking_process`: "Tôi thấy ngày bài báo là 2020, nhưng claim bảo 'mới đây' -> Mâu thuẫn thời gian."<br>`Conclusion`: `FAKE` |
| **Điểm mạnh** | Nhanh, code xử lý output dễ. | Giải thích được **Tại sao** (Explainable AI), tránh ảo giác (Hallucination). |

---

## 4. SƠ ĐỒ TỔNG QUAN SO SÁNH

```mermaid
flowchart LR
    subgraph SYS1["HE THONG 1 - TOC DO"]
        direction TB
        A1["INPUT"] --> B1["PLANNER"]
        B1 --> C1["SEARCH"]
        C1 --> D1["JUDGE"]
        D1 --> E1["OUTPUT"]
    end

    subgraph SYS2["HE THONG 2 - CHINH XAC"]
        direction TB
        A2["INPUT"] --> B2["PLANNER"]
        B2 --> C2{"Age Check"}
        C2 --> D2["SEARCH/API"]
        D2 --> E2["FILTER"]
        E2 --> F2["CRITIC"]
        F2 --> G2["JUDGE"]
        G2 --> H2["OUTPUT"]
    end

    SYS1 -.->|"Trade-off"| SYS2

    style SYS1 fill:#fff3e0
    style SYS2 fill:#e8f5e9
```

| Tiêu chí | Hệ thống 1 | Hệ thống 2 |
|----------|------------|------------|
| **Số bước** | 4 bước | 6-8 bước |
| **Filtering** | Không | Có (Llama 8B) |
| **Adversarial Check** | Không | Có (CRITIC) |
| **Temporal Logic** | Yếu | Mạnh |
| **Explainability** | Thấp | Cao |
