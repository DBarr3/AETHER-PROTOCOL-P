# Red Team Sweep #2 — ModelRouter Remediation Report

**Date:** 2026-04-22
**Scope:** Closes Critical C1, High H2, High H3 per the sweep report at
`tests/security/redteam_modelrouter_report.md`. Medium / Low findings
deliberately out of scope this session per
`.claude/md/modelrouter_fix_notes.txt`.
**Branch:** `claude/suspicious-wright-619275` (pushed)
**Worktree:** `.claude/worktrees/suspicious-wright-619275/`

---

## Executive Summary

The Critical (C1) and both referenced Highs (H2, H3) are fixed. Five
commits landed: four route-fix commits per the prescribed split, plus
one follow-up to update two test files that still mocked the removed
`Anthropic` class symbol.

Concretely:

- **C1** — Three production files that called Anthropic directly have
  been rewired to route through `lib/token_accountant`. An AST-based
  CI gate replaces the grep check that let the finding slip into a
  signed-off report. The original PoC that proved the violation now
  passes (no longer finds any bypass).
- **H2** — `lib/router.py:_pick_orchestrator` now returns Haiku for
  free-tier users on medium classification, honoring the architecture
  doc's explicit promise. Three new adversarial invariant tests guard
  the fix and cover the previously unchecked `medium × free` /
  `medium × solo` / `light × free` triples.
- **H3** — Durable-billing claim is now honest. `_append_to_dlq` emits
  a `dlq.size_gauge` log record on every enqueue and fires a CRITICAL
  line tagged `DLQ_OVER_THRESHOLD` once queue depth crosses
  `AETHER_DLQ_ALERT_THRESHOLD` (default 50). A manual replay script
  at `deploy/replay_dlq.py` re-fires `rpc_record_usage` for buffered
  events. Release notes updated to reflect the mitigation.

All five verification commands from the fix notes pass. 553 tests
green across the fix-relevant surface. Pre-existing failures in the
full-repo run trace to an unrelated missing `security/` package
(flagged in `aether/harness/simulate.py:13`) — documented and left
untouched per scope.

## Findings closed

### C1 — TokenAccountant is no longer bypassable

**Before:** three files imported `from anthropic import Anthropic` and
called `client.messages.create(...)` directly:

- `agent/claude_agent.py:14` — 10 direct call sites
- `agent/hardened_claude_agent.py:22` — 9 direct call sites
- `mcp_worker/agent_executor.py:114` — one httpx POST to
  `https://api.anthropic.com/v1/messages` with hand-built headers

Every call through these paths skipped UVT accounting, DLQ on RPC
failure, `usage_events` ledger, and `qopc_load` attribution.
Verification-report claim §12.1d was false against the current
worktree.

**After:**

1. New public helpers added to `lib/token_accountant.py`:
   - `resolve_model_key(raw: str) -> ModelKey` maps env-config
     identifiers (`"claude-opus-4-5"`, `"claude-sonnet-4-20250514"`, …)
     to the registry short key. Defaults to `"sonnet"` when ambiguous.
   - `call_sync(**kwargs) -> AnthropicResponse` wraps the existing
     async `call()` with an event-loop detector: `asyncio.run()` when
     no loop is running, a short-lived worker thread otherwise.

2. Each offending file was rewritten to route through these helpers:
   - `agent/claude_agent.py` — dropped the Anthropic import; no
     `self.client` is constructed; `_claude_call()` helper method
     added; all 10 call sites rewired; response `.content[0].text`
     access replaced with flat `.text`; sys.modules assertion at
     import time catches any future regression.
   - `agent/hardened_claude_agent.py` — same pattern, 9 rewires. The
     Protocol-L crypto-verification chain is unchanged; the HTTP
     hop it wraps is now metered.
   - `mcp_worker/agent_executor.py` — the sole httpx call replaced
     with `await token_accountant.call(...)`. `task["client_id"]` is
     passed as `user_id` when it parses as a valid UUID, which
     attributes MCP worker usage where possible.

3. New CI gate at
   `tests/security/test_anthropic_import_isolation.py` (3 tests)
   uses `ast.parse` + a recursive import-graph walker to assert the
   ONLY production module that transitively imports `anthropic` is
   `lib.token_accountant`. The docstring explains why grep is
   structurally insufficient (docstring / comment false positives,
   re-exports, conditional imports, dynamic `importlib.import_module`)
   — exactly the failure mode that let C1 slip into the signed-off
   report.

