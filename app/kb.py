# 22520876-NguyenNhatMinh
"""
Module 1: Knowledge Base Cache
"""
import os
import sqlite3
import faiss
import numpy as np
from typing import Optional
from sentence_transformers import SentenceTransformer

# Biến toàn cục
MODEL_BI_ENCODER = None
faiss_index = None
DIMENSION = 768  # bkai-bi-encoder dùng 768
KB_FAISS_PATH = "data/kb_vector.faiss"
KB_SQLITE_PATH = "data/kb_content.db"


def init_kb():
    """Khởi tạo Knowledge Base (FAISS + SQLite)"""
    global MODEL_BI_ENCODER, faiss_index
    
    # Tạo thư mục data nếu chưa có
    os.makedirs("data", exist_ok=True)
    
    # Khởi tạo model encoder
    if MODEL_BI_ENCODER is None:
        MODEL_BI_ENCODER = SentenceTransformer('bkai-foundation-models/vietnamese-bi-encoder')
    
    # Khởi tạo hoặc load FAISS index
    if os.path.exists(KB_FAISS_PATH):
        faiss_index = faiss.read_index(KB_FAISS_PATH)
    else:
        faiss_index = faiss.IndexFlatIP(DIMENSION)  # IP = Inner Product cho Cosine Similarity
    
    # Khởi tạo SQLite database
    conn = sqlite3.connect(KB_SQLITE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verified_news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faiss_id INTEGER UNIQUE NOT NULL,
            original_text TEXT,
            gemini_conclusion TEXT,
            gemini_reason TEXT,
            gemini_style_analysis TEXT,
            key_evidence_snippet TEXT,
            key_evidence_source TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_faiss_id ON verified_news(faiss_id)
    """)
    
    conn.commit()
    conn.close()


def search_knowledge_base(text_input: str, similarity_threshold: float = 0.85) -> Optional[dict]:
    """
    Tìm kiếm trong Knowledge Base.
    Trả về dict nếu tìm thấy, None nếu không.
    
    Threshold 0.85 = Bắt các câu tương tự về ngữ nghĩa (semantic similarity)
    Ví dụ: "iPhone 16 ra mắt" ~ "Apple công bố iPhone 16" sẽ được match
    """
    global faiss_index, MODEL_BI_ENCODER
    
    if faiss_index is None or faiss_index.ntotal == 0:
        return None
    
    # Encode text input
    vector = MODEL_BI_ENCODER.encode([text_input], normalize_embeddings=True)
    
    # Tìm vector gần nhất
    D, I = faiss_index.search(vector, 1)
    similarity = float(D[0][0])
    
    if similarity >= similarity_threshold:
        found_faiss_id = int(I[0][0])
        
        # Truy vấn SQLite
        conn = sqlite3.connect(KB_SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM verified_news WHERE faiss_id = ?", (found_faiss_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "conclusion": row["gemini_conclusion"],
                "reason": row["gemini_reason"],
                "style_analysis": row["gemini_style_analysis"],
                "key_evidence_snippet": row["key_evidence_snippet"],
                "key_evidence_source": row["key_evidence_source"],
                "cached": True
            }
    
    return None


def add_to_knowledge_base(text_input: str, gemini_result: dict):
    """
    Thêm kết quả mới vào Knowledge Base.
    """
    global faiss_index, MODEL_BI_ENCODER
    
    # Encode text input
    vector = MODEL_BI_ENCODER.encode([text_input], normalize_embeddings=True)
    
    # Thêm vào FAISS
    new_faiss_id = faiss_index.ntotal
    faiss_index.add(vector)
    faiss.write_index(faiss_index, KB_FAISS_PATH)
    
    # Thêm vào SQLite
    conn = sqlite3.connect(KB_SQLITE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO verified_news (
            faiss_id, original_text, gemini_conclusion, gemini_reason,
            gemini_style_analysis, key_evidence_snippet, key_evidence_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        new_faiss_id,
        text_input,
        gemini_result.get("conclusion", ""),
        gemini_result.get("reason", ""),
        gemini_result.get("style_analysis", ""),
        gemini_result.get("key_evidence_snippet", ""),
        gemini_result.get("key_evidence_source", "")
    ))
    
    conn.commit()
    conn.close()

