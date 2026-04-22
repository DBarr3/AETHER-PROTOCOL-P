"""Generator for tests/parity/fixtures.json — 100 UVT parity cases.

Run: python tests/parity/generate_fixtures.py

Each fixture is deterministic (seeded random). expected_simple uses the
Python-parity formula (input - cached) + output — Python is source of
truth for this. expected_weighted uses the spec §2 weighted formula with
v1 weights and model multipliers — spec is source of truth.

Both TS and Python tests read this file and assert their own impl matches
these expected values. If the generator is ever changed, regenerate +
commit fixtures.json, then re-run both tests.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

WEIGHTS = {
    "w_in": 1.0,
    "w_out": 4.0,
    "w_think": 5.0,
    "w_cached_in": 0.1,
    "w_subagent_fixed": 250,
    "w_tool": 50,
}
MULTS = {
    "claude-haiku-4": 0.25,
    "claude-sonnet-4": 1.0,
    "claude-opus-4": 5.0,
    "gpt-5-mini": 0.3,
    "gpt-5": 1.2,
    "perplexity-sonar": 0.4,
}
MODELS = list(MULTS.keys())


def compute_simple(u: dict) -> int:
    return max(0, u["input_tokens"] - u["cached_input_tokens"]) + u["output_tokens"]


def compute_weighted(u: dict) -> int:
    pre = (
        u["input_tokens"] * WEIGHTS["w_in"]
        + u["output_tokens"] * WEIGHTS["w_out"]
        + u["thinking_tokens"] * WEIGHTS["w_think"]
        + u["cached_input_tokens"] * WEIGHTS["w_cached_in"]
        + u["sub_agent_count"] * WEIGHTS["w_subagent_fixed"]
        + u["tool_calls"] * WEIGHTS["w_tool"]
    )
    return math.ceil(pre * MULTS[u["model_id"]])


def make_fixture(u: dict) -> dict:
    return {
        "input": u,
        "expected_simple": compute_simple(u),
        "expected_weighted": compute_weighted(u),
    }


def strategic() -> list[dict]:
    base = lambda **kw: {
        "input_tokens": 0,
        "output_tokens": 0,
        "thinking_tokens": 0,
        "cached_input_tokens": 0,
        "sub_agent_count": 0,
        "tool_calls": 0,
        "model_id": "claude-sonnet-4",
        **kw,
    }
    cases = []
    # Zero + floor cases per model
    for m in MODELS:
        cases.append(base(model_id=m))
        cases.append(base(model_id=m, output_tokens=1))
        cases.append(base(model_id=m, input_tokens=1))
    # Opus = 5× Sonnet parity pair
    cases.append(base(input_tokens=1000, output_tokens=500, model_id="claude-sonnet-4"))
    cases.append(base(input_tokens=1000, output_tokens=500, model_id="claude-opus-4"))
    # Cached > input clamp
    cases.append(base(input_tokens=100, cached_input_tokens=500, output_tokens=50))
    # Large rich usage
    cases.append(base(
        input_tokens=20000, output_tokens=4000, thinking_tokens=2000,
        cached_input_tokens=15000, sub_agent_count=5, tool_calls=20,
        model_id="claude-opus-4",
    ))
    return cases


def randomized(n: int) -> list[dict]:
    rng = random.Random(42)
    cases = []
    for _ in range(n):
        cases.append({
            "input_tokens": rng.randint(0, 20000),
            "output_tokens": rng.randint(0, 8000),
            "thinking_tokens": rng.randint(0, 3000),
            "cached_input_tokens": rng.randint(0, 10000),
            "sub_agent_count": rng.randint(0, 10),
            "tool_calls": rng.randint(0, 50),
            "model_id": rng.choice(MODELS),
        })
    return cases


def main() -> None:
    out_path = Path(__file__).parent / "fixtures.json"
    strategic_cases = strategic()
    needed = 100 - len(strategic_cases)
    all_cases = strategic_cases + randomized(max(0, needed))
    all_cases = all_cases[:100]
    fixtures = [make_fixture(u) for u in all_cases]
    out_path.write_text(json.dumps(fixtures, indent=2), encoding="utf-8")
    print(f"wrote {len(fixtures)} fixtures to {out_path}")


if __name__ == "__main__":
    main()
