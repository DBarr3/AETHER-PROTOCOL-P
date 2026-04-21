"""
Deterministic Anthropic stand-in for the Stage I integration harness.

How it hooks in:
- TokenAccountant accepts an optional `_http_client` param. The harness
  constructs an httpx.AsyncClient whose `transport` returns canned responses
  for api.anthropic.com/v1/messages. TokenAccountant doesn't know it's fake.

What it returns:
- Deterministic token counts drawn from per-load distributions (seeded RNG).
- A `usage` block that matches Anthropic's real response shape.
- The response model string matches what TokenAccountant sent — no surprise
  routing drift.

What it does NOT do:
- Emit real Anthropic ratelimit headers. Our PricingGuard doesn't read those
  (our rate limiting is Supabase-driven). If Stage I later wants to test
  real-Anthropic backoff, bolt it on then.

Cost computation lives in ModelRegistry (Stage A), not here. The harness
sums costs from usage_events.cost_usd_cents_fractional — already populated
on the real code path by TokenAccountant.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Optional

import httpx


# ─── Per-load token distributions (mean, std, floor, ceiling) ─────────────
# Input ranges are spec values; output means come from the spec table.
# Std of 0.25 × mean gives a realistic long-tail while keeping most calls
# within the quoted range.
_INPUT_RANGES = {
    "light":  (400,   1_200),
    "medium": (2_000, 8_000),
    "heavy":  (10_000, 40_000),
}
_OUTPUT_MEANS = {"light": 180, "medium": 900, "heavy": 3_500}


def _draw_tokens(rng: random.Random, load: str) -> tuple[int, int]:
    """Sample (input_tokens, output_tokens) for a given load tier."""
    lo, hi = _INPUT_RANGES.get(load, _INPUT_RANGES["medium"])
    input_tok = rng.randint(lo, hi)
    out_mean = _OUTPUT_MEANS.get(load, _OUTPUT_MEANS["medium"])
    # Log-normal-ish tail: most calls near the mean, rare spikes up to 3×.
    noise = rng.gauss(0, 0.25)
    output_tok = max(40, int(out_mean * (1.0 + noise)))
    return input_tok, output_tok


@dataclass
class FakeCallLog:
    """One line per simulated Anthropic call. Harness collects these."""
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    load: str


class FakeAnthropicTransport(httpx.AsyncBaseTransport):
    """httpx transport that returns a canned /v1/messages response.

    Use:
        transport = FakeAnthropicTransport(seed=42)
        async with httpx.AsyncClient(transport=transport) as client:
            await token_accountant.call(..., _http_client=client)
    """

    def __init__(self, *, seed: int = 0, cache_hit_rate: float = 0.0):
        self._rng = random.Random(seed)
        self._cache_hit_rate = cache_hit_rate
        # Harness-visible history so tests can assert distributions
        self.calls: list[FakeCallLog] = []

    def set_next_load(self, load: str) -> None:
        """Hint the transport which load tier the next call will be.

        TokenAccountant doesn't pass load in the HTTP request, so we smuggle
        it via a module-level var set by the harness right before calling
        token_accountant.call(). Ugly but isolated and deterministic.
        """
        self._next_load = load

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        model_id = body.get("model", "")
        max_tokens = int(body.get("max_tokens") or 0)
        load = getattr(self, "_next_load", "medium")

        # Classifier calls have max_tokens <= 200 and use the stable
        # _CLASSIFIER_SYSTEM prompt. Orchestrator calls are always >= 8k.
        is_classifier = max_tokens <= 200
        if is_classifier:
            # Classifier bills ~50-100 input tokens (cached system prompt
            # at steady state) + 40 tokens of JSON output. Tiny footprint.
            input_tok = self._rng.randint(80, 140)
            output_tok = self._rng.randint(30, 60)
        else:
            input_tok, output_tok = _draw_tokens(self._rng, load)

        # Simulate cache hits on the declared cache_control portions.
        cached_tok = 0
        if self._cache_hit_rate > 0 and self._rng.random() < self._cache_hit_rate:
            cached_tok = int(input_tok * self._rng.uniform(0.5, 0.9))

        self.calls.append(FakeCallLog(
            model=model_id,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cached_input_tokens=cached_tok,
            load=load if not is_classifier else "classifier",
        ))

        # Classifier must emit valid JSON on content.text; orchestrator
        # returns free-form text that the caller just displays.
        text = _canned_text(load) if is_classifier else f"Response to {load} request."

        payload = {
            "id": f"msg_fake_{len(self.calls)}",
            "type": "message",
            "role": "assistant",
            "model": model_id,
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": input_tok,
                "output_tokens": output_tok,
                "cache_read_input_tokens": cached_tok,
            },
        }
        return httpx.Response(200, json=payload)


# ─── Canned text the classifier actually parses ───────────────────────────
# QOPCBridge.classify() expects `{"qopc_load": ..., "confidence": ..., "reason": ...}`.
# When the harness calls the classifier (indirectly via router.route), the
# response goes through the same parse path as prod — so we need to emit the
# right JSON shape based on the HINTED load. _canned_text is keyed on the
# fake-transport's _next_load, which the harness sets to the TRUE load for
# the current synthetic call. The classifier thus returns the ground-truth
# tier, which is the whole point — the harness isolates billing/routing from
# classifier accuracy. Classifier drift is a separate concern.

def _canned_text(load: str) -> str:
    confidence = {"light": 0.92, "medium": 0.85, "heavy": 0.90}.get(load, 0.8)
    reason = {
        "light": "simple lookup",
        "medium": "moderate reasoning",
        "heavy": "complex coordination",
    }.get(load, "n/a")
    return json.dumps({
        "qopc_load": load,
        "confidence": confidence,
        "reason": reason,
    })
