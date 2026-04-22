"""Test-only helper — mirrors TS computeUvtWeighted() so Python parity
tests can validate the weighted formula produces identical results across
languages. Intentionally NOT in lib/ — no production callers.

Source of truth: site/lib/uvt/weights.v1.ts + site/lib/uvt/compute.ts
(spec §2). If weights ever change, regenerate fixtures.json AND update
this helper in lockstep.
"""

from __future__ import annotations

import math

UVT_WEIGHTS_V1 = {
    "w_in": 1.0,
    "w_out": 4.0,
    "w_think": 5.0,
    "w_cached_in": 0.1,
    "w_subagent_fixed": 250,
    "w_tool": 50,
}

MODEL_MULTIPLIERS_V1 = {
    "claude-haiku-4": 0.25,
    "claude-sonnet-4": 1.0,
    "claude-opus-4": 5.0,
    "gpt-5-mini": 0.3,
    "gpt-5": 1.2,
    "perplexity-sonar": 0.4,
}


class UnknownModelError(Exception):
    pass


def uvt_weighted(usage: dict) -> int:
    mult = MODEL_MULTIPLIERS_V1.get(usage["model_id"])
    if mult is None:
        raise UnknownModelError(f"Unknown model_id: {usage['model_id']}")
    w = UVT_WEIGHTS_V1
    pre = (
        usage["input_tokens"] * w["w_in"]
        + usage["output_tokens"] * w["w_out"]
        + usage["thinking_tokens"] * w["w_think"]
        + usage["cached_input_tokens"] * w["w_cached_in"]
        + usage["sub_agent_count"] * w["w_subagent_fixed"]
        + usage["tool_calls"] * w["w_tool"]
    )
    return math.ceil(pre * mult)
