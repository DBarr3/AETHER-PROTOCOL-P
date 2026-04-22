"""
TokenAccountant — the ONLY file in the codebase that calls api.anthropic.com.

Every request through the system goes through `call()`:
    1. Apply prompt caching (`cache_control: ephemeral`) to system + tool schemas
    2. POST to /v1/messages
    3. Compute UVT + cost_usd_cents via ModelRegistry
    4. Atomic ledger write via Supabase rpc_record_usage
    5. Return the parsed response

Callers (Router, legacy direct paths in api_server.py, etc.) must never do
their own httpx.post to Anthropic. Stage B of the UVT migration rips the
direct call sites out of agent_pipeline / project_orchestrator /
task_decomposer / agent/claude_agent / agent/hardened_claude_agent /
agent/task_scheduler / api_server.py:1966 and replaces them with calls
through this module.

Invariants:
- Anthropic API key read ONCE at module import from $ANTHROPIC_API_KEY.
  Never from function args, never from user state. Server-side key only.
- Usage accounting is best-effort durable: if rpc_record_usage fails, the
  event is appended to a local JSONL dead-letter at
  $AETHER_USAGE_DLQ (default /var/lib/aethercloud/usage_dlq.jsonl) so a
  replay job can commit it later. We never lose billing data silently.
- QOPC load signal (light|medium|heavy) is threaded through here because
  rpc_record_usage writes it to usage_events — the margin-analysis harness
  reads it back to correlate load class with cost.

Aether Systems LLC - Patent Pending
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

import httpx

from lib import model_registry

log = logging.getLogger("aethercloud.token_accountant")

# ─── Module-level config (read once) ─────────────────────────────────────
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_ANTHROPIC_CACHE_BETA = "prompt-caching-2024-07-31"
_ANTHROPIC_MCP_BETA = "mcp-client-2025-04-04"
_DEFAULT_DLQ_PATH = Path("/var/lib/aethercloud/usage_dlq.jsonl")
_HTTPX_TIMEOUT_SECONDS = 90.0

QopcLoad = Literal["light", "medium", "heavy"]


def _api_key() -> str:
    """Read ANTHROPIC_API_KEY at call time so hot-rotation via
    /etc/aethercloud/.env + systemctl restart picks up new values."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. TokenAccountant cannot call Anthropic without it. "
            "Set in /etc/aethercloud/.env on VPS2."
        )
    return key


def _dlq_path() -> Path:
    return Path(os.environ.get("AETHER_USAGE_DLQ", str(_DEFAULT_DLQ_PATH)))


# ─── Response envelope ───────────────────────────────────────────────────
@dataclass
class AnthropicResponse:
    """What TokenAccountant.call() returns. Raw-ish pass-through with the
    bits the router + tool loop need pulled into named fields."""
    raw: dict[str, Any]
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    uvt_consumed: int
    cost_usd_cents: float
    stop_reason: str
    tool_uses: list[dict]

    @property
    def content(self) -> list[dict]:
        return self.raw.get("content", [])


# ─── Public API ──────────────────────────────────────────────────────────

async def call(
    *,
    model: model_registry.ModelKey,
    messages: list[dict],
    user_id: Optional[str] = None,
    task_id: Optional[str] = None,
    system: Optional[str] = None,
    tools: Optional[list[dict]] = None,
    mcp_servers: Optional[list[dict]] = None,
    max_tokens: int = 2048,
    qopc_load: Optional[QopcLoad] = None,
    supabase_client: Optional[Any] = None,
    _http_client: Optional[httpx.AsyncClient] = None,
) -> AnthropicResponse:
    """Single-entrypoint Anthropic call with UVT accounting.

    Parameters that matter:
    - model: ModelRegistry key. Not the model_id; the logical role.
    - user_id: Supabase public.users.id (uuid). When set, usage is attributed
      via rpc_record_usage. When None, the call still happens and prompt
      caching still applies, but no ledger row is written — Stage B transition
      mode. PricingGuard in Stage E requires user_id.
    - task_id: optional; when set, usage_events rows are joined back into
      public.tasks for the UX breakdown panel.
    - qopc_load: threaded through to usage_events for post-hoc margin analysis.

    Raises:
    - RuntimeError if ANTHROPIC_API_KEY unset or model disabled.
    - httpx.HTTPStatusError on Anthropic 4xx/5xx (caller's responsibility to
      translate to user-facing errors).
    """

    spec = model_registry.get(model)
    if not spec.enabled:
        raise RuntimeError(f"Model {model!r} is disabled in ModelRegistry. Enable it first.")

    payload = _build_payload(spec, messages, system, tools, max_tokens)

    headers = _build_headers(api_key=_api_key(), has_mcp=bool(mcp_servers))
    if mcp_servers:
        payload["mcp_servers"] = mcp_servers

    # ─── The one HTTPS call ────────────────────────────────────
    owns_client = _http_client is None
    client = _http_client or httpx.AsyncClient(timeout=_HTTPX_TIMEOUT_SECONDS)
    try:
        resp = await client.post(_ANTHROPIC_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    finally:
        if owns_client:
            await client.aclose()

    # ─── Usage extraction ──────────────────────────────────────
    usage = data.get("usage", {}) or {}
    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    # Anthropic reports cached reads separately — they count against the 90%-off
    # rate, not the full input rate.
    cached_input_tokens = int(usage.get("cache_read_input_tokens", 0))

    uvt = model_registry.uvt(input_tokens, output_tokens, cached_input_tokens)
    cost = model_registry.cost_usd_cents(model, input_tokens, output_tokens, cached_input_tokens)

    text = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ).strip()
    tool_uses = [b for b in data.get("content", []) if b.get("type") == "tool_use"]

    # ─── Ledger commit (best-effort-durable) ───────────────────
    await _commit_usage(
        supabase_client=supabase_client,
        user_id=user_id,
        task_id=task_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        cost_usd_cents_fractional=cost,
        qopc_load=qopc_load,
    )

    return AnthropicResponse(
        raw=data,
        text=text,
        model=spec.model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        uvt_consumed=uvt,
        cost_usd_cents=cost,
        stop_reason=data.get("stop_reason", ""),
        tool_uses=tool_uses,
    )


