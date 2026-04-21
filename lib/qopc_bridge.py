"""
QOPCBridge — the classifier that emits the load signal the Router uses to
decide model escalation.

One public async entrypoint: `classify(prompt, hydrated_context) -> QopcSignal`.

Internally runs a cheap Haiku call with a stable ~200-token system prompt
(fully cache-eligible via TokenAccountant). Output is structured JSON the
router reads directly — no free-form prose parsing.

Failure semantics: we NEVER raise to the caller. On network failure, API
error, malformed JSON, or invalid tier, we return a conservative
`QopcSignal(load='medium', confidence=0.5, reason=...)`. The router can
treat low-confidence signals differently; a raised exception would break
the whole /agent/run path, which is unacceptable for a routing helper.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, Optional

from lib import token_accountant

log = logging.getLogger("aethercloud.qopc_bridge")

QopcLoad = Literal["light", "medium", "heavy"]


@dataclass(frozen=True)
class QopcSignal:
    """What the router reads: tier recommendation + how sure the classifier is.

    confidence < 0.6 on heavy is the documented 'second-pass' trigger — the
    router may re-classify before burning Opus budget. This dataclass just
    carries the signal; gating decisions live in the router.
    """
    load: QopcLoad
    confidence: float  # clamped to [0.0, 1.0]
    reason: str


# ═══════════════════════════════════════════════════════════════════════════
# Stable system prompt — cache_control is auto-applied by TokenAccountant.
# Target: <250 tokens so the cached portion stays small.
# ═══════════════════════════════════════════════════════════════════════════

_CLASSIFIER_SYSTEM = """You are a compute-load classifier for an AI task router.

Output exactly one line of JSON — no prose, no code fences, no explanation:
{"qopc_load": "<tier>", "confidence": <float 0-1>, "reason": "<brief>"}

TIERS:
- "light": simple lookup, single-step answer, fact retrieval, short summary, one tool call. Examples: "what's 2+2", "summarize this email", "list files in /tmp".
- "medium": multi-step reasoning, code generation under ~100 LOC, a plan with 2-5 subtasks, moderate research. Examples: "write a Python function for X", "plan my afternoon", "refactor this snippet".
- "heavy": architecture design, whole-codebase changes, long-form writing >1000 words, coordinating 5+ sub-agents, deep research. Examples: "build me a full auth system", "redesign this database schema", "audit this entire service".

CONFIDENCE:
- 0.9+ = crystal clear which tier
- 0.7-0.9 = reasonably sure
- 0.5-0.7 = ambiguous, could go either way
- <0.5 = genuinely uncertain (rare; ask for more if unsure)

RULES:
- Always output valid single-line JSON.
- Keep "reason" under 8 words.
- When ambiguous, default DOWN a tier. Opus is expensive; false-heavy is worse than false-medium."""


_DEFAULT_LOAD: QopcLoad = "medium"
_DEFAULT_CONFIDENCE = 0.5
_MAX_CONTEXT_CHARS_FOR_CLASSIFIER = 500  # compact summary only; full context goes to orchestrator


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════


async def classify(
    prompt: str,
    hydrated_context: Optional[str] = None,
    *,
    user_id: Optional[str] = None,
    task_id: Optional[str] = None,
    supabase_client: Optional[Any] = None,
) -> QopcSignal:
    """Classify a request's compute load via a Haiku call.

    Parameters:
    - prompt: the user's request verbatim.
    - hydrated_context: optional compact summary of prior conversation/project
      state. Truncated to 500 chars — the classifier only needs shape, not
      detail. The full context goes to the orchestrator downstream.
    - user_id: threaded to TokenAccountant so classifier UVT is billed to the
      requesting user. Unattributed (None) during Stage B/C transition.
    - task_id: when set, classifier usage joins back to the task for the
      breakdown panel.

    Returns a QopcSignal. Never raises.
    """
    if not prompt or not prompt.strip():
        # Empty prompt can't be classified — let the router handle it as light.
        return QopcSignal(load="light", confidence=0.9, reason="empty prompt")

    user_message = _build_user_message(prompt, hydrated_context)

    try:
        resp = await token_accountant.call(
            model="haiku",
            messages=[{"role": "user", "content": user_message}],
            system=_CLASSIFIER_SYSTEM,
            max_tokens=120,
            user_id=user_id,
            task_id=task_id,
            supabase_client=supabase_client,
        )
    except Exception as exc:
        log.warning("QOPCBridge: classifier call failed (%s) — defaulting to medium/0.5", exc)
        return QopcSignal(load=_DEFAULT_LOAD, confidence=_DEFAULT_CONFIDENCE, reason="classifier error")

    return _parse_signal(resp.text)


# ═══════════════════════════════════════════════════════════════════════════
# Internals
# ═══════════════════════════════════════════════════════════════════════════


def _build_user_message(prompt: str, hydrated_context: Optional[str]) -> str:
    """Assemble the classifier input. Context stays compact — the classifier
    is deciding routing, not answering."""
    if not hydrated_context:
        return f"Classify this request:\n\n{prompt}"
    trimmed_ctx = hydrated_context[:_MAX_CONTEXT_CHARS_FOR_CLASSIFIER]
    return (
        f"Prior context (compact summary):\n{trimmed_ctx}\n\n"
        f"Current request:\n\n{prompt}"
    )


def _parse_signal(text: str) -> QopcSignal:
    """Parse the Haiku response. Defensive against every formatting drift
    — extra prose, missing fields, wrong types — because classifier output
    is one of the things most likely to be "almost right" and break."""
    if not text or not text.strip():
        return QopcSignal(load=_DEFAULT_LOAD, confidence=_DEFAULT_CONFIDENCE,
                          reason="empty classifier output")

    # Find the first JSON object. {...} is intentionally non-greedy; Haiku
    # occasionally emits the JSON then a newline then some prose.
    match = re.search(r'\{[^{}]*\}', text, flags=re.DOTALL)
    if not match:
        return QopcSignal(load=_DEFAULT_LOAD, confidence=_DEFAULT_CONFIDENCE,
                          reason="no JSON in classifier output")

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return QopcSignal(load=_DEFAULT_LOAD, confidence=_DEFAULT_CONFIDENCE,
                          reason="malformed classifier JSON")

    load_raw = data.get("qopc_load") or data.get("load")  # tolerate key drift
    if load_raw not in ("light", "medium", "heavy"):
        return QopcSignal(load=_DEFAULT_LOAD, confidence=_DEFAULT_CONFIDENCE,
                          reason=f"invalid load: {load_raw!r}")

    try:
        confidence = float(data.get("confidence", _DEFAULT_CONFIDENCE))
    except (TypeError, ValueError):
        confidence = _DEFAULT_CONFIDENCE
    # Clamp — classifier occasionally emits 1.2 or -0.1
    confidence = max(0.0, min(1.0, confidence))

    reason_raw = data.get("reason", "")
    reason = str(reason_raw)[:120] if reason_raw else ""

    return QopcSignal(load=load_raw, confidence=confidence, reason=reason)  # type: ignore[arg-type]
