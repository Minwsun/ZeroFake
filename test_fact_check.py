"""Test Google Fact Check API"""
import asyncio
import os
os.environ['GOOGLE_FACT_CHECK_API_KEY'] = 'AIzaSyAc10oNxon3RWI_G0XxXO3b1BIyL7kBcFc'

from app.fact_check import call_google_fact_check, interpret_fact_check_rating

async def test():
    queries = [
        'Bill Gates vaccine microchip',
        'COVID-19 lab created Wuhan',
        'Real Madrid Champions League 2024',
        'Elon Musk DOGE department',
    ]
    for q in queries:
        print(f'\n{"="*60}')
        print(f'Query: {q}')
        print("="*60)
        results = await call_google_fact_check(q)
        if results:
            for r in results[:2]:
                rating = r.get('rating', 'N/A')
                conclusion, conf = interpret_fact_check_rating(rating)
                print(f'  Publisher: {r.get("publisher")}')
                print(f'  Rating: {rating} -> {conclusion} ({conf}%)')
                print(f'  Claim: {r.get("claim", "")[:80]}...')
        else:
            print('  No results found')

if __name__ == "__main__":
    asyncio.run(test())
