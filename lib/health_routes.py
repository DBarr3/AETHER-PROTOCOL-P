"""
Health endpoints for the VPS2 deploy runbook.

Three tiers, each progressively more expensive:

    GET /healthz         — "is the process alive"  (no auth, no DB, always fast)
    GET /healthz/deep    — "is the backend healthy" (2s budget, hits Supabase)
    GET /healthz/flags   — "what's the feature-flag config"  (sanitized)

Used by:
- deploy/healthcheck.sh (crontab) to detect bad deploys within 60s
- nginx upstream check for load balancing (if we add >1 VPS)
- deploy/deploy.sh post-restart smoke

Process start time is captured at module import so /healthz can report
uptime without adding a background task.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from typing import Any, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from lib import feature_flags

log = logging.getLogger("aethercloud.health")

health_router = APIRouter(tags=["health"])

_started_at = time.time()

# Cached git SHA — computed once at import. If this process is run from a
# non-repo or the git CLI isn't on PATH, we use 'unknown' rather than
# crashing the endpoint.
def _git_sha() -> str:
    sha = os.environ.get("AETHER_GIT_SHA")
    if sha:
        return sha[:12]
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=1,
        )
        return out.decode("utf-8").strip()
    except Exception:
        return "unknown"

_GIT_SHA = _git_sha()


# Injected at startup (same pattern as uvt_routes) so the deep check can
# reach Supabase without forcing a heavy import at module load.
supabase_client: Optional[Any] = None


# ═══════════════════════════════════════════════════════════════════════════
# /healthz — liveness
# ═══════════════════════════════════════════════════════════════════════════


@health_router.get("/healthz")
async def healthz() -> dict:
    """Shallow health — proves the event loop is running and the module
    imported cleanly. Zero I/O. Cron-friendly.

    Must stay fast + dependency-free. A failing DB should NOT make this
    endpoint 5xx, or every healthcheck probe cascades into an outage signal.
    Use /healthz/deep for that."""
    return {
        "ok": True,
        "sha": _GIT_SHA,
        "uptime_s": round(time.time() - _started_at, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════
# /healthz/deep — DB reachability
# ═══════════════════════════════════════════════════════════════════════════


@health_router.get("/healthz/deep")
async def healthz_deep() -> Any:
    """Deep health — verifies the backend can reach Supabase. No Stripe
    ping: Stripe's list-customers API can spike latency and we'd rather
    not page ourselves on a Stripe blip.

    2-second budget. If Supabase is down or slow, return 503 with the
    reason so we don't silently mask degraded state.
    """
    checks: dict[str, str] = {}
    overall_ok = True

    # DB reachability
    if supabase_client is None:
        checks["db"] = "not_configured"
        overall_ok = False
    else:
        try:
            # Cheap read — 'plans' has exactly 4 rows, no RLS drama, unique
            # to our schema. 1s timeout on the query itself.
            def _probe():
                resp = supabase_client.table("plans").select("tier").limit(1).execute()
                return bool(getattr(resp, "data", None) is not None)

            ok = await asyncio.wait_for(asyncio.to_thread(_probe), timeout=1.5)
            checks["db"] = "ok" if ok else "empty"
            if not ok:
                overall_ok = False
        except asyncio.TimeoutError:
            checks["db"] = "timeout"
            overall_ok = False
        except Exception as exc:
            checks["db"] = f"error: {exc.__class__.__name__}"
            overall_ok = False

    # Stripe — skipped for the reason above. Documented so future ops
    # doesn't wonder why the endpoint pretends Stripe is always fine.
    checks["stripe"] = "skipped_by_design"

    body = {"ok": overall_ok, **checks}
    return JSONResponse(content=body, status_code=200 if overall_ok else 503)


# ═══════════════════════════════════════════════════════════════════════════
# /healthz/flags — sanitized feature-flag config
# ═══════════════════════════════════════════════════════════════════════════


@health_router.get("/healthz/flags")
async def healthz_flags() -> dict:
    """Return the current flag state. Desktop clients hit this on page
    load to decide whether to render the UVT meter. Operators hit it to
    confirm their `systemctl set-environment` took effect.

    Never includes user IDs or secrets. The `AETHER_UVT_ENABLED` key is
    included literally so `deploy/healthcheck.sh`'s grep works."""
    return feature_flags.flag_snapshot()
