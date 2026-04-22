"""
RouterClient — Python-side shim that calls PolicyGate (TypeScript edge).

The Python orchestrator receives a RoutingDecision BEFORE invoking Stage D's
ModelRouter. PolicyGate owns the "is this call allowed?" gates; Stage D owns
"which model fits this work?" — see diagrams/docs_router_architecture.md.

Invariants:
- 200ms total timeout (includes TCP connect). PolicyGate should respond p99<5ms.
- Fail-closed: on timeout / 5xx / network error, raise RouterUnreachable.
  NEVER return a fallback RoutingDecision. The orchestrator must propagate
  the failure upstream (503) so no user request runs without PolicyGate's
  eligibility check.
- 402 / 413 / 429 with `error="router_gate"` body → RouterGateRejected with
  machine-readable fields. The /agent/run route catches this and maps it
  back to an HTTP error the client can show.
- Service token is read from AETHER_INTERNAL_SERVICE_TOKEN once per call
  (so rotation via env-var + systemctl restart picks up new values).

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

log = logging.getLogger("aethercloud.router_client")

_TIMEOUT_SECONDS = 0.200  # total; PolicyGate p99<5ms, so this is a huge margin


# ═══════════════════════════════════════════════════════════════════════════
# Response types
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RoutingDecision:
    """PolicyGate's success envelope. predicted_uvt_cost is the weighted
    formula (spec §2); predicted_uvt_cost_simple is the Python-parity
    (input-cached)+output unit that gates actually check against in PR1."""

    chosen_model: str
    reason_code: str
    predicted_uvt_cost: int
    predicted_uvt_cost_simple: int
    decision_schema_version: int
    uvt_weight_version: int
    latency_ms: int


class RouterGateRejected(Exception):
    """PolicyGate denied the call on a plan/budget/quota gate.

    The orchestrator should translate this to an HTTP error for the user —
    e.g. 402 with user_message_code 'opus_budget_exceeded'. Never retry on
    this exception; gates are deterministic given the same context.
    """

    def __init__(
        self,
        *,
        gate_type: str,
        user_message_code: str,
        gate_cap_key: str,
        http_status: int,
    ):
        self.gate_type = gate_type
        self.user_message_code = user_message_code
        self.gate_cap_key = gate_cap_key
        self.http_status = http_status
        super().__init__(f"PolicyGate rejected: {gate_type}")


class RouterUnreachable(Exception):
    """PolicyGate didn't respond, responded 5xx, or returned a 4xx that is
    NOT a router_gate body. Caller must fail-closed (propagate 503);
    NEVER return a fallback RoutingDecision."""


# ═══════════════════════════════════════════════════════════════════════════
# Client
# ═══════════════════════════════════════════════════════════════════════════


_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(_TIMEOUT_SECONDS))
    return _client


def _emit_unreachable() -> None:
    # OTel counter is wired by ops layer; we keep this as a log hook so the
    # import surface stays tiny. SRE alert: router.unreachable_total > 0.5%
    # of calls over 5 min → page.
    log.warning("router.unreachable_total", extra={"event": "router.unreachable"})


async def pick(ctx: dict[str, Any]) -> RoutingDecision:
    """Call PolicyGate. Returns RoutingDecision on 200. Raises
    RouterGateRejected on router_gate 4xx. Raises RouterUnreachable on
    timeout / network / 5xx / unexpected 4xx shape.

    ctx is the RoutingContext shape validated zod-side:
      userId, tier, taskKind, estimatedInputTokens, estimatedOutputTokens,
      requestId, traceId.
    (opusPctMtd, activeConcurrentTasks, uvtBalance were removed from the
    PolicyGate contract in C1/C2/C3 — see
    tests/security/redteam_policygate_report.md. The TS route now
    server-resolves them from Supabase. Callers may still include them
    in the dict for now; the route strips legacy keys pre-Zod.)
    """
    url = os.environ.get("AETHER_ROUTER_URL")
    token = os.environ.get("AETHER_INTERNAL_SERVICE_TOKEN")
    if not url or not token:
        _emit_unreachable()
        raise RouterUnreachable(
            "AETHER_ROUTER_URL or AETHER_INTERNAL_SERVICE_TOKEN not set"
        )

    try:
        resp = await _get_client().post(
            url,
            json=ctx,
            headers={
                "x-aether-internal": token,
                "content-type": "application/json",
            },
        )
    except (httpx.TimeoutException, httpx.NetworkError):
        _emit_unreachable()
        raise RouterUnreachable()

    status = resp.status_code

    if status == 200:
        data = resp.json()
        return RoutingDecision(
            chosen_model=data["chosen_model"],
            reason_code=data["reason_code"],
            predicted_uvt_cost=data["predicted_uvt_cost"],
            predicted_uvt_cost_simple=data["predicted_uvt_cost_simple"],
            decision_schema_version=data["decision_schema_version"],
            uvt_weight_version=data["uvt_weight_version"],
            latency_ms=data["latency_ms"],
        )

    if status in (402, 413, 429):
        try:
            body = resp.json()
        except Exception:
            body = {}
        if body.get("error") == "router_gate":
            raise RouterGateRejected(
                gate_type=body["gate_type"],
                user_message_code=body["user_message_code"],
                gate_cap_key=body["gate_cap_key"],
                http_status=status,
            )
        # 4xx but not a gate body → treat as protocol failure
        _emit_unreachable()
        raise RouterUnreachable(f"unexpected {status} body shape")

    # 5xx / 400 / anything else → unreachable (NO fallback decision)
    _emit_unreachable()
    raise RouterUnreachable(f"status={status}")
