# DeepSeek V4 → UVT Integration — System Design

**Status:** Pre-implementation. Approve before code changes.
**Date:** 2026-04-25
**Author:** AetherCloud planning
**Repo target:** `DBarr3/AETHER-CLOUD@main`
**Companion docs:**
- [Pricing reference](./2026-04-25-deepseek-v4-pricing.md)
- [All-stage plan](../plans/2026-04-25-deepseek-v4-uvt-plan.md)

---

## 1. One-paragraph summary

DeepSeek V4 ships a fully OpenAI-compatible REST API at `https://api.deepseek.com/v1`, exposes per-call cache-hit and cache-miss tokens directly on `usage`, and bills at roughly **8.6× cheaper output than GPT-5.5 and 21× cheaper than Claude Opus 4.6**. The integration is mechanically simple — one new provider module, two new registry entries — but it forces three structural changes to UVT we have been deferring: (1) a real **provider abstraction** in `TokenAccountant`, (2) a **per-cache-tier rate** instead of the current single `cache_discount` multiplier, and (3) explicit **reasoning-token accounting** for thinking-mode billing accuracy.

**Estimate:** 5–7 working days for V4-Flash + V4-Pro behind a feature flag, including Supabase migration and parity tests against the existing Claude `usage_events` ledger. Plus 7 calendar days of shadow-eval running in parallel with soft-launch prep.

---

## 2. Goals & non-goals

**In scope (this PR / sequence of PRs):**
- Provider abstraction (`token_accountant.py` → orchestrator + `lib/providers/anthropic.py`).
- DeepSeek adapter (`lib/providers/deepseek.py`) for V4-Flash + V4-Pro.
- `ModelSpec` rewrite: explicit `cache_read` / `cache_write` / `cache_storage` rates.
- Reasoning-token accounting: new field on response envelope and `usage_events`.
- Supabase migration: `usage_events` columns; `uvt_balances.provider_uvt jsonb`; `rpc_record_usage` dual-write.
- `AnthropicResponse → ProviderResponse` rename, with deprecated alias for one release.
- Feature flag: `AETHER_DEEPSEEK_ENABLED=false` initially.
- Shadow-eval harness for 1% heavy traffic.

**Out of scope (deferred follow-up PR):**
- **Router integration.** `qopc_load → model_key` mapping stays untouched in v1. We revisit after Phase 5 is stable for ≥1 week.
- OpenAI / Gemini wiring (slots remain disabled).
- DLQ replay path changes — only the event shape grows; the existing replay job is updated to handle both old and new shapes (one-line change).

---

## 3. Architecture

### 3.1 Module layout (after Phase 0)

```
lib/
├── token_accountant.py        ← orchestration, UVT math, ledger commit
├── providers/
│   ├── __init__.py
│   ├── anthropic.py           ← extracted from token_accountant.py, ZERO behavior change
│   ├── deepseek.py            ← NEW, Phase 2
│   └── openai.py              ← placeholder for gpt5 (out of scope)
├── model_registry.py          ← rewritten ModelSpec, V4 entries (Phase 1)
├── pricing_guard.py           ← READ-ONLY context, do NOT modify in this PR
└── router.py                  ← READ-ONLY context, do NOT modify in this PR
```

### 3.2 ProviderAdapter interface

Each adapter is a small module exposing two pure functions:

```python
class ProviderAdapter(Protocol):
    def build_request(spec, messages, system, tools, max_tokens, **kw) -> tuple[str, dict, dict]:
        """Returns (url, headers, payload)."""
    def parse_usage(response_json) -> UsageBreakdown:
        """Returns standardized {input, output, cached_input, reasoning, cache_write_tokens}."""
    def parse_response(response_json) -> dict:
        """Returns {text, reasoning_text, tool_uses, stop_reason}."""
```

`token_accountant.call()` dispatches on `spec.provider`:

```
spec = model_registry.get(model)
adapter = _adapters[spec.provider]      # {"anthropic": ..., "deepseek": ...}
url, headers, payload = adapter.build_request(spec, ...)
data = httpx.post(url, headers=headers, json=payload)
usage = adapter.parse_usage(data)
parsed = adapter.parse_response(data)
# UVT math + ledger commit are provider-agnostic from here.
```

### 3.3 ProviderResponse envelope (renamed from `AnthropicResponse`)

