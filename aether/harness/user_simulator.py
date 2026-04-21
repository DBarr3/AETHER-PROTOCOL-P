"""
Per-user traffic generator for the Stage I harness.

Each synthetic user has a tier + persona + RNG. The simulator produces a
stream of (load, timestamp_within_day) pairs that a driver sends through
`/agent/run` (or direct module calls — the CLI picks the interface).

Personas drive call volume + load mix. All numbers from the spec:

    persona     calls/day (mean)    load mix (L / M / H)
    ─────────────────────────────────────────────────
    casual            4               70 / 25 /  5
    power            25               40 / 45 / 15
    abusive          80               10 / 30 / 60

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterator, Literal

Persona = Literal["casual", "power", "abusive"]
Load = Literal["light", "medium", "heavy"]


_PERSONA_CALLS_PER_DAY_MEAN: dict[str, int] = {
    "casual": 4,
    "power": 25,
    "abusive": 80,
}

_PERSONA_LOAD_MIX: dict[str, dict[str, float]] = {
    "casual":  {"light": 0.70, "medium": 0.25, "heavy": 0.05},
    "power":   {"light": 0.40, "medium": 0.45, "heavy": 0.15},
    "abusive": {"light": 0.10, "medium": 0.30, "heavy": 0.60},
}


@dataclass
class SimCall:
    day: int             # 0-indexed day within the simulation window
    load: Load
    prompt: str          # short; real length comes from fake_anthropic
    estimated_output_max: int  # for the /agent/run body — the harness uses
                               # the tier's output_cap, not this value


class UserProfile:
    """Stateful per-user call generator."""

    def __init__(
        self,
        *,
        email: str,
        tier: str,
        persona: Persona,
        seed: int,
    ):
        self.email = email
        self.tier = tier
        self.persona = persona
        self._rng = random.Random(seed)

    def calls_for_day(self, day: int) -> Iterator[SimCall]:
        """Yield SimCall events for this persona for one day.

        Call count: Poisson-ish around the persona's daily mean. We use
        a simple uniform draw (mean ± 40%) for determinism — a proper
        Poisson would need numpy.
        """
        mean = _PERSONA_CALLS_PER_DAY_MEAN[self.persona]
        lo = max(0, int(mean * 0.6))
        hi = int(mean * 1.4) + 1
        n = self._rng.randint(lo, hi)

        mix = _PERSONA_LOAD_MIX[self.persona]
        for i in range(n):
            load = self._draw_load(mix)
            yield SimCall(
                day=day,
                load=load,
                prompt=f"[{self.persona}/{load}/{day}.{i}] synthetic prompt",
                estimated_output_max=800,
            )

    # ── internals ────────────────────────────────────────────────
    def _draw_load(self, mix: dict[str, float]) -> Load:
        r = self._rng.random()
        cum = 0.0
        for load, prob in mix.items():
            cum += prob
            if r <= cum:
                return load  # type: ignore[return-value]
        return "medium"  # safety fallback (rounding float drift)


# ═══════════════════════════════════════════════════════════════════════════
# Persona-mix helpers
# ═══════════════════════════════════════════════════════════════════════════


def parse_persona_mix(spec: str) -> dict[str, float]:
    """Parse 'casual=0.6,power=0.35,abusive=0.05' → {...}.
    Normalizes to sum-to-1 in case of rounding."""
    out: dict[str, float] = {}
    for part in spec.split(","):
        k, _, v = part.strip().partition("=")
        if k and v:
            out[k] = float(v)
    total = sum(out.values())
    if total <= 0:
        raise ValueError(f"invalid persona mix: {spec!r}")
    return {k: v / total for k, v in out.items()}


def assign_personas(
    n_users: int, mix: dict[str, float], *, seed: int = 0,
) -> list[Persona]:
    """Deterministic persona assignment across n_users."""
    rng = random.Random(seed)
    personas: list[Persona] = []
    for p, frac in mix.items():
        count = round(frac * n_users)
        personas.extend([p] * count)  # type: ignore[list-item]
    # Top up or trim to exactly n_users
    while len(personas) < n_users:
        personas.append("casual")
    personas = personas[:n_users]
    rng.shuffle(personas)
    return personas
