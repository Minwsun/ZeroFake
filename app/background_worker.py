# app/background_worker.py
"""
🚑 Background Self-Healing Worker

Chạy ngầm để tự động cập nhật các tin:
- STALE (sắp hết hạn) → Làm mới trước khi người dùng hỏi
- HOT categories (finance, breaking_news) → Ưu tiên cao

Cách chạy:
    python -m app.background_worker

Hoặc tích hợp với APScheduler/Celery cho production.
"""
import asyncio
import time
import sqlite3
from datetime import datetime
from typing import Optional

# Import từ các module khác
from app.kb import KB_SQLITE_PATH, TTL_CONFIG, check_cache_status, update_cache_entry


# Cấu hình Worker
WORKER_INTERVAL_SECONDS = 300  # Chạy mỗi 5 phút
HIGH_PRIORITY_CATEGORIES = ["finance", "breaking_news", "sports", "politics"]
MAX_ITEMS_PER_RUN = 10  # Giới hạn số tin xử lý mỗi lần chạy


async def verify_claim_fresh(claim_text: str) -> Optional[dict]:
    """
    Chạy lại quy trình verify cho một claim.
    Trả về kết quả mới từ AI pipeline.
    """
    try:
        from app.agent_planner import create_action_plan
        from app.tool_executor import execute_tool_plan
        from app.agent_synthesizer import execute_final_analysis
        from app.search import get_site_query
        
        current_date = datetime.now().strftime('%Y-%m-%d')
        
        # Step 1: Create action plan
        plan = await create_action_plan(claim_text, flash_mode=True)
        
        # Step 2: Execute tool plan (search evidence)
        site_query = get_site_query("config.json") if True else ""
        evidence_bundle = await execute_tool_plan(plan, site_query, flash_mode=True)
        
        # Step 3: Run final analysis
        result = await execute_final_analysis(
            claim_text,
            evidence_bundle,
            current_date,
            flash_mode=True
        )
        
        return result
        
    except Exception as e:
        print(f"[Worker] ❌ Lỗi khi verify: {e}")
        return None


def get_stale_entries() -> list[dict]:
    """
    Lấy danh sách các tin cần cập nhật:
    1. Tin STALE (sắp hết hạn)
    2. Ưu tiên categories hot
    3. Ưu tiên tin có hit_count cao
    """
    conn = sqlite3.connect(KB_SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Lấy tất cả tin trong các category ưu tiên cao
    placeholders = ",".join("?" * len(HIGH_PRIORITY_CATEGORIES))
    cursor.execute(f"""
        SELECT id, faiss_id, original_text, topic_category, last_verified_at, 
               COALESCE(hit_count, 0) as hit_count
        FROM verified_news 
        WHERE topic_category IN ({placeholders})
        ORDER BY hit_count DESC, last_verified_at ASC
        LIMIT ?
    """, (*HIGH_PRIORITY_CATEGORIES, MAX_ITEMS_PER_RUN * 2))
    
    rows = cursor.fetchall()
    conn.close()
    
    # Filter chỉ lấy tin STALE
    stale_entries = []
    for row in rows:
        row_dict = dict(row)
        status = check_cache_status(row_dict)
        if status == "STALE":
            stale_entries.append(row_dict)
            if len(stale_entries) >= MAX_ITEMS_PER_RUN:
                break
    
    return stale_entries


async def heal_entry(entry: dict) -> bool:
    """
    'Chữa lành' một entry bằng cách verify lại.
    Trả về True nếu thành công.
    """
    claim_text = entry.get("original_text", "")
    faiss_id = entry.get("faiss_id")
    
    if not claim_text or faiss_id is None:
        return False
    
    print(f"[Worker] 🔄 Đang cập nhật: {claim_text[:60]}...")
    
    # Chạy verify lại
    new_result = await verify_claim_fresh(claim_text)
    
    if new_result and new_result.get("conclusion"):
        # Cập nhật vào database
        update_cache_entry(faiss_id, new_result)
        print(f"[Worker] ✅ Đã cập nhật: {new_result.get('conclusion')}")
        return True
    else:
        # Fallback: Chỉ update timestamp để đánh dấu đã check
        conn = sqlite3.connect(KB_SQLITE_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE verified_news SET last_verified_at = CURRENT_TIMESTAMP WHERE faiss_id = ?",
            (faiss_id,)
        )
        conn.commit()
        conn.close()
        print(f"[Worker] ⚠️ Không có kết quả mới, chỉ update timestamp")
        return False


async def run_healing_cycle():
    """
    Một chu kỳ chữa lành: Quét và cập nhật các tin STALE.
    """
    print(f"\n{'='*60}")
    print(f"[Worker] 🚑 Bắt đầu chu kỳ Self-Healing - {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}")
    
    # Lấy danh sách tin cần cập nhật
    stale_entries = get_stale_entries()
    
    if not stale_entries:
        print(f"[Worker] 💚 Không có tin nào cần cập nhật!")
        return
    
    print(f"[Worker] 📋 Tìm thấy {len(stale_entries)} tin STALE cần cập nhật")
    
    # Xử lý từng tin
    success_count = 0
    for entry in stale_entries:
        try:
            if await heal_entry(entry):
                success_count += 1
        except Exception as e:
            print(f"[Worker] ❌ Lỗi: {e}")
        
        # Nghỉ giữa các request để tránh rate limit
        await asyncio.sleep(2)
    
    print(f"[Worker] 📊 Hoàn thành: {success_count}/{len(stale_entries)} tin đã được cập nhật")


async def run_worker_loop():
    """
    Vòng lặp chính của Worker.
    Chạy liên tục, nghỉ giữa các chu kỳ.
    """
    print(f"[Worker] 🚀 Background Self-Healing Worker đã khởi động!")
    print(f"[Worker] ⏰ Interval: {WORKER_INTERVAL_SECONDS}s ({WORKER_INTERVAL_SECONDS//60} phút)")
    print(f"[Worker] 🎯 Priority categories: {HIGH_PRIORITY_CATEGORIES}")
    
    while True:
        try:
            await run_healing_cycle()
        except Exception as e:
            print(f"[Worker] ❌ Lỗi chu kỳ: {e}")
        
        print(f"[Worker] 💤 Ngủ {WORKER_INTERVAL_SECONDS//60} phút...")
        await asyncio.sleep(WORKER_INTERVAL_SECONDS)


def run_once():
    """
    Chạy một lần duy nhất (cho testing hoặc cron job).
    """
    asyncio.run(run_healing_cycle())


if __name__ == "__main__":
    # Chạy worker liên tục
    asyncio.run(run_worker_loop())