```python
@dataclass
class ProviderResponse:
    raw: dict[str, Any]
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int                 # NEW — 0 for providers without reasoning split
    cache_write_tokens: int               # NEW — 0 for providers without cache-write surcharge
    uvt_consumed: int
    cost_usd_cents: float
    stop_reason: str
    tool_uses: list[dict]

# Deprecated alias kept one release for the legacy import path.
AnthropicResponse = ProviderResponse
```

**Rename safety verified:** grep against `agent/claude_agent.py` and `agent/hardened_claude_agent.py` confirms neither touches `AnthropicResponse` fields beyond `.text`. Both go through `token_accountant.call_sync()` and use the return value's `.text` only — both names expose `.text`.

---

## 4. Data flow (V4-Pro happy path)

```
Caller (api_server, agent_pipeline, etc.)
   │ model="dsv4_pro", messages=[...], user_id, task_id, qopc_load="heavy"
   ▼
PricingGuard.preflight()                  ← UNCHANGED, blocks before adapter dispatch
   │ allowed=True
   ▼
TokenAccountant.call()
   │   spec = registry.get("dsv4_pro")
   │   adapter = providers.deepseek
   │   url, headers, payload = adapter.build_request(spec, ...)
   │
   ▼ POST https://api.deepseek.com/v1/chat/completions
       Authorization: Bearer $DEEPSEEK_API_KEY
       payload: {model:"deepseek-v4-pro", messages, max_tokens,
                 thinking:{type:"enabled"}, tools?}
   │
   │ response.usage = {prompt_tokens, prompt_cache_hit_tokens, prompt_cache_miss_tokens,
   │                   completion_tokens, completion_tokens_details:{reasoning_tokens}, ...}
   ▼
adapter.parse_usage(data) → UsageBreakdown
   │   input_tokens, output_tokens, cached_input_tokens,
   │   reasoning_tokens, cache_write_tokens=0
   ▼
registry.uvt(...)         → uvt_consumed
registry.cost_usd_cents(...) → fractional cents
   ▼
_commit_usage()  ──── rpc_record_usage(p_user_id, p_task_id, p_model,
                                       p_input_tokens, p_output_tokens,
                                       p_cached_input_tokens,
                                       p_cost_usd_cents_fractional, p_qopc_load,
                                       p_reasoning_tokens=0, p_cache_write_tokens=0)
   │ (DLQ on failure → /var/lib/aethercloud/usage_dlq.jsonl)
   ▼
ProviderResponse → caller
```

---

## 5. Schema migration (Phase 1)

### 5.1 `usage_events` — additive

```sql
ALTER TABLE public.usage_events
  ADD COLUMN reasoning_tokens   integer NOT NULL DEFAULT 0,
  ADD COLUMN cache_write_tokens integer NOT NULL DEFAULT 0;
```

### 5.2 `uvt_balances` — generic provider tracking

The current table has hardcoded `haiku_uvt` / `sonnet_uvt` / `opus_uvt` columns. **Do not add `dsv4_flash_uvt` / `dsv4_pro_uvt` columns** — that path doesn't scale.

```sql
ALTER TABLE public.uvt_balances
  ADD COLUMN provider_uvt jsonb NOT NULL DEFAULT '{}'::jsonb;
-- Keep legacy haiku_uvt / sonnet_uvt / opus_uvt for one release —
-- pricing_guard reads opus_uvt directly today.
```

`provider_uvt` shape:

```json
{
  "haiku":      12345,
  "sonnet":     23456,
  "opus":       3456,
  "dsv4_flash": 9876,
  "dsv4_pro":   543
}
```

### 5.3 `rpc_record_usage` — dual-write + new params

```sql
CREATE OR REPLACE FUNCTION rpc_record_usage(
  p_user_id                   uuid,
  p_task_id                   uuid,
  p_model                     text,
  p_input_tokens              integer,
  p_output_tokens             integer,
  p_cached_input_tokens       integer,
  p_cost_usd_cents_fractional numeric(12,6),
  p_qopc_load                 text,
  p_reasoning_tokens          integer DEFAULT 0,   -- NEW
  p_cache_write_tokens        integer DEFAULT 0    -- NEW
) RETURNS TABLE(total_uvt bigint, haiku_uvt bigint, sonnet_uvt bigint, opus_uvt bigint, provider_uvt jsonb)
```

