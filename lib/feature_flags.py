"""
Feature flags for the UVT stack rollout.

Three precedence tiers, first match wins:

  1. Per-user override — AETHER_UVT_USER_OVERRIDES ("uuid1:true,uuid2:false")
  2. Percentage rollout — AETHER_UVT_ROLLOUT_PCT (0-100, bucket by user hash)
  3. Global flag       — AETHER_UVT_ENABLED ("true"/"false")

Design notes:
- Env is re-read on every call. We want the operator to be able to change
  rollout percentage via `systemctl set-environment` + restart without
  waiting for a redeploy. The cost is ~1 os.environ.get per call, which
  is negligible next to a Supabase query.
- Hash-bucketing is deterministic: the SAME user_id always lands in the
  same bucket, so a user doesn't flap in and out of UVT mid-session.
- First-time-true per user gets logged at INFO so you can watch rollout
  happen in journalctl without instrumenting anything else. Cache is
  process-local (a set); on worker restart it re-logs, which is fine.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Literal, Optional

log = logging.getLogger("aethercloud.feature_flags")

# Env var names — kept as module constants so tests can patch without string drift
ENV_ENABLED = "AETHER_UVT_ENABLED"
ENV_ROLLOUT_PCT = "AETHER_UVT_ROLLOUT_PCT"
ENV_USER_OVERRIDES = "AETHER_UVT_USER_OVERRIDES"

# Process-local set of user_ids we've already logged "first-time-true" for.
# Not thread-safe in the strict sense; collisions are harmless (one extra log).
_first_time_seen: set[str] = set()


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════


def is_uvt_enabled(user_id: Optional[str] = None) -> bool:
    """Return True if this user should hit the UVT-enabled codepath.

    user_id is the Supabase public.users.id UUID. When None (unauthenticated
    or pre-auth), only the global flag applies — rollout percentage and
    per-user overrides are skipped.
    """
    # 1. Per-user override (always wins)
    if user_id:
        overrides = _load_user_overrides()
        if user_id in overrides:
            enabled = overrides[user_id]
            _maybe_log_first_time(user_id, enabled, reason="override")
            return enabled

    # 2. Percentage rollout
    if user_id:
        pct = _get_rollout_pct()
        if pct > 0:
            if _hash_bucket(user_id) < pct:
                _maybe_log_first_time(user_id, True, reason=f"rollout@{pct}")
                return True
            # Rollout set but user not in bucket: fall through to global
            # flag — normally False — so operators who set pct ALSO have
            # AETHER_UVT_ENABLED=false (the documented combo).

    # 3. Global flag
    global_on = _get_global_flag()
    if user_id and global_on:
        _maybe_log_first_time(user_id, True, reason="global")
    return global_on


def require_uvt_or_legacy(user_id: Optional[str] = None) -> Literal["uvt", "legacy"]:
    """String branch helper for route handlers that switch on the flag.

    Usage:
        if feature_flags.require_uvt_or_legacy(user.id) == "uvt":
            return await _agent_run_uvt(...)
        return await _agent_run_legacy(...)
    """
    return "uvt" if is_uvt_enabled(user_id) else "legacy"


def flag_snapshot() -> dict:
    """Sanitized flag state for the /healthz/flags endpoint.

    Never returns user IDs or secret values — only the shape of the config.
    Safe to expose on an unauthenticated endpoint.
    """
    return {
        "AETHER_UVT_ENABLED": str(_get_global_flag()).lower(),
        "AETHER_UVT_ROLLOUT_PCT": _get_rollout_pct(),
        "override_count": len(_load_user_overrides()),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Internals — env parsing
# ═══════════════════════════════════════════════════════════════════════════


def _get_global_flag() -> bool:
    raw = os.environ.get(ENV_ENABLED, "false").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _get_rollout_pct() -> int:
    raw = os.environ.get(ENV_ROLLOUT_PCT, "0").strip()
    try:
        pct = int(raw)
    except ValueError:
        log.warning("feature_flags: invalid %s=%r — defaulting to 0", ENV_ROLLOUT_PCT, raw)
        return 0
    # Clamp — an operator typing 150 or -5 should NOT enable for everyone
    # or disable entirely by accident.
    return max(0, min(100, pct))


def _load_user_overrides() -> dict[str, bool]:
    """Parse 'uuid1:true,uuid2:false' into a dict. Tolerates whitespace and
    empty entries. Unknown values default to False (safer than True)."""
    raw = os.environ.get(ENV_USER_OVERRIDES, "")
    if not raw.strip():
        return {}
    out: dict[str, bool] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        uid, _, val = entry.partition(":")
        uid = uid.strip()
        if not uid:
            continue
        out[uid] = val.strip().lower() in ("1", "true", "yes", "on")
    return out


def _hash_bucket(user_id: str) -> int:
    """Map user_id → [0, 99] deterministically. Same input → same bucket,
    always. Uses SHA-256 (not random) so the bucket doesn't change across
    server restarts or Python versions."""
    h = hashlib.sha256(user_id.encode("utf-8")).digest()
    # Use the first 4 bytes as an unsigned int — plenty of entropy for 100 buckets.
    n = int.from_bytes(h[:4], "big")
    return n % 100


def _maybe_log_first_time(user_id: str, enabled: bool, *, reason: str) -> None:
    """Log the first time a given user gets UVT=True in this process.

    Rollout visibility: tail `journalctl -u aether` and grep for
    'first UVT hit' to watch bucket fills during a percentage ramp.
    """
    if not enabled:
        return
    if user_id in _first_time_seen:
        return
    _first_time_seen.add(user_id)
    log.info("first UVT hit user=%s reason=%s", user_id[:8] + "…", reason)


def _reset_first_time_cache_for_tests() -> None:
    """Test hook — the first-time-logged set leaks across tests otherwise."""
    _first_time_seen.clear()
