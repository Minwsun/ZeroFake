"""
Test script to verify:
1. Google Fact Check API is working
2. Priority News Search (Google News, Bing) is working
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Add API key for testing
os.environ["GOOGLE_FACT_CHECK_API_KEY"] = "AIzaSyAc10oNxon3RWI_G0XxXO3b1BIyL7kBcFc"


async def test_fact_check():
    print("=" * 60)
    print("TEST 1: GOOGLE FACT CHECK API")
    print("=" * 60)
    
    from app.fact_check import call_google_fact_check, interpret_fact_check_rating
    
    test_queries = [
        "Bill Gates vaccine microchip",
        "COVID-19 lab made",
        "Vietnam 63 provinces",
    ]
    
    for query in test_queries:
        print(f"\n[Query] {query}")
        results = await call_google_fact_check(query)
        
        if results:
            print(f"  → Found {len(results)} fact checks:")
            for r in results[:2]:
                conclusion, conf = interpret_fact_check_rating(r.get("rating", ""))
                print(f"    • {r.get('publisher', 'Unknown')}: {r.get('rating', 'N/A')}")
                print(f"      Interpreted: {conclusion} ({conf}%)")
        else:
            print("  → No fact checks found")


def test_priority_search():
    print("\n" + "=" * 60)
    print("TEST 2: PRIORITY NEWS SEARCH")
    print("=" * 60)
    
    from app.search import call_duckduckgo_search
    
    test_query = "Real Madrid Champions League 2024 winner"
    
    print(f"\n[Query] {test_query}")
    print("Watch for '[DDG] Priority News Search' in output...")
    print("-" * 40)
    
    results = call_duckduckgo_search(test_query)
    
    print("-" * 40)
    print(f"Total results: {len(results)}")
    
    # Show first 3 results
    for i, r in enumerate(results[:3], 1):
        source = r.get("source", "Unknown")
        title = r.get("title", "")[:60]
        print(f"{i}. [{source}] {title}...")


if __name__ == "__main__":
    print("\n🔹 VERIFYING DUAL FLOW SYSTEM 🔹\n")
    
    # Test Fact Check API
    asyncio.run(test_fact_check())
    
    # Test Priority Search
    test_priority_search()
    
    print("\n" + "=" * 60)
    print("VERIFICATION COMPLETE")
    print("=" * 60)
