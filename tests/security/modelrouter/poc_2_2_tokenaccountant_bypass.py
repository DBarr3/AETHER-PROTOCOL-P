"""PoC 2.2 — TokenAccountant is NOT the sole Anthropic call site.

The verification report (pr1_v5_verification_report.md §12.1d) claims:
    "only lib/token_accountant.py imports anthropic (confirmed in prior commits)"

This PoC proves that claim is false. Three files bypass TokenAccountant and
hit Anthropic directly — every inference they do is unmetered (no UVT
decrement, no usage_events row, no DLQ on failure, no qopc_load field).

Run: python -m pytest tests/security/modelrouter/poc_2_2_tokenaccountant_bypass.py

Severity: CRITICAL — money-adjacent invariant violated in production paths.
Impact: unlimited Anthropic burn (credits, $$$) with zero ledger.
Fix (Stage B migration per token_accountant.py docstring):
    - replace agent/claude_agent.py    Anthropic() client with token_accountant.call()
    - replace agent/hardened_claude_agent.py    same
    - replace mcp_worker/agent_executor.py:114 httpx.post with token_accountant.call()
The docstring at token_accountant.py:14 already lists these as migration
targets; they simply haven't been migrated yet.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# Explicit allowlist — ONLY this file is permitted to reach Anthropic.
ALLOWED = {REPO / "lib" / "token_accountant.py"}

# Directories that contain production Python code. Scope matches the red
# team brief §1 + the plan doc's "Stage B migration" list.
SCAN_ROOTS = [REPO / "lib", REPO / "agent", REPO / "mcp_worker"]

# Also scan top-level *.py files in the repo root (api_server.py etc.)
for p in REPO.glob("*.py"):
    SCAN_ROOTS.append(p)

_PAT = re.compile(
    r"^\s*(from anthropic\b|import anthropic\b)"
    r"|api\.anthropic\.com",
    re.MULTILINE,
)


def _scan() -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    targets: list[Path] = []
    for r in SCAN_ROOTS:
        if r.is_file() and r.suffix == ".py":
            targets.append(r)
        elif r.is_dir():
            targets.extend(r.rglob("*.py"))
    for path in targets:
        if path in ALLOWED:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _PAT.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            hits.append((path, line_no, m.group(0)))
    return hits


def test_token_accountant_is_the_sole_anthropic_call_site() -> None:
    """Every file outside ALLOWED that imports anthropic or POSTs to
    api.anthropic.com is a TokenAccountant bypass."""
    bypasses = _scan()
    if bypasses:
        msg = ["CRITICAL: TokenAccountant bypass — these files call Anthropic directly:"]
        for path, line, match in bypasses:
            rel = path.relative_to(REPO)
            msg.append(f"  {rel}:{line}    {match!r}")
        msg.append("")
        msg.append("Every call through these paths is unmetered inference.")
        msg.append("Verification report §12.1d is incorrect.")
        raise AssertionError("\n".join(msg))


if __name__ == "__main__":
    hits = _scan()
    if not hits:
        print("PASS: no TokenAccountant bypass found.")
    else:
        print("FAIL: TokenAccountant bypass(es) found:")
        for path, line, match in hits:
            print(f"  {path.relative_to(REPO)}:{line}    {match!r}")
        raise SystemExit(1)
