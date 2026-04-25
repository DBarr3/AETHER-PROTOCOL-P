# DeepSeek V4 — Pricing Reference

**Status:** Pre-implementation. Approve before code changes.
**Date:** 2026-04-25
**Author:** AetherCloud planning
**Source of truth:** [DeepSeek API pricing](https://api-docs.deepseek.com/quick_start/pricing) · cross-referenced [Apidog rate card](https://apidog.com/blog/deepseek-v4-api-pricing/)
**Units:** USD cents per 1M tokens (matches `lib/model_registry.py` convention).

---

## 1. V4 rate card

| Model ID | Input miss | Input hit | Output | Context | Max output | Cache hit ratio |
|---|---|---|---|---|---|---|
| `deepseek-v4-flash` | 14.0 ¢/M | 2.8 ¢/M | 28.0 ¢/M | 1M | 384K | 5× off (80%) |
| `deepseek-v4-pro`   | 174.0 ¢/M | 14.5 ¢/M | 348.0 ¢/M | 1M | 384K | 12× off (~91.7%) |

**Mechanics that affect billing:**

- Cache hits require a **byte-exact prefix ≥1024 tokens** matching a previous request from the same account. Hits are automatic — no opt-in, no headers, no `cache_control` blocks.
- **Thinking and non-thinking share the same per-token rate.** Thinking mode emits `completion_tokens_details.reasoning_tokens` which is **included in `completion_tokens`** and bills at the full output rate. Reasoning bursts of 10K–50K tokens are routine on V4-Pro hard problems.
- **No off-peak discount** on V4 (was a V3.2 feature; V4 rate card is flat as of 2026-04-25).
- **Legacy aliases `deepseek-chat` / `deepseek-reasoner` are deprecating.** Do not register either in `MODELS`.
- **No 200K-tier price break** (unlike Gemini). Flat across the full 1M window.

---

## 2. Comparison vs current registry

Current `MODELS` (Anthropic only, in cents/M):

| Key | Input | Output | Cache discount | Cache hit input |
|---|---|---|---|---|
| `haiku`  | 80.0   | 400.0   | 0.90 | 8.0   |
| `sonnet` | 300.0  | 1500.0  | 0.90 | 30.0  |
| `opus`   | 1500.0 | 7500.0  | 0.90 | 150.0 |

Proposed V4 entries:

| Key | Provider | Input | Output | Cache read | Cache write |
|---|---|---|---|---|---|
| `dsv4_flash` | deepseek | 14.0  | 28.0  | 2.8  | None (billed at miss rate) |
| `dsv4_pro`   | deepseek | 174.0 | 348.0 | 14.5 | None (billed at miss rate) |

### Where V4 lands

- **V4-Flash output (28 ¢/M)** is **14× cheaper than Haiku output (400 ¢/M)** — opens a new "cheap-but-frontier" class below Haiku. Today `qopc_load=light` routes to Haiku; V4-Flash could become the new floor.
- **V4-Pro output (348 ¢/M)** sits **between Sonnet (1500) and Haiku (400)** with frontier-class benchmarks (LiveCodeBench 93.5, Codeforces 3206 per Apidog). Effectively "Opus quality at sub-Haiku price" if benchmarks hold in eval.
- **V4-Pro cache-hit input (14.5 ¢/M)** is **cheaper than Haiku's full input rate (80 ¢/M)** — for stable system prompts + tool schemas (which we cache aggressively today), V4-Pro is near-free on input after warm-up.

### Margin implication

Without changing Stripe tier prices, swapping a heavy-load workload from Sonnet to V4-Pro drops COGS-per-UVT by **~76% on output and ~50% on input** at list. Even after a 30% safety/margin buffer, V4-Pro lets us **triple the per-tier UVT allowance on Solo/Pro** without changing margin. This is the strategic prize — not "another model," but **rewriting the router's cost-equivalence table** so the cheap tier serves substantially more volume.

---

## 3. Response usage object — verbatim

```json
"usage": {
  "prompt_tokens": 1247,
  "prompt_cache_hit_tokens": 1024,
  "prompt_cache_miss_tokens": 223,
  "completion_tokens": 8421,
  "completion_tokens_details": { "reasoning_tokens": 7180 },
  "total_tokens": 9668
}
```

Maps cleanly to the existing envelope:
- `prompt_tokens` → `input_tokens`
- `prompt_cache_hit_tokens` → `cached_input_tokens`
- `completion_tokens` → `output_tokens` (already includes reasoning)
- `completion_tokens_details.reasoning_tokens` → **new** `reasoning_tokens` field

---

## 4. UVT formula — what changes

Today:

```
UVT      = (input − cached_input) + output
COGS¢    = (input − cached) · input_rate
         + cached           · input_rate · (1 − cache_discount)
         + output           · output_rate
```

The formula still works for V4. **Three subtle gaps must close before V4 ships:**

### Gap 1 — Reasoning-token billing policy *(decision pending)*

`reasoning_tokens` is hidden CoT — user pays but doesn't see it.

| Option | UX | Margin risk |
|---|---|---|
| A — bill all `completion_tokens` silently | Surprise bills on hard prompts | None |
| B — bill only visible completion | Friendly | **Bad on V4-Pro** — 50K reasoning loop eats ~70% of COGS |
| **C (recommended)** — bill all, expose `reasoning_tokens` separately in usage panel | "burned 8K visible + 7K reasoning UVT", user can flip thinking off | None — matches OpenAI o-series and Anthropic extended thinking |

### Gap 2 — Single `cache_discount` field can't represent cache-write costs

Anthropic charges 1.25× input rate to **write** a cache entry, then 0.10× to **read**. Today `cache_discount=0.90` conflates both. DeepSeek has **no cache-write surcharge**. Gemini (next on roadmap) charges separately for write, read, and **storage per hour**.

**Recommended now (in same PR):** replace `cache_discount: float` with three explicit fields on `ModelSpec`:

```python
cache_read_rate_cents_per_million:        float
cache_write_rate_cents_per_million:       Optional[float]   # None → billed at miss rate (DeepSeek, OpenAI)
cache_storage_rate_cents_per_million_hour: Optional[float]  # None → no storage charge
```

Anthropic migration values that produce **identical COGS** to today (regression-test the math):
- `cache_read = input_rate × 0.10`
- `cache_write = input_rate × 1.25`
- `cache_storage = None`

### Gap 3 — Provider dispatch in `TokenAccountant`

Hardcoded to `api.anthropic.com`. Headers (`x-api-key`, `anthropic-version`, `anthropic-beta`) and prompt-caching mechanism (`cache_control: ephemeral` blocks) are Anthropic-specific. Refactor required (Phase 0).

---

## 5. New `ModelSpec` (Phase 1 target shape)

```python
ModelKey = Literal["haiku", "sonnet", "opus", "gpt5", "gemma", "dsv4_flash", "dsv4_pro"]

@dataclass(frozen=True)
class ModelSpec:
    key: ModelKey
    provider: Literal["anthropic", "openai", "google", "deepseek"]
    model_id: str
    input_cents_per_million: float
    output_cents_per_million: float

    cache_read_cents_per_million: float
    cache_write_cents_per_million: Optional[float] = None
    cache_storage_cents_per_million_hour: Optional[float] = None

    reports_reasoning_tokens: bool = False        # provider response splits reasoning out

    context_window_tokens: int = 0
    supports_prompt_caching: bool = False
    enabled: bool = False
    # TBD per decision 3:
    # jurisdiction: Literal["us", "cn", "self"] = "us"
```

V4 entries:

```python
"dsv4_flash": ModelSpec(
    provider="deepseek", model_id="deepseek-v4-flash",
    input_cents_per_million=14.0, output_cents_per_million=28.0,
    cache_read_cents_per_million=2.8,
    cache_write_cents_per_million=None,
    cache_storage_cents_per_million_hour=None,
    reports_reasoning_tokens=True,
    context_window_tokens=1_000_000,
    supports_prompt_caching=True,
    enabled=False,                  # gated by AETHER_DEEPSEEK_ENABLED
),
"dsv4_pro": ModelSpec(
    provider="deepseek", model_id="deepseek-v4-pro",
    input_cents_per_million=174.0, output_cents_per_million=348.0,
    cache_read_cents_per_million=14.5,
    cache_write_cents_per_million=None,
    cache_storage_cents_per_million_hour=None,
    reports_reasoning_tokens=True,
    context_window_tokens=1_000_000,
    supports_prompt_caching=True,
    enabled=False,
),
```

`cost_usd_cents()` updated to use `cache_read_cents_per_million` directly (no more `(1 - cache_discount)` multiplier).

---

## 6. Risks affecting pricing

| Risk | Severity | Mitigation |
|---|---|---|
| Reasoning-token surprise bills | Medium | Surface `reasoning_tokens` separately from day one. Cap thinking via `thinking={"type":"disabled"}` for `qopc_load=light`. Per-call UVT spike alerts at 5× user's 90th-percentile call size. |
| Cache prefix silently fails (timestamps in prompts) | Medium | Unit test runs same 1500-token system prompt twice, asserts `prompt_cache_hit_tokens > 0`. Nightly canary against live API. |
| V4-Pro thinking-mode margin error | Medium | **Shadow eval before flip:** 1% of `qopc_load=heavy` traffic → V4-Pro shadow (record cost, return Sonnet response) for 7 days. Compare measured COGS-per-task to model. |
| Data jurisdiction (PRC infra) | High for Enterprise | `jurisdiction` field on `ModelSpec`; router excludes `cn` for users with `compliance_flag=true`. Document data path before flipping `enabled=true`. |
| Alias deprecation timing | Low | Don't register `deepseek-chat` / `deepseek-reasoner`. Pricing-scan cron (weekday 7 AM) catches new/missing IDs. |
| API outage (no SLA) | Low | V4 is additive, never the only path. Router falls back to Sonnet on 5xx or timeout >10s. |

---

## 7. Open decisions (must answer before Phase 0)

1. Reasoning-token billing: A / B / **C**?
2. Cache-pricing rework now or defer? **Now (recommended)**
3. Add `jurisdiction` field now or later? **Now (recommended)**
4. Shadow-eval scope: 1%/7d (**recommended**) or skip?
5. Confirm router untouched in v1? **Yes (recommended)**

---

## 8. Sources

- DeepSeek API pricing — https://api-docs.deepseek.com/quick_start/pricing
- DeepSeek chat completions usage object — https://api-docs.deepseek.com/api/create-chat-completion
- Apidog rate card + benchmarks — https://apidog.com/blog/deepseek-v4-api-pricing/
- ArXivIQ DSA architecture writeup — https://arxiviq.substack.com/p/deepseek-v4-towards-highly-efficient
- Live `lib/model_registry.py` and `lib/token_accountant.py` (read 2026-04-25)

_Aether Systems LLC — Patent Pending_
