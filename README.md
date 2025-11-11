# ZeroFake V1.0

Hệ thống phát hiện và kiểm chứng tin giả theo thời gian thực, ưu tiên nguồn uy tín và dữ liệu API thời tiết toàn cầu.

---

## 1) Mục tiêu
ZeroFake giúp kiểm tra nhanh một tin/bài viết là: "TIN THẬT" | "TIN GIẢ" | "GÂY HIỂU LẦM" | "TIN CHƯA XÁC THỰC". Hệ thống vận hành hoàn toàn API-Native, không yêu cầu huấn luyện cục bộ.

## 2) Kiến trúc tổng quan
- Frontend: GUI PyQt6 (Dark Mode), không bị đơ nhờ QThread.
- Backend: FastAPI (Python), pipeline bất đồng bộ.
- Các dịch vụ tích hợp:
  - Google Custom Search API (lấy bài báo theo thời gian, 3-pass thông minh v3.8)
  - Gemini API (phân tích với prompt động)
  - OpenWeatherMap API (thời tiết toàn cầu: current + forecast 5 ngày, có geocoding toàn cầu)
- Lưu trữ/Learning:
  - KB Cache: SQLite + FAISS (nhớ các kết quả đã kiểm chứng)
  - Feedback loop: SQLite + FAISS (Relevant Retrieval: tự động lôi ví dụ lỗi tương tự đưa vào prompt)

## 3) Luồng hoạt động
1. GUI gửi đoạn tin cần kiểm tra lên FastAPI.
2. Backend kiểm tra KB Cache (FAISS) – nếu có, trả ngay.
3. Phân loại sơ bộ (classify_claim) – nếu là tin thời tiết, tiền xử lý thời gian (present/future/historical) và gọi OpenWeather:
   - present/future (trong ≤5 ngày): gọi forecast/current → tạo weather_api_data {status, data}
   - quá xa hoặc quá khứ: {status: forecast_not_available/historical_not_available}
4. Google Search 3-pass (v3.8):
   - Pass 1: "precise" trên nguồn uy tín
   - Pass 2: "broad" toàn web
   - Pass 3: "keyword" rút gọn + nguồn uy tín (fallback)
5. Ranker xử lý và xếp hạng nguồn theo config.json (hỗ trợ cấu trúc lồng nhau), trích xuất ngày đăng (đa định dạng).
6. Prompt động gửi Gemini:
   - current_date, weather_api_data, evidence_json_string (báo chí), dynamic few-shots từ feedback.
   - Quy tắc:
     - Quy tắc 0 (Thời tiết): ưu tiên API thời tiết khi status=success; fallback báo chí nếu forecast_not_available.
     - Quy tắc 1 (Trạng thái): ưu tiên nguồn uy tín, bài mới nhất.
     - Quy tắc 2.1 (Entailment): nhiều nguồn uy tín xác nhận → TIN THẬT.
     - Quy tắc 2.2 (Contradiction): mâu thuẫn bởi nguồn cấp 1, mới → TIN GIẢ.
     - Quy tắc 3 (Silence): sau 3-pass vẫn rỗng → TIN CHƯA XÁC THỰC.
     - Quy tắc 4 (Misleading): satire/sai bối cảnh… → GÂY HIỂU LẦM.
7. Lưu kết quả vào KB Cache (nền) và trả về GUI.
8. Người dùng có thể gửi feedback ; hệ thống ghi log và học từ lỗi.

## 4) Cài đặt & Chạy
### Yêu cầu
- Python 3.10+ (khuyến nghị 3.11/3.12/3.13)

### Cài đặt
```bash
pip install -r requirements.txt
```

### Cấu hình API Keys (.env)
Tạo file `.env` ở thư mục gốc:
```
GOOGLE_API_KEY=...            # Google Custom Search API Key
GOOGLE_CSE_ID=...             # Custom Search Engine ID
GEMINI_API_KEY=...            # Google AI Studio (Gemini) API Key
OPENWEATHER_API_KEY=...       # OpenWeather API Key
```

### Chạy Backend
- Windows: double-click `run_server.bat`
- Hoặc:
```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
- Health check: http://127.0.0.1:8000/
- API docs: http://127.0.0.1:8000/docs

### Chạy GUI
- Windows: double-click `run_gui.bat`
- Hoặc:
```bash
python gui/main_gui.py
```

## 5) Cấu trúc thư mục (rút gọn)
```
app/
  __init__.py
  main.py          # FastAPI orchestrator (ZeroFake V1.0)
  kb.py            # KB Cache (SQLite + FAISS)
  search.py        # Google Search 3-pass
  ranker.py        # Ranker (flatten config, date extractor pro)
  gemini.py        # Gemini API + safe prompt formatter
  feedback.py      # Feedback loop (Relevant Retrieval)
  weather.py       # Geocoding + weather current/forecast (global)
config.json        # Source ranker (lồng nhau)
 gemini_prompt.txt # Prompt (Rule 0/1/2.1/2.2/3/4)
 gui/main_gui.py   # PyQt6 (Dark Mode)
```


---

Tác giả: Nguyễn Nhật Minh

