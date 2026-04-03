"""
AetherCloud — License Validation Client

Validates AetherCloud license key against the Aether License Server.
Implements 72-hour grace period using cached responses when server is unreachable.

License check happens ONCE at startup. Does NOT block server operation.

Aether Systems LLC — Patent Pending
"""

import json
import logging
import os
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("aethercloud.license")

KEY_PATTERN = re.compile(r"^AETH-CLD-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")


class CloudLicenseClient:
    """
    Manages AetherCloud license validation against the Aether License Server.
    Validates on startup. Falls back to cached response with 72h grace period.
    """

    def __init__(self):
        self.key = os.getenv("AETHERCLOUD_LICENSE_KEY", "").strip()
        self.server = os.getenv(
            "AETHER_LICENSE_SERVER",
            "https://aethersecurity.net/api/license",
        ).rstrip("/")
        self.cache_path = os.getenv(
            "AETHERCLOUD_LICENSE_CACHE",
            str(Path(__file__).parent / "data" / "license_cache.json"),
        )
        self.grace_period_hours = 72

    def validate(self) -> dict:
        """Validate the license key. Returns dict with valid, plan, etc."""
        if not self.key:
            return {
                "valid": False,
                "reason": "no key configured",
                "plan": None,
                "expires_at": None,
                "client_id": None,
                "grace_mode": False,
            }

        # Try remote validation
        try:
            result = self._validate_remote()
            if result.get("valid"):
                self._save_cache(result)
            return result
        except Exception as exc:
            logger.warning("License server unreachable: %s", exc)
            cached = self._load_cache()
            if cached:
                cached["grace_mode"] = True
                return cached
            return {
                "valid": False,
                "reason": "server unreachable, no cached license",
                "plan": None,
                "expires_at": None,
                "client_id": None,
                "grace_mode": False,
            }

    def _validate_remote(self) -> dict:
        url = f"{self.server}/license/cloud/validate"
        payload = json.dumps({
            "key": self.key,
            "version": os.getenv("APP_VERSION", "0.8.9"),
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                data.setdefault("grace_mode", False)
                return data
        except urllib.error.HTTPError as e:
            body = {}
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:
                pass

            if e.code in (401, 403):
                return {
                    "valid": False,
                    "reason": body.get("reason", "license invalid"),
                    "plan": None, "expires_at": None,
                    "client_id": None, "grace_mode": False,
                }
            elif e.code == 429:
                raise Exception("rate limited") from e
            else:
                raise

    def _load_cache(self) -> dict or None:
        try:
            cache_file = Path(self.cache_path)
            if not cache_file.exists():
                return None
            with open(cache_file, "r") as f:
                data = json.load(f)
            cached_at = data.get("cached_at")
            if not cached_at:
                return None
            cached_time = datetime.fromisoformat(cached_at)
            if cached_time.tzinfo is None:
                cached_time = cached_time.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_elapsed = (now - cached_time).total_seconds() / 3600
            if hours_elapsed > self.grace_period_hours:
                return None
            return data.get("response", data)
        except Exception as e:
            logger.warning("Failed to load license cache: %s", e)
            return None

    def _save_cache(self, response: dict) -> None:
        try:
            cache_file = Path(self.cache_path)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "response": response,
            }
            with open(cache_file, "w") as f:
                json.dump(cache_data, f, indent=2)
            # Restrict permissions to owner-only (prevents info disclosure)
            try:
                import os as _os
                cache_file.chmod(0o600)
            except Exception:
                pass  # Windows may not support chmod — acceptable
        except Exception as e:
            logger.warning("Failed to save license cache: %s", e)


# Module-level instance — validated on import
_license_info = {}


def get_license_info() -> dict:
    """Get the cached license info (set at startup)."""
    return _license_info
