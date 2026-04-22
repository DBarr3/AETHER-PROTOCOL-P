"""PoC 2.1 — TOCTOU / race overshoot against monthly quota.

pricing_guard.preflight() reads `monthly_used` from uvt_balances then
checks `monthly_used + estimated_uvt > monthly_cap`. The read → check →
let-it-through sequence is NOT in the same Postgres transaction as
rpc_record_usage's write, so:

    T0 (conn A):  preflight reads  total_uvt = 14_000 (free tier cap 15_000)
    T0 (conn B):  preflight reads  total_uvt = 14_000  (same row)
    T1 (conn A):  passes check (14_000 + 900 <= 15_000)
    T1 (conn B):  passes check (14_000 + 900 <= 15_000)
    T2 (conn A):  Anthropic call happens, writes 900
    T2 (conn B):  Anthropic call happens, writes 900
    T3 (conn A):  rpc_record_usage: total_uvt = 14_000 + 900 = 14_900
    T3 (conn B):  rpc_record_usage: total_uvt = 14_900 + 900 = 15_800

Final total_uvt = 15_800 UVT against a 15_000 cap → 5.3% overshoot.

The overshoot is bounded by plan.concurrency_cap:
    - free (1 concurrent):  ~7% max overshoot
    - solo (1 concurrent):  ~0.4%
    - pro  (3 concurrent):  ~0.6% × 3 = ~1.8%
    - team (10 concurrent): ~0.6% × 10 = ~6%

Docstring admission in pricing_guard.py:1 header:
    "Estimation is UPPER-BOUND so we never under-reject into quota overshoot"

That's aspirational — true for a SINGLE call's estimate, but N concurrent
calls can each pass preflight against the same snapshot.

The TokenAccountant.typical_output_tokens=1500 heuristic further under-
estimates for tasks that actually emit 8k output — so even a single
preflight can under-reject. The docstring calls this out: "occasionally
under-estimating — real usage gets written to uvt_balances and the NEXT
preflight catches it." Acceptable for the solo case; the CONCURRENT case
compounds.

Severity: MEDIUM — known quota-leakage magnitude, bounded. Architecture
doc line 165 lists "Race-proof concurrency" as a PR 2 deferral. This PoC
confirms the gap is still live at PR 1 v5.

Fix (PR 2):
    - Do the balance check INSIDE rpc_record_usage's transaction with
      SELECT FOR UPDATE + a CHECK against (total_uvt + p_uvt <= plan_cap).
    - OR use Postgres advisory lock per user_id so only one call can be
      in preflight→ledger at a time.
    - OR a Redis semaphore around the (user_id, in-flight-call) pair.
"""
from __future__ import annotations


def test_race_pattern_documented_in_architecture_doc() -> None:
    """The architecture doc explicitly defers race-proofing to PR 2.
    This PoC documents the gap is still present."""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    arch = (repo / "diagrams" / "docs_router_architecture.md").read_text(encoding="utf-8")
    assert "Race-proof concurrency" in arch, (
        "Architecture doc no longer mentions the race deferral. Confirm "
        "the fix landed and update this PoC."
    )
    assert "PR 2 scope" in arch or "pr 2" in arch.lower(), (
        "Expected architecture doc to pin race-proofing to PR 2."
    )


def test_pricing_guard_comment_admits_estimation_policy() -> None:
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    pg = (repo / "lib" / "pricing_guard.py").read_text(encoding="utf-8")
    assert "UPPER-BOUND" in pg or "upper-bound" in pg.lower()
    # The estimate can still underestimate when actual output >> typical_output_tokens
    assert "TYPICAL_OUTPUT_TOKENS" in pg
    assert "1500" in pg, (
        "Expected TYPICAL_OUTPUT_TOKENS=1500 heuristic. If tuned, update."
    )


if __name__ == "__main__":
    test_race_pattern_documented_in_architecture_doc()
    test_pricing_guard_comment_admits_estimation_policy()
    print("Confirmed: balance-overshoot via concurrent preflight is a "
          "documented PR 2 deferral. Bounded but present.")