# ─── Payload + header builders ───────────────────────────────────────────

def _build_payload(
    spec: model_registry.ModelSpec,
    messages: list[dict],
    system: Optional[str],
    tools: Optional[list[dict]],
    max_tokens: int,
) -> dict[str, Any]:
    """Constructs the /v1/messages body with prompt caching applied to stable
    prompts (system, tool schemas). User messages are never cached."""
    payload: dict[str, Any] = {
        "model": spec.model_id,
        "max_tokens": max_tokens,
        "messages": messages,
    }

    if system and spec.supports_prompt_caching:
        # Anthropic accepts `system` as either a string OR a list of content
        # blocks. We use the list form so we can attach cache_control.
        payload["system"] = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    elif system:
        payload["system"] = system

    if tools:
        if spec.supports_prompt_caching:
            # Cache the ENTIRE tool schema block — it's the biggest stable
            # prompt fragment most agents carry.
            cached_tools = [copy.deepcopy(t) for t in tools]
            if cached_tools:
                cached_tools[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = cached_tools
        else:
            payload["tools"] = tools

    return payload


def _build_headers(*, api_key: str, has_mcp: bool) -> dict[str, str]:
    betas: list[str] = [_ANTHROPIC_CACHE_BETA]
    if has_mcp:
        betas.append(_ANTHROPIC_MCP_BETA)
    return {
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_VERSION,
        "anthropic-beta": ",".join(betas),
        "content-type": "application/json",
    }


# ─── Ledger commit path ──────────────────────────────────────────────────

async def _commit_usage(
    *,
    supabase_client: Optional[Any],
    user_id: Optional[str],
    task_id: Optional[str],
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
    cost_usd_cents_fractional: float,
    qopc_load: Optional[QopcLoad],
) -> None:
    """Calls rpc_record_usage. On failure, writes the event to a local DLQ
    so a replay job can commit it later. We never lose billing data silently.

    If user_id is None, the call is unattributed — no ledger write at all
    (rpc_record_usage requires uuid not null). Stage B transition mode.
    Once Stage E lands, PricingGuard refuses unattributed calls upstream.

    The supabase_client is injected to keep this module testable. In prod,
    api_server builds one at startup and passes it per-request.
    """
    if user_id is None:
        log.debug("TokenAccountant: unattributed call (user_id=None) — ledger skipped")
        return

    event = {
        "user_id": user_id,
        "task_id": task_id,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cost_usd_cents_fractional": cost_usd_cents_fractional,
        "qopc_load": qopc_load,
    }
    if supabase_client is None:
        log.warning("TokenAccountant: no supabase_client provided — writing usage to DLQ only")
        _append_to_dlq(event)
        return

    try:
        # supabase-py: .rpc(name, params) returns a builder. Running it
        # yields the function result. We don't need the return value here —
        # we only care that the write succeeded.
        rpc_call = supabase_client.rpc(
            "rpc_record_usage",
            {
                "p_user_id": user_id,
                "p_task_id": task_id,
                "p_model": model,
                "p_input_tokens": input_tokens,
                "p_output_tokens": output_tokens,
                "p_cached_input_tokens": cached_input_tokens,
                "p_cost_usd_cents_fractional": cost_usd_cents_fractional,
                "p_qopc_load": qopc_load,
            },
        )
        # Async supabase-py exposes .execute() as awaitable; sync client
        # returns a response object directly. Support both.
        result = rpc_call.execute()
        if asyncio.iscoroutine(result):
            result = await result
        err = getattr(result, "error", None)
        if err:
            raise RuntimeError(f"rpc_record_usage returned error: {err}")
    except Exception as exc:
        log.error("TokenAccountant: rpc_record_usage failed (%s) — appending to DLQ", exc)
        _append_to_dlq(event)


def _append_to_dlq(event: dict[str, Any]) -> None:
    """Best-effort DLQ write. Even this can fail (disk full); if so we log
    and drop. Monitoring alerts on non-empty DLQ size are the backstop."""
    path = _dlq_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as exc:  # noqa: BLE001 — nothing actionable if DLQ write fails
        log.error("TokenAccountant: DLQ append failed (%s). Usage event LOST: %s", exc, event)
        return

    # ─── DLQ size gauge + threshold alert (Red Team #2 H3) ────────────────
    # Emit a gauge on every enqueue + a CRITICAL line tagged DLQ_OVER_THRESHOLD
    # once the queue crosses AETHER_DLQ_ALERT_THRESHOLD (default 50). Ops can
    # grep journalctl for the tag; Prometheus scrapes log_messages_total
    # filtered by the tag. Stage K will replace this with a proper replay
    # cron (see deploy/replay_dlq.py for the manual path that exists today).
    try:
        line_count = 0
        with path.open("r", encoding="utf-8") as f:
            for _ in f:
                line_count += 1
        log.info("dlq.size_gauge", extra={
            "event": "dlq.size_gauge",
            "dlq_line_count": line_count,
            "dlq_path": str(path),
        })
        threshold = int(os.environ.get("AETHER_DLQ_ALERT_THRESHOLD", "50"))
        if line_count >= threshold:
            log.critical(
                "DLQ_OVER_THRESHOLD: usage_dlq has %d entries (>= %d). "
                "Billing ledger is drifting. Run deploy/replay_dlq.py to "
                "re-fire rpc_record_usage against these rows before any "
                "reach the monthly boundary.",
                line_count, threshold,
            )
    except Exception as exc:  # noqa: BLE001 — gauge is best-effort; never fail the write
        log.warning("TokenAccountant: DLQ size-gauge read failed (%s)", exc)


# ─── Public helpers for non-router call sites ───────────────────────────
#
# Red Team #2 Critical C1: the three legacy call sites
#     agent/claude_agent.py
#     agent/hardened_claude_agent.py
#     mcp_worker/agent_executor.py
# used to call Anthropic directly, bypassing every invariant this module
# enforces. They're now required to route through `call()` (async) or
# `call_sync()` (the sync bridge below). Do NOT add a fourth helper that
# hits Anthropic — extend this module instead.


def resolve_model_key(raw: str) -> model_registry.ModelKey:
    """Map a raw model identifier (env-config string, Anthropic snapshot,
    logical name) to the ModelRegistry short key.

    Used by call sites that carry a legacy `CLAUDE_MODEL`-style env string
    and need to feed it into `call()`. If the mapping is ambiguous we
    default to 'sonnet' — safer than raising in a hot path.
    """
    if not raw:
        return "sonnet"
    r = str(raw).lower()
    if "haiku" in r:
        return "haiku"
    if "opus" in r:
        return "opus"
    if "sonnet" in r:
        return "sonnet"
    if "gpt" in r:
        return "gpt5"
    if "gemma" in r:
        return "gemma"
    return "sonnet"


def call_sync(
    *,
    model: model_registry.ModelKey,
    messages: list[dict],
    user_id: Optional[str] = None,
    task_id: Optional[str] = None,
    system: Optional[str] = None,
    tools: Optional[list[dict]] = None,
    mcp_servers: Optional[list[dict]] = None,
    max_tokens: int = 2048,
    qopc_load: Optional[QopcLoad] = None,
    supabase_client: Optional[Any] = None,
) -> AnthropicResponse:
    """Synchronous bridge around `call()` for legacy sync call sites.

    Behavior:
    - If no asyncio loop is running in the current thread: uses
      asyncio.run() (creates a new loop, runs, closes).
    - If a loop IS already running (e.g. this is called from within an
      async handler): runs the coroutine on a dedicated thread via a
      short-lived executor. This avoids the "cannot be called from a
      running event loop" error while keeping the caller synchronous.

    Never returns a fallback response — all errors propagate exactly as
    the async version, including httpx.HTTPStatusError and RuntimeError.
    """
    coro_factory = lambda: call(
        model=model, messages=messages, user_id=user_id, task_id=task_id,
        system=system, tools=tools, mcp_servers=mcp_servers,
        max_tokens=max_tokens, qopc_load=qopc_load,
        supabase_client=supabase_client,
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop → safe to asyncio.run()
        return asyncio.run(coro_factory())

    # Running loop present → execute on a worker thread with its own loop.
    import concurrent.futures as _cf

    def _runner() -> AnthropicResponse:
        return asyncio.run(coro_factory())

    with _cf.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_runner).result()
