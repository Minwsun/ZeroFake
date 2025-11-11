# 22520876-NguyenNhatMinh
"""
Module 3: Feedback Loop (Học Ngược)
Quản lý DB cho các lỗi sai và cung cấp các ví dụ liên quan.
"""
import os
import sqlite3
import faiss
import numpy as np
from app.kb import MODEL_BI_ENCODER

# Biến toàn cục
faiss_feedback_index = None
FEEDBACK_FAISS_PATH = "data/feedback_vector.faiss"
FEEDBACK_DB_PATH = "data/feedback.db"
DIMENSION = 768


def init_feedback_db():
    """Khởi tạo Feedback Database (FAISS + SQLite)"""
    global faiss_feedback_index
    
    # Tạo thư mục data nếu chưa có
    os.makedirs("data", exist_ok=True)
    
    # Khởi tạo hoặc load FAISS index
    if os.path.exists(FEEDBACK_FAISS_PATH):
        faiss_feedback_index = faiss.read_index(FEEDBACK_FAISS_PATH)
    else:
        # Tạo index với ID mapping
        index = faiss.IndexFlatIP(DIMENSION)
        faiss_feedback_index = faiss.IndexIDMap2(index)
    
    # Khởi tạo SQLite database
    conn = sqlite3.connect(FEEDBACK_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_text TEXT,
            gemini_conclusion TEXT,
            gemini_reason TEXT,
            human_correction TEXT,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()


def log_human_feedback(original_text: str, gemini_conclusion: str, gemini_reason: str, 
                       human_correction: str, notes: str):
    """
    Ghi nhận phản hồi từ người dùng và thêm vào vector index.
    """
    global faiss_feedback_index
    
    # Thêm vào SQLite
    conn = sqlite3.connect(FEEDBACK_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO feedback_log (
            original_text, gemini_conclusion, gemini_reason,
            human_correction, notes
        ) VALUES (?, ?, ?, ?, ?)
    """, (original_text, gemini_conclusion, gemini_reason, human_correction, notes))
    
    feedback_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    # Thêm vào FAISS
    if MODEL_BI_ENCODER is not None and faiss_feedback_index is not None:
        vector = MODEL_BI_ENCODER.encode([original_text], normalize_embeddings=True)
        faiss_feedback_index.add_with_ids(vector, np.array([feedback_id]).astype('int64'))
        faiss.write_index(faiss_feedback_index, FEEDBACK_FAISS_PATH)


def get_relevant_examples(text_input: str, limit: int = 3) -> str:
    """
    Lấy các ví dụ lỗi liên quan nhất từ feedback database.
    Trả về chuỗi formatted để chèn vào prompt.
    """
    global faiss_feedback_index
    
    if faiss_feedback_index is None or faiss_feedback_index.ntotal == 0:
        return "Không có lỗi nào được ghi nhận."
    
    # Encode text input
    if MODEL_BI_ENCODER is None:
        return "Không có lỗi nào được ghi nhận."
    
    vector = MODEL_BI_ENCODER.encode([text_input], normalize_embeddings=True)
    
    # Tìm các lỗi liên quan nhất
    D, I = faiss_feedback_index.search(vector, limit)
    found_ids = tuple(I[0])
    
    if len(found_ids) == 0:
        return "Không có lỗi tương tự được ghi nhận."
    
    # Truy vấn SQLite
    conn = sqlite3.connect(FEEDBACK_DB_PATH)
    cursor = conn.cursor()
    
    placeholders = ','.join(['?'] * len(found_ids))
    cursor.execute(f"""
        SELECT * FROM feedback_log WHERE id IN ({placeholders})
        ORDER BY created_at DESC
    """, found_ids)
    
    examples = cursor.fetchall()
    conn.close()
    
    # Format examples
    example_str = ""
    for idx, example in enumerate(examples, 1):
        example_str += f"""
Ví dụ {idx}:
- Tin Gốc: "{example[1]}"
- Kết quả Gemini (SAI): {example[2]} - {example[3]}
- Kết quả Đúng: {example[4]}
- Ghi chú: {example[5] if example[5] else "Không có ghi chú"}

"""
    
    return example_str.strip()

