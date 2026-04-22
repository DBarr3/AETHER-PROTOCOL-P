"""
Smoke test for the Stage I integration harness.

Runs a tiny simulation (2 users × 3 days × casual persona) and asserts:
- simulate.main() exits 0
- CSV has ≥1 row per user
- /account/usage tally matches CSV tally (no drift)
- Markdown renders without KeyError
- reports directory is created + written

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest


def test_smoke_harness_run(tmp_path):
    # Import inline — simulate.py installs the api_server shim at import time
    # and we want each test to start from a clean module state.
    from aether.harness import simulate

    out_dir = tmp_path / "reports"

    rc = simulate.main([
        "--tier", "solo",
        "--users", "2",
        "--days", "3",
        "--persona-mix", "casual=1.0",
        "--seed", "1",
        "--out", str(out_dir),
        "--quiet",
    ])
    assert rc == 0, "harness should exit 0"

    # Expect one CSV + one MD written
    csv_files = sorted(out_dir.glob("margin-*.csv"))
    md_files = sorted(out_dir.glob("margin-*.md"))
    assert len(csv_files) >= 1, "CSV must be written"
    assert len(md_files) >= 1, "Markdown must be written"
    csv_path = csv_files[-1]
    md_path = md_files[-1]
    assert csv_path.stat().st_size > 0
    assert md_path.stat().st_size > 0

    # Read rows
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert rows, "CSV must contain at least one row"

    # At least one row per user id in the CSV (casual persona still fires
    # ≥~2 calls/day × 3 days, so >= 2 rows per user is realistic)
    per_user = {}
    for r in rows:
        per_user.setdefault(r["user_id"], []).append(r)
    assert len(per_user) == 2, "two users should be represented"

    # Markdown contract — must contain the section headers we ship
    md = md_path.read_text(encoding="utf-8")
    assert "AetherCloud UVT Margin Report" in md
    assert "Per-tier margin" in md
    assert "Routing breakdown" in md

    # No integration-drift warning when the harness ran clean
    assert "Integration drift" not in md, (
        "harness sum must match /account/usage exactly — drift was detected"
    )


def test_parse_persona_mix_normalizes():
    from aether.harness.user_simulator import parse_persona_mix
    out = parse_persona_mix("casual=6,power=3,abusive=1")
    assert abs(sum(out.values()) - 1.0) < 1e-6
    assert out["casual"] == pytest.approx(0.6)


def test_assign_personas_even_split():
    from aether.harness.user_simulator import assign_personas
    personas = assign_personas(10, {"casual": 0.5, "power": 0.5}, seed=42)
    assert len(personas) == 10
    # Roughly balanced
    c = personas.count("casual")
    assert 3 <= c <= 7
