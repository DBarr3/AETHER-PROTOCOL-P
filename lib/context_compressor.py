"""
ContextCompressor — trim QOPC-hydrated context to fit the user's tier budget
before it hits the orchestrator.

This is the single biggest UVT leak vector in agent systems: an uncompressed
conversation history + vault summary + tool-schema dump blows past the
tier's context budget and bills the user for re-sending the same tokens
every turn. PricingGuard in Stage E will reject calls that overshoot; this
module is the proactive fix.

Strategy — simple first pass (semantic summarization is Stage C.5):
- str input: tail-trim (keep the most recent content, drop oldest).
- list input: drop oldest turns from the front.
- keep_first=True preserves turns[0] (useful when the first turn carries
  persona context you don't want dropped).

Token estimate: char-based heuristic (len // 4). Anthropic tokenization
averages ~3.5-4 chars/token for English. Picking 4 biases toward OVER-
trimming, which is the safe direction — better to send less context than
to overshoot budget and get billed extra.

Budget source: public.plans.context_budget_tokens per tier:
- free:    8,000
- solo:   24,000 (Starter)
- pro:    80,000
- team:  160,000

Callers look up the budget from Supabase; this module is pure data in/out.

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import logging
from typing import Any, Union

log = logging.getLogger("aethercloud.context_compressor")

# Conservative chars-per-token estimate. Anthropic averages ~3.5-4 for English;
# 4 biases toward trimming MORE than strictly necessary. That's the safe
# direction — undershooting budget costs less than overshooting.
CHARS_PER_TOKEN = 4

# Budget safety margin: don't fill exactly to the limit (estimator has ±10%
# error). Pack to 95% of the computed char budget.
SAFETY_MARGIN = 0.95


ContextLike = Union[str, list]


def estimate_tokens(content: ContextLike) -> int:
    """Fast char-based token estimate. No tokenizer — too slow for the hot path.

    Accepts:
    - str → len(s) // CHARS_PER_TOKEN
    - list of {"role": ..., "content": ...} turns → sum over turn contents
    - list of strings → sum over strings
    """
    if isinstance(content, str):
        if not content:
            return 0
        return max(1, len(content) // CHARS_PER_TOKEN)
    if isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, dict):
                # Pull the message body; tolerate both str and list-of-blocks content
                body = item.get("content", "")
                if isinstance(body, list):
                    for block in body:
                        if isinstance(block, dict):
                            total += estimate_tokens(str(block.get("text", "") or block.get("content", "")))
                        else:
                            total += estimate_tokens(str(block))
                else:
                    total += estimate_tokens(str(body))
            else:
                total += estimate_tokens(str(item))
        return total
    return 0


def compress(
    context: ContextLike,
    budget_tokens: int,
    *,
    keep_first: bool = False,
) -> ContextLike:
    """Trim context to fit in budget_tokens.

    Parameters:
    - context: str OR list of turn dicts OR list of strings.
    - budget_tokens: hard ceiling (from public.plans.context_budget_tokens).
    - keep_first: when True AND context is a list, turns[0] is always retained
      (oldest-first drop happens from turns[1:] onward). Use when the first
      turn is a persona/system bootstrap you can't lose.

    Returns the same type as input (str in → str out, list in → list out).
    Returns the empty equivalent when budget_tokens <= 0.
    """
    if budget_tokens <= 0:
        log.warning("ContextCompressor: budget_tokens=%d — returning empty", budget_tokens)
        return "" if isinstance(context, str) else []

    estimated = estimate_tokens(context)
    if estimated <= budget_tokens:
        return context

    if isinstance(context, str):
        char_budget = int(budget_tokens * CHARS_PER_TOKEN * SAFETY_MARGIN)
        if char_budget >= len(context):
            return context
        trimmed = context[-char_budget:]
        log.info(
            "ContextCompressor: trimmed text %d→%d tokens (budget=%d)",
            estimated, estimate_tokens(trimmed), budget_tokens,
        )
        return trimmed

    if isinstance(context, list):
        turns = list(context)
        if not turns:
            return turns

        first = turns[0] if keep_first else None
        body = turns[1:] if keep_first else list(turns)

        # Drop oldest (front of body) until under budget
        while body:
            current = ([first] + body) if first is not None else body
            if estimate_tokens(current) <= budget_tokens:
                break
            body.pop(0)

        result = ([first] + body) if first is not None else body
        # If we still overshoot (only first survives and it's too big), truncate
        # its content string as a last resort rather than returning an empty list.
        if estimate_tokens(result) > budget_tokens and first is not None and not body:
            result = [_truncate_turn(first, budget_tokens)]

        log.info(
            "ContextCompressor: trimmed turns %d→%d tokens (budget=%d, kept=%d/%d)",
            estimated, estimate_tokens(result), budget_tokens, len(result), len(turns),
        )
        return result

    return context


def _truncate_turn(turn: Any, budget_tokens: int) -> Any:
    """Trim a single turn dict's content string to fit. Last-resort fallback
    when even one turn exceeds budget; avoids returning nothing at all."""
    if not isinstance(turn, dict):
        return turn
    body = turn.get("content", "")
    if isinstance(body, str):
        char_budget = int(budget_tokens * CHARS_PER_TOKEN * SAFETY_MARGIN)
        return {**turn, "content": body[-char_budget:]}
    return turn
