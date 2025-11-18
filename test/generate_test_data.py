import os
import json
import re
import requests

from dotenv import load_dotenv
from tqdm import tqdm

# Tải API key từ file .env
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY chưa được cấu hình trong .env")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
LLAMA_MODEL = "meta-llama/llama-3.3-70b-instruct"

# Master prompt để yêu cầu Gemini tạo dữ liệu kiểm thử
MASTER_PROMPT_TEMPLATE = """
Bạn là một kỹ sư kiểm thử (QA Engineer) chuyên tạo dữ liệu kiểm thử cho hệ thống fact-checking ZeroFake.
Nhiệm vụ của bạn là tạo ra <<NUM_SAMPLES>> mẫu tin tức độc đáo, thực tế, bằng tiếng Việt.
Các mẫu phải tuân thủ nghiêm ngặt các danh mục và quy tắc logic của hệ thống.

QUY TẮC LOGIC (từ synthesis_prompt.txt):
1.  **Sự thật hiển nhiên (Đúng/Sai)**: Tin tức là kiến thức cơ bản (khoa học, địa lý, lịch sử).
2.  **Thời tiết (Đúng/Sai)**: Tin tức dự báo thời tiết (ví dụ: "Hà Nội ngày mai mưa").
3.  **Tin thật (Lớp 2)**: Tin tức có thật, được nhiều báo lớn (VnExpress, Reuters) xác nhận.
4.  **Tin giả (Mâu thuẫn)**: Tin tức có thật nhưng bịa đặt số liệu.
5.  **Tin giả (Im lặng)**: Tin tức bịa đặt hoàn toàn, không thể tìm thấy trên bất kỳ báo uy tín nào.
6.  **Gây hiểu lầm (Tin cũ)**: Tin tức đã từng đúng nhưng hiện tại đã lỗi thời.

YÊU CẦU DANH MỤC:
Hãy tạo chính xác <<NUM_SAMPLES>> mẫu tin thuộc danh mục: "<<CATEGORY_NAME>>"

ĐỊNH DẠNG OUTPUT:
Chỉ trả về một danh sách JSON (JSON list), mỗi đối tượng JSON chứa:
{
  "text": "(Nội dung tin tức tiếng Việt cần kiểm tra)",
  "ground_truth": "(Nhãn đúng: \"TIN THẬT\" | \"TIN GIẢ\" | \"GÂY HIỂU LẦM\")",
  "category": "(Tên danh mục được yêu cầu ở trên)"
}

Ví dụ:
[
  {
    "text": "Nước Mỹ tuyên bố Paris là thủ đô của nước Anh.",
    "ground_truth": "TIN GIẢ",
    "category": "Sự thật hiển nhiên (Sai)"
  },
  {
    "text": "Dự báo thời tiết Hà Nội ngày mai trời nắng, không mưa.",
    "ground_truth": "TIN THẬT",
    "category": "Thời tiết (Đúng)"
  }
]

Hãy bắt đầu tạo <<NUM_SAMPLES>> mẫu cho danh mục: "<<CATEGORY_NAME>>"
"""

# Cấu hình danh mục và số lượng mẫu
CATEGORIES_TO_GENERATE = {
    "Sự thật hiển nhiên (Đúng)": (100, "TIN THẬT"),
    "Sự thật hiển nhiên (Sai)": (100, "TIN GIẢ"),
    "Thời tiết (Đúng)": (100, "TIN THẬT"),
    "Thời tiết (Sai)": (100, "TIN GIẢ"),
    "Tin thật (Lớp 2 xác nhận)": (200, "TIN THẬT"),
    "Tin giả (Mâu thuẫn số liệu)": (150, "TIN GIẢ"),
    "Tin giả (Bịa đặt hoàn toàn)": (150, "TIN GIẢ"),
    "Gây hiểu lầm (Tin cũ)": (100, "GÂY HIỂU LẦM"),
}

OUTPUT_FILE = "test_data_1000.jsonl"


def clean_response(text: str) -> str | None:
    """Trích xuất JSON list từ phản hồi của LLM."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        return match.group(0)
    return None


def _call_llama(prompt: str) -> str:
    """Gọi OpenRouter để sinh dữ liệu bằng model Llama."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLAMA_MODEL,
        "messages": [
            {"role": "system", "content": "You are a QA data generator for fact-checking benchmarks."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "stream": False,
    }
    response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter trả về rỗng.")
    content = choices[0]["message"].get("content")
    if not content:
        raise RuntimeError("OpenRouter không trả về nội dung.")
    return content


def generate_data() -> None:
    """Gọi Llama qua OpenRouter để tạo dữ liệu kiểm thử."""
    print(f"generate_test_data: using Llama model '{LLAMA_MODEL}' qua OpenRouter.")
    all_samples: list[dict] = []

    print(f"Bắt đầu tạo 1000 mẫu dữ liệu kiểm thử. Lưu vào {OUTPUT_FILE}...")
    pbar_categories = tqdm(CATEGORIES_TO_GENERATE.items(), desc="Categories")

    for category_name, (num_samples, expected_truth) in pbar_categories:
        pbar_categories.set_description(f"Generating {category_name}")

        batch_size = 20
        num_batches = (num_samples + batch_size - 1) // batch_size
        generated_count = 0

        for _ in range(num_batches):
            samples_needed = min(batch_size, num_samples - generated_count)
            if samples_needed <= 0:
                break

            prompt = (
                MASTER_PROMPT_TEMPLATE
                .replace("<<NUM_SAMPLES>>", str(samples_needed))
                .replace("<<CATEGORY_NAME>>", category_name)
            )

            try:
                raw_text = _call_llama(prompt)
                json_text = clean_response(raw_text)

                if not json_text:
                    print(f"Lỗi: Không tìm thấy JSON trong phản hồi cho danh mục {category_name}")
                    continue

                samples = json.loads(json_text)
                for sample in samples:
                    if {"text", "ground_truth", "category"}.issubset(sample):
                        if sample["ground_truth"] == expected_truth:
                            all_samples.append(sample)
                            generated_count += 1
                        else:
                            print(
                                "Warning: Nhãn ground_truth bị sai: "
                                f"{sample['ground_truth']} (mong đợi {expected_truth})"
                            )
            except Exception as exc:
                print(f"Lỗi khi gọi API cho danh mục {category_name}: {exc}")
                print(f"Prompt snippet: {prompt[:200]}...")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for sample in all_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(f"\nHoàn tất! Đã tạo và lưu {len(all_samples)} mẫu vào {OUTPUT_FILE}.")


if __name__ == "__main__":
    generate_data()