Function body:
- Bumps legacy `haiku_uvt` / `sonnet_uvt` / `opus_uvt` when `p_model IN ('haiku','sonnet','opus')` — backwards-compatible.
- Merges the value into `provider_uvt` for **all** models including the legacy three: `provider_uvt = provider_uvt || jsonb_build_object(p_model, current + v_uvt)`.
- New params default to 0 → existing call sites continue to work without modification.

---

## 6. Environment + secrets

```diff
# /etc/aethercloud/.env on VPS2
+ DEEPSEEK_API_KEY=...           # primary key
+ DEEPSEEK_TEST_KEY=...          # used by nightly canary only
+ AETHER_DEEPSEEK_ENABLED=false  # flip to true after parity tests pass
```

Secret rotation: same 3-step procedure documented in §6 of the handoff bundle.

---

## 7. Working agreements (must hold across all phases)

- **TokenAccountant is the SOLE provider HTTP caller.** Both `agent/claude_agent.py` and `agent/hardened_claude_agent.py` have `assert "anthropic" not in sys.modules` at import time. **Do NOT add a similar direct DeepSeek import anywhere.** All DeepSeek calls go through `TokenAccountant`.
- **Cents not dollars.** All pricing in `model_registry.py` stays in USD cents per 1M tokens, stored as `float`. Same convention as today.
- **`AnthropicResponse` rename is safe.** Keep `AnthropicResponse = ProviderResponse` as a deprecated alias for one release.
- **Patent Pending header.** Every new file in `lib/` and `agent/` ends its module docstring with `Aether Systems LLC — Patent Pending`. Match the existing convention.
- **Phase 0 first.** The provider extraction must land with **zero behavior change** before any DeepSeek code is touched. Full Anthropic test suite must pass after Phase 0 with **no edits to test files**.

---

## 8. Test surface that must stay green

| Suite | LOC / Tests | Role |
|---|---|---|
| `tests/test_model_registry.py` | 164 / 19 | Pricing arithmetic + feature-flag gating |
| `tests/test_token_accountant.py` | 471 / 19 (async) | Provider HTTP + ledger commit |
| `tests/test_uvt_parity.py` | 100 fixtures | TS ↔ Python parity (do NOT break) |
| `tests/providers/test_anthropic.py` | NEW (Phase 0) | Mirrors current `test_token_accountant.py` HTTP slice against the extracted adapter |
| `tests/providers/test_deepseek.py` | NEW (Phase 2) | Adapter unit tests + integration test against `DEEPSEEK_TEST_KEY` |
| `tests/integration/test_deepseek_cache_canary.py` | NEW (Phase 3) | Nightly cron against live API; asserts `prompt_cache_hit_tokens > 0` on 2nd identical call |

**TS↔Python parity is non-negotiable.** Phase 1's COGS migration must produce **identical numbers to today** for all 100 parity fixtures.

---

## 9. Risks & mitigations (summary)

See [pricing reference §6](./2026-04-25-deepseek-v4-pricing.md#6-risks-affecting-pricing) for the full table. Top three:

1. **Reasoning-token surprise bills (Medium).** Surface `reasoning_tokens` separately in usage panel from day one; cap thinking on `qopc_load=light`.
2. **V4-Pro thinking-mode margin error (Medium).** Shadow eval before flip — 1% of heavy traffic, 7 days, COGS-per-task within 10% of model.
3. **Data jurisdiction PRC (High for Enterprise).** `jurisdiction` field on `ModelSpec`; router exclusion for `compliance_flag=true` users; document the data path before flip.

---

## 10. Open decisions (must answer before Phase 0 cut)

1. **Reasoning-token billing policy** — A / B / **C (recommended)**?
2. **Cache-pricing field rework now or defer to Gemini?** **Now (recommended)**.
3. **`jurisdiction` field — now or later?** **Now (recommended)**.
4. **Shadow-eval scope** — 1% heavy / 7 days (**recommended**), or skip to opt-in soft-launch?
5. **Confirm router stays untouched in v1** — yes (**recommended**).

---

## 11. Sources

- Live `lib/model_registry.py`, `lib/token_accountant.py`, `lib/pricing_guard.py`, `lib/router.py` — read 2026-04-25.
- Supabase project `cjjcdwrnpzwlvradbros` — schema verified 2026-04-25.
- DeepSeek API docs — https://api-docs.deepseek.com/quick_start/pricing
- Apidog rate card + benchmarks — https://apidog.com/blog/deepseek-v4-api-pricing/

_Aether Systems LLC — Patent Pending_