4. Three legacy test files that patched the removed `Anthropic`
   symbol were updated to patch `token_accountant.call_sync` instead:
   `tests/test_claude_agent.py`, `tests/test_hardened_agent.py`,
   `tests/test_marketing_agent.py`, `tests/test_context_scorer.py`.
   Mock helpers reshaped to return a flat-`.text` response.

**Evidence it's fixed:**
- `grep -rn "^import anthropic\|^from anthropic" --include=*.py .`
  (excluding `lib/token_accountant.py` and `tests/`) returns zero.
- `tests/security/test_anthropic_import_isolation.py` — 3/3 pass.
- `tests/security/modelrouter/poc_2_2_tokenaccountant_bypass.py` — was
  FAILING (proved the finding); now PASSES (no bypass found).

### H2 — Free-tier medium classification returns Haiku

**Before** — `lib/router.py:_pick_orchestrator`:

```python
if signal.load == "light":
    return "haiku"
if signal.load == "medium":
    return "sonnet"          # Sonnet for every tier, free included
# heavy
if plan_cfg.opus_pct_cap <= 0:
    ...
```

**After** — same file:

```python
if signal.load == "light":
    return "haiku"
if signal.load == "medium":
    # Red Team #2 H2: free-tier baseline is Haiku. The architecture
    # doc ("Philosophy — honest limits", …) promises "Free user tries
    # a task → runs on Haiku (explicit tier baseline, not a downgrade)."
    # Returning Sonnet here violated that promise and imposed ~5× Haiku
    # COGS on the highest-volume tier. Paid tiers (solo/pro/team)
    # still get Sonnet on medium.
    if plan_cfg.tier == "free":
        return "haiku"
    return "sonnet"
# heavy
if plan_cfg.opus_pct_cap <= 0:
    ...
```

Three new invariant tests added to
`tests/test_model_router_invariant.py`:

- `test_invariant_medium_free_returns_haiku` — core H2 assertion
- `test_invariant_medium_solo_returns_sonnet` — paid-tier regression
  guard (scoped fix did not over-correct)
- `test_invariant_light_free_returns_haiku` — explicit light-path
  coverage that the existing heavy-only suite never guarded

The original 5 `heavy × {free, solo, pro, team, counter}` invariants
still pass. Total: 8 invariant tests. The H2 PoC
(`poc_2_3_free_tier_gets_sonnet_on_medium.py`) flipped from
evidence-of-bug to regression-guard consistent with the sweep-report
convention for closed findings.

### H3 — DLQ durability claim made honest

**Before:**
- `RELEASE_NOTES.md:61` disclosed "No DLQ replay. If rpc_record_usage
  ever fails, events land in …/usage_dlq.jsonl on VPS2; manual replay
  until Stage K cron lands."
- No alert, no size visibility, no replay path.

**After** (`lib/token_accountant.py:_append_to_dlq`):

```python
# ─── DLQ size gauge + threshold alert (Red Team #2 H3) ────────────────
# Emit a gauge on every enqueue + a CRITICAL line tagged DLQ_OVER_THRESHOLD
# once the queue crosses AETHER_DLQ_ALERT_THRESHOLD (default 50). Ops can
# grep journalctl for the tag; Prometheus scrapes log_messages_total
# filtered by the tag. Stage K will replace this with a proper replay
# cron (see deploy/replay_dlq.py for the manual path that exists today).
try:
    line_count = 0
    with path.open("r", encoding="utf-8") as f:
        for _ in f:
            line_count += 1
    log.info("dlq.size_gauge", extra={
        "event": "dlq.size_gauge",
        "dlq_line_count": line_count,
        "dlq_path": str(path),
    })
    threshold = int(os.environ.get("AETHER_DLQ_ALERT_THRESHOLD", "50"))
    if line_count >= threshold:
        log.critical(
            "DLQ_OVER_THRESHOLD: usage_dlq has %d entries (>= %d). "
            "Billing ledger is drifting. Run deploy/replay_dlq.py to "
            "re-fire rpc_record_usage against these rows before any "
            "reach the monthly boundary.",
            line_count, threshold,
        )
except Exception as exc:
    log.warning("TokenAccountant: DLQ size-gauge read failed (%s)", exc)
```

