"""Test new search with DDGS().news()"""
from app.search import call_google_search

results = call_google_search('Real Madrid Champions League 2024', '')
print(f'\nTotal results: {len(results)}')
for r in results[:5]:
    source = r.get("source", "")
    title = r.get("title", "")[:60]
    print(f'  [{source}] {title}')
