"""
Firebase Firestore client for ZeroFake KB Cache
Uses REST API with API Key for efficient O(1) lookups
Strategy:
- KB Cache: Uses claim hash as document ID for O(1) lookup (minimal reads)
- Result Logs: Append-only collection for analytics (write-only, no read from frontend)
- History: Read from browser localStorage only (no Firebase reads for display)
"""

import hashlib
import httpx
import os
from datetime import datetime
from typing import Optional, Dict, Any

# Firebase configuration
FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY", "")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "zerofake-2025")

# Firestore REST API base URL
FIRESTORE_BASE_URL = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents"

# In-memory cache to reduce Firebase reads (this is the PRIMARY read source)
_memory_cache: Dict[str, Dict[str, Any]] = {}
_cache_max_size = 1000  # Max entries in memory cache


def get_claim_hash(claim: str) -> str:
    """Generate a hash for the claim text to use as document ID"""
    # Normalize: lowercase, strip whitespace
    normalized = claim.lower().strip()
    # Create SHA256 hash and take first 32 chars for shorter ID
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:32]


async def get_cached_result(claim: str) -> Optional[Dict[str, Any]]:
    """
    Get cached result for a claim
    PRIORITY: Memory cache first, then Firebase (only 1 read per unique claim)
    """
    claim_hash = get_claim_hash(claim)
    
    # Check memory cache first - NO FIREBASE READ if found
    if claim_hash in _memory_cache:
        print(f"[Cache] Memory hit: {claim_hash[:8]}...")
        return _memory_cache[claim_hash]
    
    if not FIREBASE_API_KEY:
        return None
    
    # Firebase O(1) lookup by document ID (claim hash)
    try:
        url = f"{FIRESTORE_BASE_URL}/kb_cache/{claim_hash}?key={FIREBASE_API_KEY}"
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                result = _parse_firestore_document(data)
                
                # Store in memory cache for future requests
                _add_to_memory_cache(claim_hash, result)
                print(f"[Firebase] KB cache hit: {claim_hash[:8]}...")
                return result
            elif response.status_code == 404:
                return None
            else:
                print(f"[Firebase] Error getting cache: {response.status_code}")
                return None
                
    except Exception as e:
        print(f"[Firebase] Exception getting cache: {e}")
        return None


async def save_to_cache(
    claim: str,
    conclusion: str,
    reason: str,
    source: str = "AI",
    confidence: float = 0.8,
    user_ip: str = ""
) -> bool:
    """
    Save result to Firebase Firestore KB cache
    Uses claim hash as document ID for O(1) lookup
    """
    if not FIREBASE_API_KEY:
        return False
    
    claim_hash = get_claim_hash(claim)
    now = datetime.utcnow().isoformat() + "Z"
    
    doc_data = {
        "fields": {
            "original_claim": {"stringValue": claim},
            "normalized_claim": {"stringValue": claim.lower().strip()},
            "conclusion": {"stringValue": conclusion},
            "reason": {"stringValue": reason},
            "source": {"stringValue": source},
            "confidence": {"doubleValue": confidence},
            "user_ip": {"stringValue": user_ip},
            "created_at": {"timestampValue": now},
            "updated_at": {"timestampValue": now}
        }
    }
    
    try:
        url = f"{FIRESTORE_BASE_URL}/kb_cache/{claim_hash}?key={FIREBASE_API_KEY}"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.patch(url, json=doc_data)
            
            if response.status_code in [200, 201]:
                # Update memory cache
                cache_entry = {
                    "original_claim": claim,
                    "conclusion": conclusion,
                    "reason": reason,
                    "source": source,
                    "confidence": confidence
                }
                _add_to_memory_cache(claim_hash, cache_entry)
                print(f"[Firebase] Saved KB cache: {claim_hash[:8]}...")
                return True
            else:
                print(f"[Firebase] Error saving cache: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"[Firebase] Exception saving cache: {e}")
        return False


async def save_result_log(
    claim: str,
    conclusion: str,
    reason: str,
    source: str = "AI",
    user_feedback: str = "",
    user_ip: str = "",
    session_id: str = ""
) -> bool:
    """
    Save full result log to Firebase (append-only, for analytics)
    This is separate from KB cache - used for tracking all requests
    """
    if not FIREBASE_API_KEY:
        return False
    
    now = datetime.utcnow()
    log_id = f"{now.strftime('%Y%m%d%H%M%S')}_{get_claim_hash(claim)[:8]}"
    
    doc_data = {
        "fields": {
            "claim": {"stringValue": claim},
            "conclusion": {"stringValue": conclusion},
            "reason": {"stringValue": reason},
            "source": {"stringValue": source},
            "user_feedback": {"stringValue": user_feedback},
            "user_ip": {"stringValue": user_ip},
            "session_id": {"stringValue": session_id},
            "timestamp": {"timestampValue": now.isoformat() + "Z"}
        }
    }
    
    try:
        url = f"{FIRESTORE_BASE_URL}/result_logs/{log_id}?key={FIREBASE_API_KEY}"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.patch(url, json=doc_data)
            
            if response.status_code in [200, 201]:
                print(f"[Firebase] Saved result log: {log_id}")
                return True
            else:
                print(f"[Firebase] Error saving log: {response.status_code}")
                return False
                
    except Exception as e:
        print(f"[Firebase] Exception saving log: {e}")
        return False


async def update_from_feedback(
    claim: str,
    human_correction: str,
    reason: str = "",
    user_ip: str = ""
) -> bool:
    """
    Update KB cache from user feedback
    Replaces AI result with human-verified result
    """
    # Check memory cache first (no Firebase read)
    claim_hash = get_claim_hash(claim)
    existing = _memory_cache.get(claim_hash)
    
    # Use existing reason if not provided
    if not reason and existing:
        reason = existing.get("reason", "Đã được người dùng xác minh")
    elif not reason:
        reason = "Đã được người dùng xác minh"
    
    return await save_to_cache(
        claim=claim,
        conclusion=human_correction,
        reason=reason,
        source="HUMAN",
        confidence=1.0,
        user_ip=user_ip
    )


def _add_to_memory_cache(claim_hash: str, data: Dict[str, Any]):
    """Add entry to memory cache with LRU eviction"""
    if len(_memory_cache) >= _cache_max_size:
        oldest_key = next(iter(_memory_cache))
        del _memory_cache[oldest_key]
    _memory_cache[claim_hash] = data


def _parse_firestore_document(doc: Dict) -> Dict[str, Any]:
    """Parse Firestore document fields into simple dict"""
    fields = doc.get("fields", {})
    result = {}
    
    for key, value in fields.items():
        if "stringValue" in value:
            result[key] = value["stringValue"]
        elif "doubleValue" in value:
            result[key] = value["doubleValue"]
        elif "integerValue" in value:
            result[key] = int(value["integerValue"])
        elif "booleanValue" in value:
            result[key] = value["booleanValue"]
        elif "timestampValue" in value:
            result[key] = value["timestampValue"]
        else:
            result[key] = str(value)
    
    return result


def clear_memory_cache():
    """Clear in-memory cache"""
    global _memory_cache
    _memory_cache = {}
    print("[Firebase] Memory cache cleared")


def preload_to_memory(claim: str, data: Dict[str, Any]):
    """Preload a result to memory cache (used when saving results)"""
    claim_hash = get_claim_hash(claim)
    _add_to_memory_cache(claim_hash, data)
