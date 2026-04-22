"""PoC 2.10 — `downgrade_reason` ghost references survive cleanup.

Red team §2.10: "_FakeRouterResp cleanup completeness — plan doc called
out removing stale downgrade_reason field from _FakeRouterResp. Grep all
of tests/ and lib/ for any remaining references to downgrade_reason. If
even one remains, it's a ghost that a copy-paste could resurrect."

The verification report (pr1_v5_verification_report.md line 97) claims
the only surviving reference was in tests/test_uvt_routes.py's
_FakeRouterResp and it was removed. BUT:

    aether/harness/simulate.py:258    downgrade_reason=body.get("downgrade_reason") or ""
    aether/harness/simulate.py:277    downgrade_reason="", reclassified=False
    aether/harness/report.py:56       downgrade_reason: str
    aether/harness/report.py:71       "downgrade_reason" in CSV columns
    aether/harness/report.py:302-329  downgrade_reason rendering logic
    desktop/pages/uvt-meter/uvt-meter.js:90    body.downgrade_reason || null

Seven+ references survived. The desktop client specifically READS a field
the backend no longer emits — if a future PR reintroduces downgrade_reason
on the response envelope, the UI contract silently resurrects the silent-
downgrade semantic.

Per red-team-doc §2 preamble: doc wins over code → Medium.

Severity: MEDIUM (ghost-references) / HIGH (desktop/uvt-meter.js: live
client contract preserves the removed field — an easy path to
reintroduction).
Fix:
    - Remove downgrade_reason from aether/harness/simulate.py (both sites)
    - Remove downgrade_reason from aether/harness/report.py (dataclass
      field, CSV column, rendering branches)
    - Remove downgrade_reason from desktop/pages/uvt-meter/uvt-meter.js
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# Paths that SHOULD NOT contain `downgrade_reason`. Docstrings that
# discuss the historical behavior are allowed ONLY in lib/router.py and
# diagrams/docs_router_architecture.md per the plan doc.
ALLOWED = {
    REPO / "lib" / "router.py",
    REPO / "diagrams" / "docs_router_architecture.md",
    REPO / "docs" / "superpowers" / "plans" / "2026-04-22-router-pr1-v5.md",
    REPO / "tests" / "security" / "pr1_v5_verification_report.md",
    REPO / "tests" / "security" / "modelrouter" / "poc_2_10_ghost_downgrade_reason.py",
}

# Where to search. Exclude node_modules, dist, build outputs.
ROOTS = [REPO / "lib", REPO / "aether", REPO / "desktop", REPO / "site"]
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".md"}


def _scan() -> list[tuple[Path, int]]:
    hits: list[tuple[Path, int]] = []
    pat = re.compile(r"\bdowngrade_reason\b")
    for root in ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in EXTENSIONS:
                continue
            if path in ALLOWED:
                continue
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in pat.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                hits.append((path, line_no))
    return hits


def test_no_ghost_downgrade_reason_references() -> None:
    """Every surviving reference is a re-introduction risk."""
    ghosts = _scan()
    if ghosts:
        msg = ["Ghost references to `downgrade_reason` survive cleanup:"]
        for path, line in ghosts:
            rel = path.relative_to(REPO)
            msg.append(f"  {rel}:{line}")
        msg.append("")
        msg.append(
            "Per verification report §'Drift Found & Fixed' line 97, cleanup "
            "was declared complete. Each of these lines re-enables the "
            "silent-downgrade contract via harness/UI layers."
        )
        raise AssertionError("\n".join(msg))


if __name__ == "__main__":
    ghosts = _scan()
    print(f"Found {len(ghosts)} ghost reference(s):")
    for p, l in ghosts:
        print(f"  {p.relative_to(REPO)}:{l}")
