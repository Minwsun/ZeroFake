"""
Google Fact Check Tool API Integration
API Documentation: https://developers.google.com/fact-check/tools/api/reference/rest
"""
import os
import httpx
from typing import Optional

# API Configuration - Key must be set in .env
FACT_CHECK_API_KEY = os.getenv("GOOGLE_FACT_CHECK_API_KEY", "")
FACT_CHECK_BASE_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


async def call_google_fact_check(query: str, language_code: str = "en") -> list:
    """
    Call Google Fact Check Tool API with MULTIPLE QUERIES in both languages.
    
    Strategy:
    1. Extract key entities (names, events, numbers)
    2. Search with 3 English variations
    3. Search with 3 Vietnamese variations (if original is Vietnamese)
    4. Merge and deduplicate results
    """
    if not FACT_CHECK_API_KEY:
        print("[FACT-CHECK] ⚠️ API key not configured")
        return []
    
    # Generate multiple search queries
    queries = _generate_fact_check_queries(query)
    
    all_results = []
    seen_urls = set()
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        for q, lang in queries[:6]:  # Max 6 queries (3 EN + 3 VN)
            try:
                params = {
                    "key": FACT_CHECK_API_KEY,
                    "query": q,
                    "languageCode": lang,
                    "pageSize": 5
                }
                
                response = await client.get(FACT_CHECK_BASE_URL, params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    claims = data.get("claims", [])
                    
                    for claim in claims:
                        claim_text = claim.get("text", "")
                        
                        for review in claim.get("claimReview", []):
                            url = review.get("url", "")
                            if url in seen_urls:
                                continue
                            seen_urls.add(url)
                            
                            result = {
                                "claim": claim_text,
                                "publisher": review.get("publisher", {}).get("name", "Unknown"),
                                "url": url,
                                "rating": review.get("textualRating", ""),
                                "title": review.get("title", ""),
                                "review_date": review.get("reviewDate", ""),
                                "language": review.get("languageCode", lang),
                                "matched_query": q
                            }
                            all_results.append(result)
                            
            except Exception as e:
                print(f"[FACT-CHECK] Query error: {e}")
                continue
    
    if all_results:
        print(f"[FACT-CHECK] ✓ Found {len(all_results)} fact checks")
    else:
        print(f"[FACT-CHECK] No fact checks found")
    
    return all_results


def _generate_fact_check_queries(text: str) -> list:
    """
    Generate multiple search queries from claim text.
    Returns: [(query, language_code), ...]
    """
    import re
    
    queries = []
    
    # Extract key entities
    # Keep proper nouns (capitalized words), numbers, years
    entities = re.findall(r'[A-Z][a-zA-Z]+|[A-Z]+|[0-9]{4}|[0-9]+', text)
    entities_str = " ".join(entities) if entities else ""
    
    # Vietnamese to English key phrases
    vn_to_en = {
        "vô địch": "champion won",
        "thắng": "beat defeated",
        "thua": "lost",
        "bổ nhiệm": "appointed",
        "qua đời": "died",
        "ra mắt": "launched",
        "bán": "sold available",
        "tổ chức": "hosted held",
        "vaccine": "vaccine",
        "microchip": "microchip",
        "virus": "virus",
        "thừa nhận": "admitted",
        "tuyên bố": "announced claimed",
        "Champions League": "Champions League",
        "COP29": "COP 29",
        "DOGE": "DOGE Department Government Efficiency",
    }
    
    # Translate to English
    en_text = text
    for vn, en in vn_to_en.items():
        en_text = re.sub(vn, en, en_text, flags=re.IGNORECASE)
    
    # Clean up
    en_text = re.sub(r'[^\w\s\-]', ' ', en_text)
    en_text = re.sub(r'\s+', ' ', en_text).strip()
    
    # Generate English queries
    if entities_str:
        queries.append((entities_str, "en"))  # Just entities
    queries.append((en_text[:100], "en"))  # Translated claim
    queries.append((f"{entities_str} fact check", "en"))  # With fact check keyword
    
    # Generate Vietnamese queries
    vn_text = re.sub(r'[^\w\s\-àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]', ' ', text, flags=re.IGNORECASE)
    vn_text = re.sub(r'\s+', ' ', vn_text).strip()
    
    queries.append((vn_text[:80], "vi"))
    if entities_str:
        queries.append((f"{entities_str} thật hay giả", "vi"))
    
    return queries




def _extract_english_query(text: str) -> str:
    """Extract English-friendly keywords from Vietnamese text for fact check search."""
    import re
    
    # Common Vietnamese to English mappings for fact check topics
    translations = {
        "vô địch": "champion winner",
        "thắng": "won defeated",
        "thua": "lost",
        "ra mắt": "launch release",
        "qua đời": "died death",
        "bổ nhiệm": "appointed",
        "từ chức": "resigned",
        "thừa nhận": "admitted confirmed",
        "tổ chức": "hosted held",
        "vaccine": "vaccine",
        "microchip": "microchip",
        "virus": "virus",
        "tạo ra": "created made",
        "phát hiện": "discovered found",
        "đổi tên": "renamed changed name",
        "giả": "fake false",
        "thật": "true real",
    }
    
    result = text
    for vn, en in translations.items():
        result = re.sub(vn, en, result, flags=re.IGNORECASE)
    
    # Keep proper nouns, numbers, and remove Vietnamese particles
    result = re.sub(r'[^\w\s\-\./]', ' ', result)
    result = re.sub(r'\s+', ' ', result).strip()
    
    # Keep only if substantial content remains
    if len(result) > 15:
        return result
    return ""


def interpret_fact_check_rating(rating: str) -> tuple[str, int]:
    """
    Interpret fact check rating to conclusion and confidence.
    
    Returns:
        (conclusion: "TIN THẬT" | "TIN GIẢ", confidence: 0-100)
    """
    rating_lower = rating.lower()
    
    # TRUE indicators
    true_keywords = ["true", "correct", "accurate", "đúng", "chính xác", "thật"]
    # FALSE indicators  
    false_keywords = ["false", "fake", "incorrect", "sai", "giả", "bịa", "misleading", "pants on fire", "hoax"]
    # PARTIAL indicators
    partial_keywords = ["partly", "partial", "mixed", "half", "một phần"]
    
    for kw in false_keywords:
        if kw in rating_lower:
            return ("TIN GIẢ", 90)
    
    for kw in true_keywords:
        if kw in rating_lower:
            return ("TIN THẬT", 90)
    
    for kw in partial_keywords:
        if kw in rating_lower:
            return ("TIN GIẢ", 70)  # Partial = leaning fake
    
    # Unknown rating, can't determine
    return ("", 0)


def format_fact_check_evidence(results: list) -> str:
    """Format fact check results as evidence string for prompts."""
    if not results:
        return ""
    
    lines = ["[FACT CHECK RESULTS FROM TRUSTED SOURCES]"]
    
    for i, r in enumerate(results[:5], 1):
        conclusion, _ = interpret_fact_check_rating(r.get("rating", ""))
        lines.append(f"\n{i}. {r.get('publisher', 'Unknown')}:")
        lines.append(f"   Claim: {r.get('claim', '')[:100]}...")
        lines.append(f"   Rating: {r.get('rating', 'N/A')}")
        if conclusion:
            lines.append(f"   Interpreted: {conclusion}")
        lines.append(f"   Source: {r.get('url', '')}")
    
    return "\n".join(lines)