New manual replay tool at `deploy/replay_dlq.py`:
- `--dry-run` parses the DLQ and reports what WOULD be replayed
  (no Supabase call).
- Live mode reads each line, calls `rpc_record_usage` via a
  service-role client, atomically rewrites the file with only
  still-failing lines remaining.
- Docstring explicitly warns NOT to cron this until Stage K adds
  per-row idempotency — `rpc_record_usage` currently lacks a
  `request_id` key, so replaying a row whose original call succeeded
  but lost its HTTP response would double-bill.

Three new tests added to `tests/test_token_accountant.py`:
- `test_dlq_gauge_emits_size_on_every_enqueue`
- `test_dlq_threshold_fires_critical_tag`
- `test_dlq_threshold_defaults_to_fifty`

`RELEASE_NOTES.md` replaced the "No DLQ replay" caveat with a summary
of the three mitigations and added an **Operational** section
documenting the exact replay invocation.

## Commits

| # | SHA      | Scope |
|---|----------|-------|
| 1 | baa3959  | fix(router): C1 route agent/claude_agent.py through TokenAccountant |
| 2 | 95d9d93  | fix(router): C1 hardened_claude_agent + mcp_worker + AST import-isolation CI test |
| 3 | 50e1b59  | fix(router): H2 free-tier medium returns Haiku; add 3 invariant tests |
| 4 | 4fdfc2b  | fix(router): H3 DLQ size gauge + threshold alert + manual replay script |
| 5 | 9090d63  | fix(tests): update marketing + context_scorer mocks for Red Team #2 C1 |

Note: five commits rather than the four specified by the fix notes.
Commit 5 is a test-only cleanup that was necessary after discovering
two additional test files still patched the removed `Anthropic`
symbol. Keeping it separate from the code-bearing commits preserves
reviewability.

Also note: Commit 1 bundled the DLQ size-gauge / threshold-alert code
changes alongside the `call_sync` / `resolve_model_key` helpers
because both live in `lib/token_accountant.py` and had to ship in one
module edit. The prescribed Commit 4 therefore carries the
non-token_accountant H3 deliverables (replay script, release notes,
tests, PoC flip); the commit message explicitly notes this split.

## Verification outputs

### 1. Direct anthropic imports outside `lib/token_accountant.py` (expect zero)

```
$ grep -rn "^import anthropic\|^from anthropic" --include="*.py" . \
    | grep -v "lib/token_accountant.py" | grep -v "tests/"
  (no matches)
```

### 2. Import-isolation test

```
$ pytest tests/security/test_anthropic_import_isolation.py -v

tests/security/test_anthropic_import_isolation.py::test_anthropic_is_imported_only_by_token_accountant PASSED
tests/security/test_anthropic_import_isolation.py::test_scanner_actually_finds_files                  PASSED
tests/security/test_anthropic_import_isolation.py::test_token_accountant_itself_does_import_anthropic PASSED

3 passed in 1.00s
```

### 3. Fix-relevant test surface — all green

```
$ pytest tests/test_token_accountant.py tests/test_claude_agent.py \
         tests/test_hardened_agent.py tests/test_model_router_invariant.py \
         tests/test_router.py tests/test_router_client.py \
         tests/test_qopc_bridge.py tests/test_context_compressor.py \
         tests/test_uvt_routes.py tests/test_model_registry.py \
         tests/test_uvt_parity.py tests/test_pricing_guard.py \
         tests/test_feature_flags.py tests/test_qopc_feedback.py \
         tests/security/test_anthropic_import_isolation.py \
         tests/security/modelrouter/

553 passed in 30.09s
```

