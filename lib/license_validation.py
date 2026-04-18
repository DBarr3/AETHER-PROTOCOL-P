"""
License-validation helper used by the /api/license/... FastAPI routes.

Queries public.users in Supabase for a given AETH-CLD-* license key and
maps subscription_status to the response contract the desktop client
(license_client.py) expects.

Never logs full license keys — always uses the last-4 redaction pattern
(mask as "****-XXXX") to match the existing convention at api_server.py
line 1096.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

log = logging.getLogger("aethercloud.license")

# License key format: matches desktop/license_client.py KEY_PATTERN exactly.
KEY_PATTERN = re.compile(r"^AETH-CLD-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")


class MalformedKeyError(ValueError):
    """Raised when a license key does not match AETH-CLD-XXXX-XXXX-XXXX."""


class UpstreamError(Exception):
    """Raised when the Supabase query fails (network, auth, DB error)."""


def last4(key: str) -> str:
    """Redact a license key for logging. Returns '****-XXXX' (last 4 chars).

    Matches the mask pattern used at api_server.py:1096.
    Empty / too-short inputs return '****'.
    """
    if not key or len(key) < 4:
        return "****"
    return f"****-{key[-4:]}"


# Module-level client cache. Created lazily on first use; reused thereafter.
# Do NOT instantiate a client per request — the brief forbids it explicitly.
_client = None


def get_supabase_client():
    """Return a lazily-initialized Supabase client.

    Reads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from the environment.
    The service role key is required because this route queries the users
    table, which has RLS enabled (only service role bypasses RLS).

    Raises UpstreamError if either env var is missing.
    """
    global _client
    if _client is not None:
        return _client

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise UpstreamError("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")

    # Lazy import so tests that patch get_supabase_client don't force
    # `supabase` to be importable.
    from supabase import create_client

    _client = create_client(url, key)
    return _client


def _reset_client_for_tests() -> None:
    """Test hook: clears the cached client. Not for production use."""
    global _client
    _client = None


# subscription_status → (valid, reason) for the response payload.
# 'active' is the only status that yields valid=True.
_STATUS_MAP: dict[str, tuple[bool, Optional[str]]] = {
    "active":   (True,  None),
    "past_due": (False, "subscription_past_due"),
    "canceled": (False, "subscription_canceled"),
}


def _map_status(status: str) -> tuple[bool, Optional[str]]:
    """Map subscription_status column value to (valid, reason)."""
    return _STATUS_MAP.get(status or "", (False, "subscription_inactive"))


def validate_license(key: str) -> dict:
    """Validate a license key against Supabase public.users.

    Normalizes input (strip + upper) before regex check. Queries the users
    table for tier, subscription_status, email, current_period_end. Returns
    the response dict matching the Sequence 1 contract.

    Args:
        key: license key string (any case, any surrounding whitespace).

    Returns:
        Response dict with keys: valid, plan, expires_at, client_id,
        grace_mode, reason. Never includes license_key, tier, status,
        or email field names — the desktop client parses exactly these
        names.

    Raises:
        MalformedKeyError: key does not match KEY_PATTERN after normalization.
        UpstreamError: Supabase unreachable or returned an error.
    """
    normalized = (key or "").strip().upper()
    if not KEY_PATTERN.match(normalized):
        raise MalformedKeyError("key does not match AETH-CLD-XXXX-XXXX-XXXX")

    try:
        client = get_supabase_client()
        resp = (
            client.table("users")
            .select("tier, subscription_status, email, current_period_end")
            .eq("license_key", normalized)
            .limit(1)
            .execute()
        )
    except UpstreamError:
        raise
    except Exception as e:
        log.error("Supabase query failed for key=%s: %s", last4(normalized), e)
        raise UpstreamError("supabase query failed") from e

    rows = getattr(resp, "data", None) or []
    if not rows:
        log.info("License not found: key=%s", last4(normalized))
        return {
            "valid": False,
            "plan": None,
            "expires_at": None,
            "client_id": None,
            "grace_mode": False,
            "reason": "license_not_found",
        }

    row = rows[0]
    status = row.get("subscription_status") or ""
    valid, reason = _map_status(status)

    log.info(
        "License validated: key=%s plan=%s status=%s valid=%s",
        last4(normalized), row.get("tier"), status, valid,
    )

    return {
        "valid": valid,
        "plan": row.get("tier"),
        "expires_at": row.get("current_period_end"),
        "client_id": row.get("email"),
        "grace_mode": False,
        "reason": reason,
    }
