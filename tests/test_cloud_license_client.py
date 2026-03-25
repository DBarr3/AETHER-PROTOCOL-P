"""
Tests for AetherCloud license_client.py
"""

import json
import os
import sys
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from license_client import CloudLicenseClient


@pytest.fixture
def cache_dir(tmp_path):
    return str(tmp_path / "license_cache.json")


@pytest.fixture
def client(cache_dir, monkeypatch):
    monkeypatch.setenv("AETHERCLOUD_LICENSE_KEY", "AETH-CLD-TEST-AAAA-BBBB")
    monkeypatch.setenv("AETHER_LICENSE_SERVER", "http://localhost:8085")
    monkeypatch.setenv("AETHERCLOUD_LICENSE_CACHE", cache_dir)
    c = CloudLicenseClient()
    c.cache_path = cache_dir
    return c


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


class TestCloudLicenseClient:
    @patch("license_client.urllib.request.urlopen")
    def test_valid_cloud_key_validates(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(200, {
            "valid": True,
            "plan": "pro",
            "expires_at": "2027-06-01T00:00:00+00:00",
            "client_id": "cid-cloud",
            "api_calls_remaining": 5000,
            "storage_used_mb": 100,
            "storage_limit_mb": 25000,
        })
        result = client.validate()
        assert result["valid"] is True
        assert result["plan"] == "pro"

    @patch("license_client.urllib.request.urlopen")
    def test_grace_period_on_server_unreachable(self, mock_urlopen, client, cache_dir):
        # Write cache
        cache_data = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "response": {
                "valid": True, "plan": "starter",
                "expires_at": "2027-06-01T00:00:00+00:00",
                "client_id": "cid-grace",
            },
        }
        Path(cache_dir).parent.mkdir(parents=True, exist_ok=True)
        with open(cache_dir, "w") as f:
            json.dump(cache_data, f)

        mock_urlopen.side_effect = ConnectionError("unreachable")
        result = client.validate()
        assert result["valid"] is True
        assert result["grace_mode"] is True

    @patch("license_client.urllib.request.urlopen")
    def test_usage_stats_returned_in_validate_response(self, mock_urlopen, client):
        mock_urlopen.return_value = _mock_response(200, {
            "valid": True, "plan": "enterprise",
            "expires_at": "2027-12-31T00:00:00+00:00",
            "client_id": "cid-ent",
            "api_calls_remaining": 99000,
            "storage_used_mb": 500,
            "storage_limit_mb": 100000,
        })
        result = client.validate()
        assert result["api_calls_remaining"] == 99000
        assert result["storage_limit_mb"] == 100000
