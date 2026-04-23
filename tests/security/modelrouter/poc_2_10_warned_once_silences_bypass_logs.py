"""PoC 2.10 / Red Team #2 M4 — ROUTER_POLICY_BYPASS log suppression
+ un-locked policy_bypass_by_gate increments.

Pre-fix pattern (now removed):

    _warned_once: bool = False
    ...
    global policy_bypass_detected, _warned_once
    policy_bypass_detected += 1
    if not _warned_once:
        log.warning("ROUTER_POLICY_BYPASS: ...")
        _warned_once = True

After the first Router.route() call per process, the ROUTER_POLICY_BYPASS
WARN log was suppressed for the life of the process — `journalctl ... |
grep ROUTER_POLICY_BYPASS` workflows missed every bypass after the first
per worker lifetime.

Separately, `policy_bypass_by_gate` dict increments were a plain
`d[k] += 1` with no lock — under uvicorn --workers N --threads M>1 or
Gunicorn gthread, the read-modify-write raced and lost increments.

Post-fix (Group C M4):

  - `_warned_once` removed entirely; WARN logs EVERY bypass
  - `threading.Lock()` (`_policy_bypass_lock`) guards writes to both
    `policy_bypass_detected` and `policy_bypass_by_gate[...]`

This file is the post-fix regression guard. If either protection is
removed, these assertions fail.

Aether Systems LLC — Patent Pending
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


def test_warned_once_pattern_is_removed() -> None:
    """The pre-fix log-suppression pattern must NOT reappear. If any
    future PR reintroduces `_warned_once`, this test fails — which is
    the whole point."""
    text = (REPO / "lib" / "router.py").read_text(encoding="utf-8")

    # The exact three phrases from the vulnerable implementation.
    forbidden_patterns = (
        "_warned_once: bool = False",
        "if not _warned_once:",
        "_warned_once = True",
    )
    survivors = [p for p in forbidden_patterns if p in text]
    assert not survivors, (
        "Red Team #2 M4 regression: the log-suppression pattern has "
        "reappeared in lib/router.py. Each bypass must produce a WARN "
        f"line — remove the short-circuit. Found: {survivors}"
    )


def test_policy_bypass_by_gate_writes_are_locked() -> None:
    """Every `policy_bypass_by_gate[...] += 1` site must be wrapped by
    `with _policy_bypass_lock:`. Under threaded workers (uvicorn
    --threads M>1, Gunicorn gthread), an unlocked read-modify-write
    loses increments; a lost increment is an un-alerted bypass."""
    lines = (REPO / "lib" / "router.py").read_text(encoding="utf-8").splitlines()

    # Find every increment site (both dict keys).
    increment_lines = [
        (i, ln) for i, ln in enumerate(lines)
        if "policy_bypass_by_gate[" in ln and "+= 1" in ln
    ]
    assert increment_lines, (
        "Expected at least one `policy_bypass_by_gate[...] += 1` site. "
        "If the counter was removed entirely, update this test."
    )

    # Each increment must be preceded (within the 3 lines above) by the
    # `with _policy_bypass_lock:` context manager.
    for idx, ln in increment_lines:
        window = "\n".join(lines[max(0, idx - 3): idx + 1])
        assert "with _policy_bypass_lock:" in window, (
            f"lib/router.py:{idx + 1} increments "
            f"policy_bypass_by_gate without a surrounding "
            f"`with _policy_bypass_lock:` — race-lossy under "
            f"threaded workers. Line: {ln.strip()}"
        )


def test_module_counter_lock_exists() -> None:
    """The module-level lock itself must remain. If any PR drops
    `_policy_bypass_lock = threading.Lock()`, the `with` blocks above
    would `NameError` at runtime."""
    text = (REPO / "lib" / "router.py").read_text(encoding="utf-8")
    assert "_policy_bypass_lock = threading.Lock()" in text, (
        "Missing module-level `_policy_bypass_lock`; the with-statements "
        "in the bypass-increment paths depend on it."
    )
    assert "import threading" in text, (
        "Missing `import threading`; the Lock() reference would NameError."
    )


if __name__ == "__main__":
    test_warned_once_pattern_is_removed()
    test_policy_bypass_by_gate_writes_are_locked()
    test_module_counter_lock_exists()
    print("Group C M4 regression guards: all three checks pass.")
