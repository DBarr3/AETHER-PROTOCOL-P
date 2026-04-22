"""PoC 2.6 — In PR 1 v5 shadow mode, PolicyGate's gate_rejected verdicts
are discarded at the Python side.

lib/uvt_routes.py:220-236 shadow dispatch:

    try:
        shadow = await router_client.pick({...})
        log.info("router_would_pick: %s", shadow.chosen_model)
    except Exception:
        log.debug("shadow dispatch failed", exc_info=True)

Both RouterGateRejected (PolicyGate said 402/413/429) AND RouterUnreachable
(PolicyGate timed out or 5xx'd) are caught by `except Exception` and
logged at DEBUG. /agent/run then proceeds to pricing_guard.preflight and
Router.route() regardless of what PolicyGate decided.

This is intentional for PR 1 v5 (that's what "shadow mode" means — log
only, don't enforce). BUT:

1. `log.debug` means the event is invisible at default INFO log level.
   PolicyGate's shadow rejections are silently dropped. SRE cannot see
   them without re-running at DEBUG.

2. PR 1 v5 callout "SRE alert: router.unreachable_total > 0.5% of calls
   over 5 min → page" (router_client.py:103) relies on the OTel counter,
   NOT the caught exception. The counter is incremented via
   `_emit_unreachable()` INSIDE router_client.pick before raising — good.
   BUT RouterGateRejected does NOT call `_emit_unreachable`, so gate
   rejections don't hit the same counter. No signal on "PolicyGate would
   have blocked N% of shadow traffic" without parsing logs.

3. Boundary risk for PR 2 cutover: when shadow_mode flips to enforcement,
   the current `except Exception: log.debug(...)` pattern — if copied —
   becomes a PolicyGate bypass. A bug in the enforcement code that leaves
   the old catch in place would silently allow ALL requests. Diligence
   required during the cutover review.

Severity: MEDIUM — informational-for-shadow, but primes a Critical
regression risk at PR 2 cutover.
Fix (at cutover):
    - Remove the `except Exception: log.debug` catch and replace with
      explicit enforcement: on RouterGateRejected → 402 to user; on
      RouterUnreachable → 503 (fail-closed, not fall-through).
    - Emit an OTel counter for shadow-gate rejections so SRE has a
      pre-cutover signal of how many requests PolicyGate would block.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


@pytest.mark.asyncio
async def test_shadow_rejection_is_swallowed(monkeypatch):
    """When PolicyGate returns RouterGateRejected, /agent/run still runs
    the downstream Python router path."""
    from lib import router_client, uvt_routes
    from lib.router_client import RouterGateRejected

    reached_downstream = {"hit": False}

    # Fake router_client.pick — raises the same way a real 402 would
    async def fake_pick(ctx):
        raise RouterGateRejected(
            gate_type="opus_budget_exceeded",
            user_message_code="opus_budget_exceeded",
            gate_cap_key="opus_pct_mtd",
            http_status=402,
        )

    monkeypatch.setattr(router_client, "pick", fake_pick)

    # Enable shadow dispatch via env vars
    monkeypatch.setenv("AETHER_ROUTER_URL", "https://fake.example/pick")
    monkeypatch.setenv("AETHER_INTERNAL_SERVICE_TOKEN", "FAKE-TOKEN")

    # The shadow dispatch block mirrors the real handler (uvt_routes.py:220)
    # We extract it to demonstrate the swallow behavior without wiring
    # FastAPI + Supabase.
    import os
    import uuid as _uuid
    import logging

    log = logging.getLogger("aethercloud.uvt_routes")
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record)

    handler = _Capture()
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)

    try:
        if os.environ.get("AETHER_ROUTER_URL") and os.environ.get("AETHER_INTERNAL_SERVICE_TOKEN"):
            try:
                shadow = await router_client.pick({"userId": "u-1"})
                log.info("router_would_pick: %s", shadow.chosen_model)
            except Exception:
                log.debug("shadow dispatch failed", exc_info=True)

        # Execution reaches here — shadow rejection did NOT stop the flow
        reached_downstream["hit"] = True
    finally:
        log.removeHandler(handler)

    assert reached_downstream["hit"] is True, (
        "Shadow rejection stopped the flow — but shadow mode should be "
        "log-only. If this assertion flips in PR 2, the enforcement path "
        "is live and should be reviewed."
    )

    # Only DEBUG-level log fired for the rejection — invisible at INFO.
    debug_records = [r for r in captured if r.levelno == logging.DEBUG]
    info_records = [r for r in captured if r.levelno == logging.INFO]
    assert len(debug_records) == 1
    assert len(info_records) == 0, (
        "Expected NO INFO-level log for a shadow rejection. If this asserts, "
        "the visibility-gap argument needs revisiting."
    )


if __name__ == "__main__":
    import asyncio
    asyncio.run(
        test_shadow_rejection_is_swallowed(
            type("P", (), {
                "setattr": lambda self, tgt, name, val: setattr(tgt, name, val),
                "setenv":  lambda self, name, val: __import__("os").environ.__setitem__(name, val),
            })()
        )
    )
    print("Confirmed: shadow gate rejections are swallowed into DEBUG log.")