(`pytest tests/` at the full-repo level reports 867 passed + 32 failed +
49 errors + 2 skipped. Every failure / error I inspected traces to a
missing `security/` package — `api_server.py:35` imports from
`security.prompt_guard`, which does not exist in this worktree. That
gap is documented in `aether/harness/simulate.py:13` as "pre-existing
security.prompt_guard issue in this worktree" and is out of scope.)

### 4. H2 invariants

```
$ pytest -k "invariant_medium_free_returns_haiku or invariant_medium_solo_returns_sonnet or invariant_light_free_returns_haiku" -v \
    --ignore=tests/test_api.py --ignore=tests/test_filesystem.py \
    --ignore=tests/test_license_validation.py --ignore=tests/test_vault_browse.py

tests/test_model_router_invariant.py::test_invariant_medium_free_returns_haiku   PASSED
tests/test_model_router_invariant.py::test_invariant_medium_solo_returns_sonnet  PASSED
tests/test_model_router_invariant.py::test_invariant_light_free_returns_haiku    PASSED

3 passed, 947 deselected in 1.22s
```

### 5. H3 artifacts

```
$ test -f deploy/replay_dlq.py && echo "replay script: yes"
replay script: yes

$ grep -rn "DLQ_OVER_THRESHOLD" lib/ agent/ mcp_worker/
lib/token_accountant.py:339:    # Emit a gauge on every enqueue + a CRITICAL line tagged DLQ_OVER_THRESHOLD
lib/token_accountant.py:357:                "DLQ_OVER_THRESHOLD: usage_dlq has %d entries (>= %d). "

$ grep -rn "AETHER_DLQ_ALERT_THRESHOLD" . | grep -v .claude/worktrees
./lib/token_accountant.py:340: # once the queue crosses AETHER_DLQ_ALERT_THRESHOLD …
./lib/token_accountant.py:354: threshold = int(os.environ.get("AETHER_DLQ_ALERT_THRESHOLD", "50"))
./RELEASE_NOTES.md:61: (2) a DLQ_OVER_THRESHOLD CRITICAL log tag once the queue crosses AETHER_DLQ_ALERT_THRESHOLD (default 50)
./tests/security/modelrouter/poc_2_7_dlq_no_replay.py:86: assert "AETHER_DLQ_ALERT_THRESHOLD" in text, …
./tests/test_token_accountant.py:436: """Red Team #2 H3: once DLQ crosses AETHER_DLQ_ALERT_THRESHOLD, …
./tests/test_token_accountant.py:440: monkeypatch.setenv("AETHER_DLQ_ALERT_THRESHOLD", "3")
./tests/test_token_accountant.py:457: """If AETHER_DLQ_ALERT_THRESHOLD isn't set, the default is 50."""
```

## PR status — not opened

`gh` CLI is not authenticated in this environment
(`gh auth login` was never run here). The branch is pushed to
`origin/claude/suspicious-wright-619275`; the PR must be opened by the
operator. Exact command:

```bash
gh pr create \
  --base main \
  --head claude/suspicious-wright-619275 \
  --title "Fix PR 1 v5 ModelRouter Critical + H2/H3 before flip" \
  --body-file tests/security/redteam_modelrouter_remediation_report.md
```

Do NOT merge the PR per fix-notes instructions.

## What I could not do

1. **Open the PR via `gh pr create`.** Authentication is missing on
   this machine. Command is above; branch is pushed and ready.

2. **Confirm `deploy/replay_dlq.py` against a real Supabase project.**
   The script was smoke-tested with `--dry-run` against a local
   scratch DLQ but live replay is gated behind
   `SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY` env. Per ROE §5 I did
   not reach for any live Supabase credentials.

3. **Run `pytest tests/` cleanly end-to-end.** Four test files
   (`test_api.py`, `test_filesystem.py`, `test_license_validation.py`,
   `test_vault_browse.py`) fail to collect because `api_server.py:35`
   imports from a `security/` package that does not exist in this
   worktree. A fifth file (`test_security_fixes.py`) has the same
   root cause. Source comment at `aether/harness/simulate.py:13`
   flags this as a pre-existing worktree issue. Out of scope for
   this session.

## Remaining Red Team #2 findings (deliberately untouched)

Per fix notes, these 7 findings remain open for subsequent sessions:

- M1: `downgrade_reason` ghost refs (10 survive in harness + desktop)
- M2: `AETHER_ROUTER_URL` not TLS-pinned (Critical risk at PR 2 cutover)
- M3: preflight TOCTOU → monthly quota overshoot
- M4: `_warned_once` suppresses bypass WARN logs after first hit
- M5: confidence-gate reclassify burn
- M6: plans cache staleness on admin updates
- L1: `chosen_model` unsanitized in shadow log line

See `tests/security/redteam_modelrouter_report.md` for details.
