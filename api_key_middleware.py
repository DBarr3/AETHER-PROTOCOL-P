"""
AetherCloud — API Key Validation Middleware

Checks X-Aether-API-Key header on API routes.
Uses 60-second in-memory cache for < 5ms latency on cache hits.
Validates against the Aether License Server on cache miss.

Aether Systems LLC — Patent Pending
"""

import json
import logging
import os
import time
import threading
import urllib.request
import urllib.error

logger = logging.getLogger("aethercloud.apikey")

LICENSE_SERVER = os.getenv(
    "AETHER_LICENSE_SERVER",
    "https://aethersecurity.net/api/license",
).rstrip("/")

# In-memory cache: { key_str: { "result": dict, "cached_at": float } }
_cache = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 60  # seconds


def validate_api_key(key: str) -> dict:
    """
    Validate an API key. Returns dict with 'valid', 'client_id', etc.
    Uses in-memory cache for fast lookups (< 5ms on hit).
    """
    if not key:
        return {"valid": False, "reason": "missing API key"}

    key = key.strip().upper()

    # Check cache
    with _cache_lock:
        cached = _cache.get(key)
        if cached and (time.time() - cached["cached_at"]) < _CACHE_TTL:
            return cached["result"]

    # Cache miss — validate against license server
    try:
        req = urllib.request.Request(
            f"{LICENSE_SERVER}/license/api/validate",
            headers={
                "X-Aether-API-Key": key,
            },
            method="GET",
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))

            # Cache successful result
            with _cache_lock:
                _cache[key] = {"result": result, "cached_at": time.time()}

            return result

    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            pass
        return {
            "valid": False,
            "reason": body.get("reason", f"HTTP {e.code}"),
            "status_code": e.code,
        }
    except Exception as exc:
        logger.warning("API key validation failed: %s", exc)
        # On network error, check if we have a stale cache entry
        with _cache_lock:
            stale = _cache.get(key)
            if stale:
                return stale["result"]
        return {"valid": False, "reason": "license server unreachable"}


def invalidate_cache(key: str = None):
    """Invalidate cache for a specific key or all keys."""
    with _cache_lock:
        if key:
            _cache.pop(key.strip().upper(), None)
        else:
            _cache.clear()


def cleanup_cache():
    """Remove expired entries from cache."""
    now = time.time()
    with _cache_lock:
        expired = [k for k, v in _cache.items() if now - v["cached_at"] > _CACHE_TTL * 2]
        for k in expired:
            del _cache[k]
