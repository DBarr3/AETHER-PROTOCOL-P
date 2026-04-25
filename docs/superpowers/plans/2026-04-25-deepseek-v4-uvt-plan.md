# DeepSeek V4 → UVT Integration — All-Stage Plan

**Status:** Pre-implementation. **Do NOT cut code until §Open decisions are answered.**
**Date:** 2026-04-25
**Companion docs:**
- [System design](../specs/2026-04-25-deepseek-v4-uvt-design.md)
- [Pricing reference](../specs/2026-04-25-deepseek-v4-pricing.md)
- Source bundle: `.claude/md/4-25/1.txt`

**Effort:** 5–7 working days for Phases 0–5 (sequential), plus 7 calendar days of shadow-eval running in parallel with Phase 5 prep. Phase 6 is a separate follow-up PR.

---

## At-a-glance phase map

| # | Phase | Effort | Gate to next phase |
|---|---|---|---|
| 0 | Provider extraction (zero behavior change) | 1.5d | Anthropic regression suite green |
| 1 | Schema + registry rewrite | 0.5d | Migration green on staging, parity suite still passes |
| 2 | DeepSeek adapter | 1d | Unit + integration tests green |
| 3 | Cache-hit canary (live API) | 0.5d | Cron green for 3 nights |
| 4 | Shadow eval (1% heavy, record-only) | 7 calendar days | Measured COGS within 10% of model |
| 5 | Soft launch (flag flip, opt-in only) | 3–7d | No customer-reported issues |
| 6 | Router integration | Separate PR | Phase 5 stable ≥1 week |

---

## Phase 0 — Provider extraction (refactor prep)

**Effort:** 1.5d. **Gate:** Anthropic regression suite green, zero behavior change.

### Deliverables

- New module: `lib/providers/__init__.py` (empty marker).
- New module: `lib/providers/anthropic.py` — current Anthropic logic extracted as-is from `lib/token_accountant.py`. Module docstring ends with `Aether Systems LLC — Patent Pending`.
- `lib/token_accountant.py` becomes a thin orchestrator: dispatches on `spec.provider`, owns UVT math + ledger commit + DLQ logic. Anthropic-specific URL, headers, payload-builder, and prompt-caching logic move into the adapter.
- Rename `AnthropicResponse → ProviderResponse`. Keep `AnthropicResponse = ProviderResponse` as deprecated alias for one release.
- Add `reasoning_tokens: int` and `cache_write_tokens: int` fields to `ProviderResponse` (both default 0; Anthropic adapter leaves them 0 in this phase).
- New test file: `tests/providers/test_anthropic.py` — mirrors the HTTP-call slice of the current `test_token_accountant.py` against the extracted adapter.

### Acceptance

- `tests/test_token_accountant.py` (471 LOC, 19 async tests) passes **with no edits**.
- `tests/test_model_registry.py` (164 LOC, 19 tests) passes with no edits.
- `tests/test_uvt_parity.py` (100 TS↔Python fixtures) passes with no edits.
- Grep confirms `agent/claude_agent.py` and `agent/hardened_claude_agent.py` still import `token_accountant` only and never touch fields beyond `.text`.
- `assert "anthropic" not in sys.modules` guards in both agent files still hold.

### Risks

- Refactor regresses an edge case in prompt-caching `cache_control` placement → **mitigation:** snapshot `_build_payload` output for 5 representative inputs (system-only, system+tools, tools-only, no-system-no-tools, MCP-enabled) before refactor; assert byte-identical output after.

---

## Phase 1 — Schema + registry rewrite

**Effort:** 0.5d. **Gate:** Supabase migration green on staging, parity suite still passes.

### Deliverables

