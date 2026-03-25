"""
Tests for AetherCloud api_key_middleware.py
"""

import json
import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_key_middleware import validate_api_key, invalidate_cache, _cache, _cache_lock


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the cache before each test."""
    invalidate_cache()
    yield
    invalidate_cache()


def _mock_response(status_code, body):
    import urllib.error
    if status_code == 200:
        mock = MagicMock()
        mock.read.return_value = json.dumps(body).encode("utf-8")
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        return mock
    else:
        error = urllib.error.HTTPError(
            url="http://test", code=status_code,
            msg="Error", hdrs={}, fp=MagicMock()
        )
        error.read = MagicMock(return_value=json.dumps(body).encode("utf-8"))
        return error


class TestApiKeyMiddleware:
    @patch("api_key_middleware.urllib.request.urlopen")
    def test_valid_api_key_passes_through(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(200, {
            "valid": True,
            "client_id": "cid-123",
            "calls_today": 5,
            "calls_this_month": 100,
            "rate_limit_per_min": 60,
        })
        result = validate_api_key("AETH-API-TEST-AAAA-BBBB")
        assert result["valid"] is True
        assert result["client_id"] == "cid-123"

    def test_missing_key_returns_invalid(self):
        result = validate_api_key("")
        assert result["valid"] is False
        assert "missing" in result["reason"]

    @patch("api_key_middleware.urllib.request.urlopen")
    def test_revoked_key_returns_invalid(self, mock_urlopen):
        mock_urlopen.side_effect = _mock_response(401, {
            "valid": False, "reason": "API key revoked",
        })
        result = validate_api_key("AETH-API-REVK-AAAA-BBBB")
        assert result["valid"] is False

    @patch("api_key_middleware.urllib.request.urlopen")
    def test_rate_limited_returns_429(self, mock_urlopen):
        mock_urlopen.side_effect = _mock_response(429, {
            "valid": False, "reason": "rate limit exceeded",
        })
        result = validate_api_key("AETH-API-RATE-AAAA-BBBB")
        assert result["valid"] is False
        assert "rate limit" in result["reason"]

    @patch("api_key_middleware.urllib.request.urlopen")
    def test_cache_hit_under_5ms(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(200, {
            "valid": True, "client_id": "cid-fast",
            "calls_today": 1, "calls_this_month": 10,
            "rate_limit_per_min": 60,
        })

        # First call populates cache
        validate_api_key("AETH-API-FAST-AAAA-BBBB")

        # Second call should be cache hit
        start = time.monotonic()
        result = validate_api_key("AETH-API-FAST-AAAA-BBBB")
        elapsed_ms = (time.monotonic() - start) * 1000

        assert result["valid"] is True
        assert elapsed_ms < 5, f"Cache hit took {elapsed_ms:.2f}ms (target < 5ms)"
        # urlopen should only be called once (first call)
        assert mock_urlopen.call_count == 1

    @patch("api_key_middleware.urllib.request.urlopen")
    def test_cache_invalidated_on_revoke(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(200, {
            "valid": True, "client_id": "cid-inv",
            "calls_today": 1, "calls_this_month": 10,
            "rate_limit_per_min": 60,
        })

        # Populate cache
        validate_api_key("AETH-API-INVL-AAAA-BBBB")
        assert "AETH-API-INVL-AAAA-BBBB" in _cache

        # Invalidate
        invalidate_cache("AETH-API-INVL-AAAA-BBBB")
        assert "AETH-API-INVL-AAAA-BBBB" not in _cache
