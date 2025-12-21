"""
Test 10 tin tức (5 thật, 5 giả) - Tin thời sự mới tháng 12/2024
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent_planner import load_planner_prompt, create_action_plan
from app.tool_executor import execute_tool_plan
from app.agent_synthesizer import load_synthesis_prompt, load_critic_prompt, execute_final_analysis
import datetime

# Load prompts
load_planner_prompt("prompts/planner_prompt.txt")
load_synthesis_prompt("prompts/synthesis_prompt.txt")
load_critic_prompt("prompts/critic_prompt.txt")

# 10 Test cases: 5 TRUE, 5 FAKE
TEST_CASES = [
    # === TRUE NEWS (5) ===
    {"text": "Apple Vision Pro đã được bán tại Việt Nam từ tháng 11/2024 với giá từ 99 triệu đồng", "expected": "TIN THẬT"},
    {"text": "Việt Nam có 63 tỉnh thành phố trực thuộc trung ương", "expected": "TIN THẬT"},
    {"text": "Real Madrid vô địch Champions League 2024 sau khi thắng Dortmund 2-0", "expected": "TIN THẬT"},
    {"text": "COP29 được tổ chức tại Azerbaijan vào tháng 11/2024", "expected": "TIN THẬT"},
    {"text": "Elon Musk được bổ nhiệm vào Bộ Hiệu quả Chính phủ (DOGE) của Trump tháng 11/2024", "expected": "TIN THẬT"},
    
    # === FAKE NEWS (5) ===
    {"text": "NÓNG: iPhone 17 sẽ có pin 10.000mAh và sạc đầy trong 5 phút - Apple vừa xác nhận", "expected": "TIN GIẢ"},
    {"text": "SỐC: Phát hiện xác tàu Titanic thực ra không chìm, tất cả chỉ là dàn dựng của chính phủ", "expected": "TIN GIẢ"},
    {"text": "BREAKING: WHO tuyên bố virus COVID-19 được tạo ra trong phòng thí nghiệm Mỹ", "expected": "TIN GIẢ"},
    {"text": "Việt Nam sắp đổi tên thành 'Cộng hòa Liên bang Việt Nam' vào năm 2025", "expected": "TIN GIẢ"},
    {"text": "Bill Gates thừa nhận vaccine COVID-19 có microchip theo dõi con người", "expected": "TIN GIẢ"},
]


async def test_single(text: str, expected: str, index: int):
    """Test a single claim"""
    print(f"\n{'='*60}")
    print(f"[{index}/10] Testing: {text[:60]}...")
    print(f"Expected: {expected}")
    print(f"{'='*60}")
    
    try:
        # Step 1: Planner
        plan = await create_action_plan(text, model_key="models/gemini-2.5-flash", flash_mode=True)
        
        # Step 2: Execute tools
        evidence_bundle = await execute_tool_plan(plan, "", flash_mode=True)
        
        # Step 3: Judge
        current_date = datetime.datetime.now().strftime('%Y-%m-%d')
        result = await execute_final_analysis(
            text, evidence_bundle, current_date,
            model_key="models/gemini-2.5-flash",
            flash_mode=True,
            site_query_string=""
        )
        
        conclusion = result.get("conclusion", "N/A")
        reason = result.get("reason", "")[:100]
        
        # Check result
        is_correct = (expected in conclusion) or (conclusion in expected)
        status = "✓ CORRECT" if is_correct else "✗ WRONG"
        
        print(f"\nResult: {conclusion}")
        print(f"Reason: {reason}...")
        print(f"Status: {status}")
        
        return {"text": text[:50], "expected": expected, "actual": conclusion, "correct": is_correct}
        
    except Exception as e:
        print(f"ERROR: {e}")
        return {"text": text[:50], "expected": expected, "actual": "ERROR", "correct": False}


async def main():
    print("="*60)
    print("ZEROFAKE SYSTEM TEST - 10 CLAIMS (5 TRUE, 5 FAKE)")
    print("="*60)
    
    results = []
    for i, case in enumerate(TEST_CASES, 1):
        result = await test_single(case["text"], case["expected"], i)
        results.append(result)
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    correct = sum(1 for r in results if r["correct"])
    print(f"\nAccuracy: {correct}/10 ({correct*10}%)")
    
    print("\nDetails:")
    for r in results:
        status = "✓" if r["correct"] else "✗"
        print(f"  {status} {r['expected']:10} → {r['actual']:15} | {r['text']}...")


if __name__ == "__main__":
    asyncio.run(main())
