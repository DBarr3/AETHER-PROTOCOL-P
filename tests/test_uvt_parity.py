"""UVT parity between TS and Python.

Reads tests/parity/fixtures.json. For each fixture:
- Simple formula: lib.model_registry.uvt(input, output, cached) must equal
  fixture['expected_simple'] (Python is source of truth for the simple
  formula; PolicyGate's computeUvtSimple mirrors it).
- Weighted formula: tests/parity/uvt_weighted_helper.uvt_weighted(input)
  must equal fixture['expected_weighted'] (spec is source of truth; the
  TS side has the authoritative impl, this helper mirrors it in Python
  so parity can be asserted both directions).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib import model_registry
from tests.parity.uvt_weighted_helper import uvt_weighted

FIXTURES_PATH = Path(__file__).parent / "parity" / "fixtures.json"


def _fixtures() -> list[dict]:
    return json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))


def test_fixtures_file_has_100_entries():
    assert len(_fixtures()) == 100


@pytest.mark.parametrize("idx", range(100))
def test_simple_formula_parity(idx: int):
    f = _fixtures()[idx]
    u = f["input"]
    got = model_registry.uvt(
        input_tokens=u["input_tokens"],
        output_tokens=u["output_tokens"],
        cached_input_tokens=u["cached_input_tokens"],
    )
    assert got == f["expected_simple"], f"fixture {idx}: {u}"


@pytest.mark.parametrize("idx", range(100))
def test_weighted_formula_parity(idx: int):
    f = _fixtures()[idx]
    got = uvt_weighted(f["input"])
    assert got == f["expected_weighted"], f"fixture {idx}: {f['input']}"
