"""PoC 2.10 — ROUTER_POLICY_BYPASS log suppression after first hit.

lib/router.py:75 `_warned_once: bool = False` + the block at :189-199:

    global policy_bypass_detected, _warned_once
    policy_bypass_detected += 1
    if not _warned_once:
        log.warning("ROUTER_POLICY_BYPASS: ...")
        _warned_once = True

After the first Router.route() call per process, the ROUTER_POLICY_BYPASS
WARN log is suppressed for the life of the process. The module counter
`policy_bypass_detected` still increments, so SRE alerting that counts
*occurrences* via OTel/Prometheus continues to work.

BUT: SRE runbook / architecture doc (line 146):
    SRE alert: any occurrence of ModelRouter.policy_bypass_detected
    OTel counter > 0 → page immediately.

The architecture doc alert is on the COUNTER, so this design is consistent
with it. The risk is when humans grep journalctl — a SECOND bypass (or
third, or ten thousandth) produces ZERO new log lines. Only the first
bypass in a process has a log trace; subsequent bypasses are invisible
to log-line-based detection.

Compounding: `_warned_once` is not reset on gunicorn/uvicorn worker
respawn; each worker has its own. But a long-lived worker that's been
serving 1 day could have had 1 bypass on day 0 and N more on day 1 with
no additional logs.

Separately, `policy_bypass_by_gate` dict increments are not thread-safe
under threadpool executor models. On CPython single-threaded asyncio,
the `d[k] += 1` operation completes in a single bytecode (BINARY_ADD on
an int followed by STORE_SUBSCR) — the GIL keeps it atomic. But if
uvicorn is configured with `--workers N --threads M` (M>1) or under
Gunicorn's `gthread` worker, the read-modify-write can lose increments.
A lost increment = an un-alerted bypass.

Severity: LOW-MEDIUM — depends on SRE's observability wiring; if alerts
are on OTel counters, MEDIUM. If alerts grep logs, HIGH.
Fix:
    - Remove the `_warned_once` short-circuit; log EVERY bypass at WARN
      with rate-limiting delegated to the log handler (python-json-logger
      or OTel sampler), not an all-or-nothing flag.
    - Guard the `policy_bypass_by_gate` increment with `threading.Lock()`
      (or use atomic counters from `opentelemetry.metrics`).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


def test_warned_once_behavior_documented() -> None:
    """Reads lib/router.py to confirm the short-circuit pattern exists.
    Pure AST-free grep — keeps the PoC portable across Python versions."""
    text = (REPO / "lib" / "router.py").read_text(encoding="utf-8")

    assert "_warned_once: bool = False" in text, (
        "Expected module-level `_warned_once` flag — if removed, revisit "
        "this PoC. If still present, log suppression is live."
    )
    assert "if not _warned_once:" in text, (
        "Expected the `if not _warned_once:` gate around the WARN log."
    )
    assert "_warned_once = True" in text, (
        "Expected the flag to be set True after the first log — this is "
        "the line that suppresses subsequent ROUTER_POLICY_BYPASS lines."
    )


def test_counter_is_plain_dict_no_lock() -> None:
    """Confirms lib/router.py.policy_bypass_by_gate is a plain dict with
    NO locking. Under multi-thread workers, increments can race."""
    text = (REPO / "lib" / "router.py").read_text(encoding="utf-8")
    # The counter is declared as `policy_bypass_by_gate: dict[str, int] = {...}`
    # with per-gate keys. No threading.Lock / RLock / asyncio.Lock near it.
    assert "policy_bypass_by_gate: dict[str, int]" in text
    # Look at a 20-line window around the declaration for any lock import
    idx = text.index("policy_bypass_by_gate: dict[str, int]")
    window = text[max(0, idx - 200): idx + 400]
    assert "Lock" not in window, (
        "If a Lock has been added around policy_bypass_by_gate, this "
        "PoC's concern is resolved — update the assertion."
    )


if __name__ == "__main__":
    test_warned_once_behavior_documented()
    test_counter_is_plain_dict_no_lock()
    print("Confirmed: ROUTER_POLICY_BYPASS suppresses after first hit; "
          "counter dict has no lock.")