- `ModelSpec` rewritten with new cache fields (see [system design §5](../specs/2026-04-25-deepseek-v4-uvt-design.md#5-schema-migration-phase-1) and [pricing §5](../specs/2026-04-25-deepseek-v4-pricing.md#5-new-modelspec-phase-1-target-shape)).
- Anthropic entries migrated to identical-COGS values:
  - `cache_read_cents_per_million = input_cents × 0.10`
  - `cache_write_cents_per_million = input_cents × 1.25`
  - `cache_storage_cents_per_million_hour = None`
- `cost_usd_cents()` updated to use `cache_read_cents_per_million` directly (no more `(1 - cache_discount)` multiplier).
- *(Pending decision 3)* `jurisdiction: Literal["us","cn","self"]` field; Anthropic entries default `"us"`.
- Supabase migration file (`supabase/migrations/<ts>_deepseek_v4_uvt.sql`):
  - `usage_events` adds `reasoning_tokens` + `cache_write_tokens` (NOT NULL DEFAULT 0).
  - `uvt_balances` adds `provider_uvt jsonb NOT NULL DEFAULT '{}'::jsonb`.
  - `rpc_record_usage` recreated with two new optional params and dual-write logic (legacy columns + jsonb merge for all models).
- Update `_commit_usage()` in the orchestrator to pass `p_reasoning_tokens` + `p_cache_write_tokens`.
- Update DLQ replay job (`deploy/replay_dlq.py`) to handle both old and new event shapes.

### Acceptance

- Migration runs green on staging Supabase project; rollback script tested.
- `test_model_registry.py` updated to assert: identical COGS output to today for haiku/sonnet/opus across the existing fixtures (regression-test the math).
- `test_uvt_parity.py` (100 fixtures) still passes.
- New parametrized test `test_cost_identical_after_cache_field_migration` covers all three Anthropic keys × {cache hit, cache miss, mixed}.

### Risks

- Math drift between `(1 - cache_discount) × input_rate` and explicit `cache_read_rate` due to float precision → **mitigation:** parity test uses fractional cents at 6-decimal precision (matches `numeric(12,6)` in DB).
- jsonb concurrent-update conflicts on hot `provider_uvt` rows → **mitigation:** `rpc_record_usage` is `SECURITY DEFINER` and uses row-level lock from existing `FOR UPDATE` on `users`; jsonb merge happens inside that transaction.

---

## Phase 2 — DeepSeek adapter

**Effort:** 1d. **Gate:** Unit + integration tests green.

### Deliverables

- New module: `lib/providers/deepseek.py`.
  - `DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"`
  - `build_request(spec, messages, system, tools, max_tokens, *, thinking=True)` — returns `(url, headers, payload)`. Payload uses OpenAI-compatible `{"messages":[...], "thinking":{"type":"enabled"|"disabled"}, "tools":...}`. Headers: `Authorization: Bearer $DEEPSEEK_API_KEY`.
  - `parse_usage(data)` — maps `prompt_tokens`, `prompt_cache_hit_tokens`, `completion_tokens`, `completion_tokens_details.reasoning_tokens` to `UsageBreakdown`.
  - `parse_response(data)` — pulls `choices[0].message.content`, `reasoning_content`, `tool_calls`, `finish_reason`.
- Register adapter in `token_accountant._adapters["deepseek"]`.
- `dsv4_flash` + `dsv4_pro` registered with `enabled=False` (gated by `AETHER_DEEPSEEK_ENABLED`).
- Override in `is_enabled()`: a deepseek model is only enabled when **both** `spec.enabled` AND `os.environ.get("AETHER_DEEPSEEK_ENABLED") == "true"`.
- New test file: `tests/providers/test_deepseek.py` — mirrors the patterns in `test_token_accountant.py`. Includes:
  - `build_request` produces correct URL, headers, payload for each combination of {system, tools, thinking on/off}.
  - `parse_usage` correctly extracts cache-hit, cache-miss, reasoning tokens from the canonical response shape.
  - End-to-end: `call_sync(model="dsv4_flash", ...)` against a `respx`-mocked DeepSeek endpoint, asserts UVT and COGS arithmetic and ledger commit.
- Integration test (only runs if `DEEPSEEK_TEST_KEY` is set, marked `@pytest.mark.integration`).

### Acceptance

- Unit tests pass against `respx`-mocked endpoint (offline).
- Integration test passes against live DeepSeek when `DEEPSEEK_TEST_KEY` is set.
- Reasoning-token billing policy from decision 1 is enforced in `parse_usage` (`reasoning_tokens` populated; UVT formula updated per decision).
- Both V4 entries appear in `MODELS` but `is_enabled()` returns False unless the env flag is on.

### Risks

- DeepSeek's `tools` schema diverges from OpenAI (e.g. `function.parameters` JSON Schema dialect drift) → **mitigation:** integration test uses a real tool definition copied from the live agent; assert tool round-trip.
- `thinking` parameter not yet documented for V4 — relying on Apidog reference → **mitigation:** integration test runs identical prompt with `thinking={"type":"enabled"}` and `{"type":"disabled"}`, asserts `reasoning_tokens > 0` only for enabled.

---

## Phase 3 — Cache-hit canary

**Effort:** 0.5d. **Gate:** Cron green for 3 consecutive nights.

### Deliverables

- New test: `tests/integration/test_deepseek_cache_canary.py`.
  - Sends a 1500-token system prompt twice, 5 seconds apart, against live DeepSeek API using `DEEPSEEK_TEST_KEY`.
  - Asserts `prompt_cache_hit_tokens > 1024` on the second response.
- Cron entry on VPS2: nightly at 03:00 UTC, runs the canary, posts result to `#aether-canary` Slack channel (existing webhook).
- Alert: 2 consecutive failures → page on-call.

### Acceptance

- Three consecutive nights pass with cache-hit detected.
- Failure path tested by mutating the system prompt mid-test (timestamps in the prompt) → assert hit count drops to 0.

### Risks

- Cache prefix silently broken by dynamically constructed prompts in production → **mitigation:** the canary is the backstop; production observability has a separate metric `deepseek_cache_hit_ratio_p50` that alerts if it drops below 0.7 over 1h.

---

## Phase 4 — Shadow eval

**Effort:** 7 calendar days (passive). **Gate:** Measured COGS-per-task within 10% of model prediction.

### Deliverables

- Shadow-eval harness (small, ~50 LOC) that, when enabled via `AETHER_DEEPSEEK_SHADOW_PCT=1`:
  - On each `qopc_load=heavy` request, with probability 1%, also fires a parallel V4-Pro call **after** Sonnet returns (so user latency is unaffected).
  - V4-Pro response is **not returned to the user**. Cost is recorded to `usage_events` with a `shadow=true` flag (new boolean column, default false).
  - Results compared offline: predicted COGS-per-task (from registry math) vs measured COGS-per-task (from shadow ledger rows).

### Acceptance

- Median shadow-vs-Sonnet COGS ratio over 7 days within 10% of model prediction.
- 99th-percentile reasoning-token count documented (informs whether `qopc_load=light` should ship with `thinking=disabled`).
- No customer-visible regression in latency or error rate during shadow window.

### Risks

- Shadow calls double DeepSeek API spend even though they don't bill the user → **mitigation:** 1% sampling caps shadow spend at ~$50/day at current heavy-traffic volume; monitored daily.
- Shadow harness silently fails (hard to detect without users seeing it) → **mitigation:** harness logs success/error at INFO; alert on >5% error rate over 1h.

---

## Phase 5 — Soft launch

**Effort:** 3–7d. **Gate:** No customer-reported issues for the window.

### Deliverables

- Flip `AETHER_DEEPSEEK_ENABLED=true` on VPS2.
- V4 available **only via explicit `model="dsv4_flash"` or `model="dsv4_pro"` parameter** on the API. Router still routes to Claude.
- Customer-facing privacy page updated to document the data path (PRC infra) before flip.
- Internal dogfood: route the AetherCloud-internal automation pipeline (`agent/claude_agent.py` for vault scans) through V4-Flash for 48h, observe.
- Status page entry added: "DeepSeek V4 (beta) — explicit opt-in only."

### Acceptance

- 7 days of opt-in production traffic: zero CRITICAL incidents, <1% increase in 5xx rate.
- Internal dogfood uncovers no behavioral regressions on tool-use, prompt-caching, or stop-reason mapping.
- Cost observability dashboard shows V4 calls landing within shadow-eval predictions.

### Risks

- Customer compliance escalation on PRC routing → **mitigation:** `jurisdiction` field gating (decision 3) blocks V4 for users with `compliance_flag=true`. Privacy page updated before flip.
- Tool-call format drift between V4 and Claude that only surfaces under load → **mitigation:** dogfood stage runs against the existing tool suite in the vault scanner; bugs surface in 48h before opening to users.

---

## Phase 6 — Router integration *(separate follow-up PR)*

**Effort:** TBD. **Gate:** Phase 5 stable for ≥1 week.

### Scope

- Update `qopc_load → model_key` mapping in `lib/router.py`.
- V4-Flash becomes default for `qopc_load=light`.
- V4-Pro available as opt-in for `qopc_load=heavy` tasks where benchmarks beat Sonnet on internal eval.
- PR depends on a separate eval harness producing a head-to-head comparison.

**Out of scope for this design.** Tracked in a separate doc when Phase 5 has run for a week.

---

## Open decisions (must answer before Phase 0 cut)

| # | Decision | Recommendation |
|---|---|---|
| 1 | Reasoning-token billing — A (silent), B (visible only), or C (bill all + surface separately) | **C** |
| 2 | Cache-pricing field rework now or defer to Gemini | **Now** |
| 3 | Add `jurisdiction` field to `ModelSpec` now or later | **Now** |
| 4 | Shadow-eval scope — 1% heavy / 7 days, or skip to opt-in soft-launch | **1% / 7d** |
| 5 | Confirm router stays untouched in v1 | **Yes** |

---

## Quick deliverables checklist (final PR sequence)

By the end of the work, one PR (or three sequenced — Phase 0 alone, Phases 1–2, Phases 3–5):

1. **Phase 0** — `lib/providers/anthropic.py` extracted with zero behavior change. `AnthropicResponse → ProviderResponse` rename + alias.
2. **Phase 1** — `ModelSpec` rewritten with new cache fields. Anthropic entries migrated to identical-COGS values. Supabase migration applied: `usage_events` adds `reasoning_tokens` + `cache_write_tokens`; `uvt_balances` adds `provider_uvt jsonb`; `rpc_record_usage` updated for both. Parity suite still passes.
3. **Phase 2** — `lib/providers/deepseek.py` complete. `dsv4_flash` + `dsv4_pro` entries with `enabled=False`. `tests/providers/test_deepseek.py` mirrors Anthropic patterns.
4. **Phase 3** — Nightly canary integration test against live DeepSeek API (`DEEPSEEK_TEST_KEY`).
5. **Phase 4** — Shadow-eval harness + 7-day observation window.
6. **Phase 5** — Flag flipped, opt-in only, customer privacy page updated.
7. **Phase 6 (separate PR)** — Router updated after ≥1 week stability.

_Aether Systems LLC — Patent Pending_
