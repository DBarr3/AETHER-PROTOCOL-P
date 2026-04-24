"""
Tests for lib/qopc_bridge.py — the classifier that emits the router's load signal.

We mock token_accountant.call so nothing hits Anthropic. The contract under
test:
- Well-formed JSON from Haiku → parsed QopcSignal
- Malformed / missing / wrong-type responses → safe fallback (medium/0.5),
  never raises
- Network / API errors → safe fallback, never propagate
- Confidence clamped to [0.0, 1.0]
- The stable system prompt gets sent to TokenAccountant (cache-eligibility)

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from lib import qopc_bridge


# ═══════════════════════════════════════════════════════════════════════════
# Helpers — mocked TokenAccountant response
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class _FakeResponse:
    text: str = ""
    raw: dict = field(default_factory=dict)
    model: str = "claude-haiku-4-5-20251001"
    input_tokens: int = 100
    output_tokens: int = 20
    cached_input_tokens: int = 0
    uvt_consumed: int = 120
    cost_usd_cents: float = 0.1
    stop_reason: str = "end_turn"
    tool_uses: list = field(default_factory=list)


@pytest.fixture
def mock_call():
    """Patch token_accountant.call and return the AsyncMock so tests can
    both (a) set the classifier response and (b) inspect what was sent."""
    with patch.object(qopc_bridge.token_accountant, "call", new_callable=AsyncMock) as m:
        m.return_value = _FakeResponse(text='{"qopc_load": "medium", "confidence": 0.8, "reason": "ok"}')
        yield m


# ═══════════════════════════════════════════════════════════════════════════
# Happy path
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_well_formed_json_parses(mock_call):
    mock_call.return_value = _FakeResponse(
        text='{"qopc_load": "heavy", "confidence": 0.92, "reason": "full app build"}'
    )
    signal = await qopc_bridge.classify("Build me a whole auth system")
    assert signal.load == "heavy"
    assert signal.confidence == pytest.approx(0.92)
    assert signal.reason == "full app build"


@pytest.mark.asyncio
async def test_light_tier(mock_call):
    mock_call.return_value = _FakeResponse(
        text='{"qopc_load": "light", "confidence": 0.95, "reason": "simple lookup"}'
    )
    signal = await qopc_bridge.classify("What's 2+2?")
    assert signal.load == "light"


@pytest.mark.asyncio
async def test_json_with_surrounding_prose_still_parses(mock_call):
    # Haiku occasionally wraps JSON in prose even when told not to. Regex
    # must find the JSON blob anyway.
    mock_call.return_value = _FakeResponse(
        text='Here you go:\n{"qopc_load": "medium", "confidence": 0.7, "reason": "moderate"}\nHope that helps!'
    )
    signal = await qopc_bridge.classify("Write a Python function")
    assert signal.load == "medium"
    assert signal.reason == "moderate"


@pytest.mark.asyncio
async def test_alternate_key_name_tolerated(mock_call):
    # Classifier drift: some responses use `load` instead of `qopc_load`
    mock_call.return_value = _FakeResponse(
        text='{"load": "light", "confidence": 0.9, "reason": "trivial"}'
    )
    signal = await qopc_bridge.classify("list files")
    assert signal.load == "light"


# ═══════════════════════════════════════════════════════════════════════════
# Failure modes — every one must fall through to medium/0.5, NEVER raise
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_network_error_falls_through_to_medium(mock_call):
    mock_call.side_effect = RuntimeError("connection refused")
    signal = await qopc_bridge.classify("Anything")
    assert signal.load == "medium"
    assert signal.confidence == 0.5
    assert "error" in signal.reason.lower()


@pytest.mark.asyncio
async def test_empty_classifier_output(mock_call):
    mock_call.return_value = _FakeResponse(text="")
    signal = await qopc_bridge.classify("Anything")
    assert signal.load == "medium"


@pytest.mark.asyncio
async def test_no_json_in_output(mock_call):
    mock_call.return_value = _FakeResponse(text="I think this is medium difficulty")
    signal = await qopc_bridge.classify("Anything")
    assert signal.load == "medium"


@pytest.mark.asyncio
async def test_malformed_json(mock_call):
    mock_call.return_value = _FakeResponse(text='{"qopc_load": "heavy", "confidence":}')
    signal = await qopc_bridge.classify("Anything")
    assert signal.load == "medium"


@pytest.mark.asyncio
async def test_invalid_tier_value(mock_call):
    mock_call.return_value = _FakeResponse(
        text='{"qopc_load": "extreme", "confidence": 0.9}'
    )
    signal = await qopc_bridge.classify("Anything")
    assert signal.load == "medium"


@pytest.mark.asyncio
async def test_missing_confidence_uses_default(mock_call):
    mock_call.return_value = _FakeResponse(text='{"qopc_load": "light"}')
    signal = await qopc_bridge.classify("Anything")
    assert signal.load == "light"
    assert signal.confidence == 0.5


@pytest.mark.asyncio
async def test_non_numeric_confidence_uses_default(mock_call):
    mock_call.return_value = _FakeResponse(
        text='{"qopc_load": "light", "confidence": "very high"}'
    )
    signal = await qopc_bridge.classify("Anything")
    assert signal.confidence == 0.5


@pytest.mark.asyncio
async def test_confidence_over_one_clamped(mock_call):
    mock_call.return_value = _FakeResponse(
        text='{"qopc_load": "heavy", "confidence": 1.5}'
    )
    signal = await qopc_bridge.classify("Anything")
    assert signal.confidence == 1.0


@pytest.mark.asyncio
async def test_confidence_negative_clamped(mock_call):
    mock_call.return_value = _FakeResponse(
        text='{"qopc_load": "heavy", "confidence": -0.3}'
    )
    signal = await qopc_bridge.classify("Anything")
    assert signal.confidence == 0.0


@pytest.mark.asyncio
async def test_empty_prompt_returns_light_without_calling(mock_call):
    signal = await qopc_bridge.classify("")
    assert signal.load == "light"
    assert mock_call.call_count == 0  # no API call wasted on empty input


@pytest.mark.asyncio
async def test_whitespace_prompt_treated_as_empty(mock_call):
    signal = await qopc_bridge.classify("   \n\t  ")
    assert signal.load == "light"
    assert mock_call.call_count == 0


# ═══════════════════════════════════════════════════════════════════════════
# Contract — what gets sent to TokenAccountant
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_uses_haiku_model(mock_call):
    await qopc_bridge.classify("Anything")
    assert mock_call.call_args.kwargs["model"] == "haiku"


@pytest.mark.asyncio
async def test_stable_system_prompt_sent(mock_call):
    await qopc_bridge.classify("Anything")
    system = mock_call.call_args.kwargs["system"]
    # The stable prompt must include tier definitions so TokenAccountant
    # applies cache_control to it. If these strings drift, caching breaks.
    assert '"qopc_load"' in system
    assert "light" in system and "medium" in system and "heavy" in system


@pytest.mark.asyncio
async def test_user_id_threaded_to_token_accountant(mock_call):
    await qopc_bridge.classify("Anything", user_id="u-123")
    assert mock_call.call_args.kwargs["user_id"] == "u-123"


@pytest.mark.asyncio
async def test_hydrated_context_is_dropped_from_classifier_input(mock_call):
    """MR-H1 Option B: hydrated_context must NOT reach the classifier's
    user message, regardless of content. See
    tests/security/modelrouter/mr_h1_classifier_prompt_injection_design.md.

    Renamed + re-asserted from the previous
    ``test_hydrated_context_included_compactly`` which predates the fix.
    """
    marker = "HYDRATED-CONTEXT-MARKER-" + "x" * 2000
    await qopc_bridge.classify("Do the thing", hydrated_context=marker)
    sent = mock_call.call_args.kwargs["messages"][0]["content"]
    assert marker not in sent, (
        "MR-H1 REGRESSION: hydrated_context reached the classifier's user "
        f"message. Option B requires the parameter to be fully ignored. "
        f"Got: {sent!r}"
    )
    assert "Prior context" not in sent, (
        "Classifier envelope reintroduced the 'Prior context' header — "
        "this only appeared on the pre-fix path."
    )
    assert "Do the thing" in sent
    # Post-fix envelope is tiny (prompt + fixed wrapper), not budget-gated.
    assert len(sent) < 200


@pytest.mark.asyncio
async def test_no_context_when_none_passed(mock_call):
    await qopc_bridge.classify("Do the thing")
    sent = mock_call.call_args.kwargs["messages"][0]["content"]
    assert "Prior context" not in sent


@pytest.mark.asyncio
async def test_max_tokens_is_bounded(mock_call):
    # Classifier only outputs ~50 tokens of JSON; cap at 120 so a runaway
    # Haiku can't bill us for 4000 tokens of prose.
    await qopc_bridge.classify("Anything")
    assert mock_call.call_args.kwargs["max_tokens"] <= 200
