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


async def call_google_fact_check(query: str, language_code: str = "vi") -> list:
    """
    Call Google Fact Check Tool API to find existing fact checks.
    
    Args:
        query: The claim to search for
        language_code: Language code (vi for Vietnamese, en for English)
    
    Returns:
        List of fact check results with rating and source
    """
    if not FACT_CHECK_API_KEY:
        print("[FACT-CHECK] API key not configured")
        return []
    
    results = []
    
    try:
        params = {
            "key": FACT_CHECK_API_KEY,
            "query": query,
            "languageCode": language_code,
            "pageSize": 10
        }
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(FACT_CHECK_BASE_URL, params=params)
            
            if response.status_code == 200:
                data = response.json()
                claims = data.get("claims", [])
                
                for claim in claims:
                    claim_text = claim.get("text", "")
                    
                    for review in claim.get("claimReview", []):
                        result = {
                            "claim": claim_text,
                            "publisher": review.get("publisher", {}).get("name", "Unknown"),
                            "url": review.get("url", ""),
                            "rating": review.get("textualRating", ""),
                            "title": review.get("title", ""),
                            "review_date": review.get("reviewDate", ""),
                            "language": review.get("languageCode", language_code)
                        }
                        results.append(result)
                
                if results:
                    print(f"[FACT-CHECK] Found {len(results)} existing fact checks")
                else:
                    print(f"[FACT-CHECK] No existing fact checks found for: {query[:50]}...")
                    
            elif response.status_code == 403:
                print(f"[FACT-CHECK] API access denied (403)")
            else:
                print(f"[FACT-CHECK] API error: {response.status_code}")
                
    except httpx.TimeoutException:
        print("[FACT-CHECK] API timeout")
    except Exception as e:
        print(f"[FACT-CHECK] Error: {e}")
    
    # Also try English if Vietnamese returns no results
    if not results and language_code == "vi":
        print("[FACT-CHECK] Trying English search...")
        return await call_google_fact_check(query, "en")
    
    return results


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
