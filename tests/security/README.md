# Security Reports Index — `tests/security/`

Single-source-of-truth for all red-team reports, per-finding status, and
verification commands. Every assertion links to the source report section.

---

## Section 1 — Report Inventory

| File | Purpose | Date | Status |
|---|---|---|---|
| [tests/security/pr1_v5_verification_report.md](pr1_v5_verification_report.md) | Stage D verification sweep — signed off build checklist and grep checks for PR 1 v5 | 2026-04-22 | Historical — §12.1d claim proved false by Sweep #2 C1 |
| [tests/security/redteam_policygate_report.md](redteam_policygate_report.md) | Red Team Sweep #1 — 19 findings (4 Critical, 5 High, 6 Medium, 4 Low/Info) on PolicyGate (TypeScript `site/`) | 2026-04-22 | Current |
| [tests/security/redteam_modelrouter_report.md](redteam_modelrouter_report.md) | Red Team Sweep #2 — 11 findings (1 Critical, 3 High, 6 Medium, 1 Low) on ModelRouter (Python `lib/`) | 2026-04-22 | Current |
| [tests/security/redteam_modelrouter_remediation_report.md](redteam_modelrouter_remediation_report.md) | Per-finding remediation status for Sweep #2 C1, H2, H3 | 2026-04-22 | Current |
| [tests/security/group_a_patch_report.md](group_a_patch_report.md) | Group A patches: Sweep #1 H2, H4, H5 + M1 with before/after matrices and live DB verification | 2026-04-23 | Current |

Future reports (Groups B, C, D) will be added here as they land.

---

## Section 2 — Findings Status Matrix

`PG-` = PolicyGate (Sweep #1) · `MR-` = ModelRouter (Sweep #2)

| ID | Severity | Summary | Status | Fix SHA | Source |
|---|---|---|---|---|---|
| [PG-C1](redteam_policygate_report.md#c1--client-supplied-opuspctmtd-bypasses-opus_pct_cap-gate) | Critical | Client-supplied `opusPctMtd` bypasses `opus_pct_cap` gate | ✅ Fixed | `3972389` | Sweep #1 §C1 |
| [PG-C2](redteam_policygate_report.md#c2--client-supplied-uvtbalance-bypasses-insufficientuvtbalance-gate) | Critical | Client-supplied `uvtBalance` bypasses balance gate | ✅ Fixed | `85b060f` | Sweep #1 §C2 |
| [PG-C3](redteam_policygate_report.md#c3--client-supplied-activeconcurrenttasks-bypasses-concurrency_cap-gate) | Critical | Client-supplied `activeConcurrentTasks` bypasses concurrency cap | ✅ Fixed | `d22183c` | Sweep #1 §C3 |
| [PG-C4](redteam_policygate_report.md#c4--production-audit-writer-is-never-wired-routing_decisions-stays-empty) | Critical | Production audit writer never wired; `routing_decisions` always empty | ✅ Fixed | `f407c97` | Sweep #1 §C4 |
| [PG-H1](redteam_policygate_report.md#h1--python-shadow-caller-hardcodes-gate-input-fields) | High | Python shadow caller hardcodes `opusPctMtd=0 / uvtBalance=1B / tasks=0` | ✅ Fixed | `1075db1` | Sweep #1 §H1 |
| [PG-H2](redteam_policygate_report.md#h2--predicted_uvt_cost-integer-overflow--dropped-audit-row) | High | `predicted_uvt_cost` int32 overflow → silently dropped audit row | ✅ Fixed | `9165bb0` | Sweep #1 §H2 |
| [PG-H3](redteam_policygate_report.md#h3--no-ip--user-rate-limit-on-apiinternalrouterpick) | High | No IP / user rate limit on `/api/internal/router/pick` | 🔜 Deferred to Group B | — | Sweep #1 §H3 |
| [PG-H4](redteam_policygate_report.md#h4--audit-error-handler-swallows-silently-by-default) | High | Audit error handler swallows silently; no alert path | ✅ Fixed | `89d5150` | Sweep #1 §H4 |
| [PG-H5](redteam_policygate_report.md#h5--getopuspctmtd-fails-open-on-db-error-dead-today-live-after-c1-fix) | High | `getOpusPctMtd` returns `0` (fail-open) on DB error | ✅ Fixed | `fc7a796` | Sweep #1 §H5 |
| [PG-M1](redteam_policygate_report.md#m1--partition-window-ends-2027-03-31-no-roll-forward-job) | Medium | Partition window ends 2027-03-31; no roll-forward job | ✅ Fixed | `dec2bc1` | Sweep #1 §M1 |
| [PG-M2](redteam_policygate_report.md#m2--hand-rolled-constant-time-compare-leaks-token-length) | Medium | Hand-rolled constant-time compare leaks token length; two copies | 🔜 Deferred to Group B | — | Sweep #1 §M2 |
| [PG-M3](redteam_policygate_report.md#m3--token-rotation-window-controlled-only-by-env-var-presence) | Medium | Token rotation PREV window unbounded; no TTL or alerting | 🔜 Deferred to Group B | — | Sweep #1 §M3 |
| [PG-M4](redteam_policygate_report.md#m4--trace_id--request_id-echoed-in-response-without-sanitization) | Medium | `traceId`/`requestId` echoed without charset restriction | 🔜 Deferred to Group B | — | Sweep #1 §M4 |
| [PG-M5](redteam_policygate_report.md#m5--plan_caps-hardcoded-without-boot-time-db-assertion) | Medium | `PLAN_CAPS` hardcoded; `startupAssertions.ts` never shipped | 🔜 Deferred to Group B | — | Sweep #1 §M5 |
| [PG-M6](redteam_policygate_report.md#m6--router_configshadow_mode-frozen-but-no-test-that-its-true-at-build-time) | Medium | No CI test asserting `shadow_mode === true` for PR 1 branch | 🔜 Deferred to Group B | — | Sweep #1 §M6 |
| [PG-L1](redteam_policygate_report.md#l1--plain-object-model-id-map-allows-prototype-chain-escape-under-future-requestedmodel) | Low | Plain-object model-id map allows prototype-chain escape | 🔜 Deferred to PR 2 | — | Sweep #1 §L1 |
| [PG-L2](redteam_policygate_report.md#l2--unknownmodelerror-leaks-model_id-in-message-string) | Info | `UnknownModelError` leaks model_id in message | 🔜 Deferred to PR 2 | — | Sweep #1 §L2 |
| [PG-L3](redteam_policygate_report.md#l3--no-http-body-size-limit-configured) | Info | No HTTP body size limit configured | 🔜 Deferred to Group B | — | Sweep #1 §L3 |
| [PG-L4](redteam_policygate_report.md#l4--verification-reports-constant-time-test-is-admitted-weak) | Info | Timing-safe test uses 60% noise ceiling (admitted-weak) | 🔜 Deferred to PR 2 | — | Sweep #1 §L4 |
| [MR-C1](redteam_modelrouter_report.md#c1--tokenaccountant-is-not-the-sole-anthropic-call-site-money-adjacent-invariant-violation) | Critical | TokenAccountant NOT sole Anthropic call site — 3 files bypass accounting | ✅ Fixed | `baa3959` `95d9d93` | Sweep #2 §C1 |
| [MR-H1](redteam_modelrouter_report.md#h1--classifier-prompt-injection-via-context_compressor-tail-trim) | High | Classifier prompt-injection via `context_compressor` tail-trim | 🔜 Deferred to Group C | — | Sweep #2 §H1 |
| [MR-H2](redteam_modelrouter_report.md#h2--free-tier-silently-receives-sonnet-on-medium-classification-architecture-doc-drift) | High | Free-tier receives Sonnet on medium classification (arch doc says Haiku) | ✅ Fixed | `50e1b59` | Sweep #2 §H2 |
| [MR-H3](redteam_modelrouter_report.md#h3--dlq-has-no-replay-mechanism-persistent-un-metered-inference) | High | DLQ has no replay mechanism; un-metered inference on Supabase hiccup | ✅ Fixed | `4fdfc2b` | Sweep #2 §H3 |
| [MR-M1](redteam_modelrouter_report.md#m1--downgrade_reason-ghost-reference-cleanup-incomplete) | Medium | `downgrade_reason` ghost refs in harness + desktop UI still live | 🔜 Deferred to Group C | — | Sweep #2 §M1 |
| [MR-M2](redteam_modelrouter_report.md#m2--aether_router_url-env-var-swap-low-today-critical-at-pr-2-cutover) | Medium | `AETHER_ROUTER_URL` not pinned; token exfil surface at PR 2 cutover | 🔜 Deferred to PR 2 | — | Sweep #2 §M2 |
| [MR-M3](redteam_modelrouter_report.md#m3--concurrent-preflight-toctou--monthly-quota-overshoot) | Medium | Concurrent-preflight TOCTOU → monthly quota overshoot | 🔜 Deferred to PR 2 | — | Sweep #2 §M3 |
| [MR-M4](redteam_modelrouter_report.md#m4--router_policy_bypass-warn-log-suppressed-after-first-hit) | Medium | `_warned_once` suppresses bypass WARN after first hit | 🔜 Deferred to Group C | — | Sweep #2 §M4 |
| [MR-M5](redteam_modelrouter_report.md#m5--confidence-gate-reclassify-burns-a-second-classifier-call-no-bounded-retry) | Medium | Confidence-gate reclassify doubles classifier UVT burn per crafted call | 🔜 Deferred to PR 2 | — | Sweep #2 §M5 |
| [MR-M6](redteam_modelrouter_report.md#m6--routers-_plans_cache-stale-window-on-tier-config-change) | Medium | `_plans_cache` stale on admin plan updates (no TTL / invalidation) | 🔜 Deferred to PR 2 | — | Sweep #2 §M6 |
| [MR-L1](redteam_modelrouter_report.md#l1--chosen_model-logged-unsanitized-in-shadow-path) | Low | `chosen_model` unsanitized in shadow log → log injection | 🔜 Deferred to Group C | — | Sweep #2 §L1 |

**Total findings: 30** (19 Sweep #1 + 11 Sweep #2) · **Fixed: 14** · **Open/Deferred: 16**

---

## Section 3 — Severity Rollup

| | Critical | High | Medium | Low | Info |
|---|---|---|---|---|---|
| **Sweep #1 — PolicyGate** | 4 of 4 fixed | 4 of 5 fixed | 1 of 6 fixed | 0 of 2 fixed | 0 of 2 fixed |
| **Sweep #2 — ModelRouter** | 1 of 1 fixed | 2 of 3 fixed | 0 of 6 fixed | 0 of 1 fixed | — |

---

## Section 4 — Open / Deferred Findings

### Group B — Operational Hygiene (next wave)

- **PG-H3** IP/user rate limit on `/api/internal/router/pick` — not present at all; brute-force and DoS surface.
- **PG-M2** Replace hand-rolled `constantTimeEqual` with `node:crypto.timingSafeEqual`; extract into one shared module (two duplicate copies today).
- **PG-M3** Token rotation PREV window has no TTL or alert; leaked PREV is valid indefinitely until manually unset.
- **PG-M4** `traceId`/`requestId` accept arbitrary chars including newlines; add Zod regex `/^[A-Za-z0-9._:-]{1,128}$/` at schema level.
- **PG-M5** `PLAN_CAPS` hardcoded in constants.ts with no boot-time parity assertion against `public.plans`; drift is invisible.
- **PG-M6** No CI test asserts `ROUTER_CONFIG.shadow_mode === true` — a mis-merge can ship enforcement mode silently.
- **PG-L3** No HTTP body-size cap on the route; Vercel 4.5 MB default is broader than needed.

### Group C — Python Hardening

- **MR-H1** Classifier prompt-injection via `context_compressor` tail-trim + `_parse_signal` first-match: attacker controls QOPC verdict. Strip JSON-looking substrings from `hydrated_context` before classifier call or stop feeding context into the classifier entirely.
- **MR-M1** `downgrade_reason` ghost refs survive in `aether/harness/simulate.py`, `aether/harness/report.py`, and `desktop/pages/uvt-meter/uvt-meter.js:90` (UI reads the dead field). Removing is lossless today but re-adding the field later would silently re-enable the buried-downgrade UX the arch doc forbids.
- **MR-M4** `_warned_once` short-circuits bypass WARN after the first hit per process; OTel counter still increments but log-line-based detection goes blind. Remove flag; delegate rate-limit to log aggregator.
- **MR-L1** `chosen_model` logged verbatim in `lib/uvt_routes.py:234`; attacker with env-write access injects newlines. One-line strip: `re.sub(r"[\x00-\x1f]", "?", shadow.chosen_model)`.

### PR 2 Prerequisites

- **PG-L1** Plain-object `LOGICAL_TO_SHORT` and `MODEL_MULTIPLIERS_V1` allow `obj["toString"]` prototype-chain escape — Low today, escalates to High when PR 2 ships `requestedModel`. Convert to `Map` or add `Object.hasOwn` guards before that flip.
- **PG-L2** `UnknownModelError` message includes raw model_id string — informational now, revisit when user-controlled model values flow through (PR 2 `requestedModel`).
- **PG-L4** Timing-safe compare test uses 60% noise ceiling; not a real timing guarantee. Superseded once PG-M2 lands `crypto.timingSafeEqual`.
- **MR-M2** `AETHER_ROUTER_URL` is mutable env var; `AETHER_INTERNAL_SERVICE_TOKEN` is forwarded to whatever URL it names. Add hostname allowlist or pin before PR 2 shadow→enforce cutover — severity escalates to Critical at that point.
- **MR-M3** Concurrent preflight TOCTOU → quota overshoot bounded by `concurrency_cap × request`. Move balance check inside `rpc_record_usage` transaction (advisory lock or `FOR UPDATE` on `uvt_balances`).
- **MR-M5** Confidence-gate reclassify burns a second Haiku call on crafted ambiguous prompts (~160 UVT overhead each). Acceptable for PR 1; set classifier temperature=0 and consider caching second-pass results in PR 2.
- **MR-M6** `Router._plans_cache` never evicts without explicit `invalidate_plans_cache()`; admin plan-table changes propagate only on worker restart. Add 60s TTL or Postgres NOTIFY subscription.

---

## Section 5 — How to Run Each Verification

### TS test suite (PolicyGate)

```bash
cd site && npm test
# Expect: 15 test files, 111+ tests passing
```

### Python router/uvt/client/parity/invariant/accountant suite (7 files)

```bash
python -m pytest \
  tests/test_router.py \
  tests/test_uvt_routes.py \
  tests/test_router_client.py \
  tests/test_pricing_guard.py \
  tests/test_uvt_parity.py \
  tests/test_model_router_invariant.py \
  tests/test_token_accountant.py \
  -q
# Expect: 308+ passed
```

### OTel PII lint

```bash
bash tests/lint/no_pii_in_otel.sh
# Expect: PASS: no PII in OTel attribute payloads.
```

### AST import-isolation (MR-C1 guard)

```bash
python -m pytest tests/security/test_anthropic_import_isolation.py -v
# Expect: 3 passed — only lib/token_accountant.py imports anthropic
```

### Per-finding PoC runners

```bash
# PolicyGate PoCs (run from site/)
cd site && npm test -- tests/security/policygate/

# ModelRouter PoCs (run from repo root)
python -m pytest tests/security/modelrouter/ -v

# MR-C1 specific bypass check (was FAIL pre-fix, now PASS)
python tests/security/modelrouter/poc_2_2_tokenaccountant_bypass.py

# MR-H3 DLQ / replay script (dry run)
python deploy/replay_dlq.py --dry-run
```

---

## Section 6 — Conventions

### Finding ID scheme

- `PG-` — PolicyGate findings (Red Team Sweep #1, `redteam_policygate_report.md`)
- `MR-` — ModelRouter findings (Red Team Sweep #2, `redteam_modelrouter_report.md`)
- Suffix pattern: `C` = Critical, `H` = High, `M` = Medium, `L` = Low/Info, numbered sequentially within each sweep.

### Severity scale

| Label | CVSS 3.1 Base | Decision criterion |
|---|---|---|
| Critical | ≥ 7.0 with direct billing / auth impact | Must fix before enforcement flip |
| High | 6.0–8.9 operational risk | Fix within 30 days |
| Medium | 4.0–5.9 hardening gap | Backlog with target group |
| Low / Info | < 4.0 or no direct attack path | Deferred to PR 2 or note-only |

### Adding a new report

1. Drop the `.md` file in `tests/security/`.
2. Use the naming pattern `redteam_<layer>_report.md` for sweeps or `group_<x>_patch_report.md` for remediation.
3. Add a row to **Section 1** (inventory) and rows to **Section 2** (findings matrix) using the next available `PG-` or `MR-` IDs (or introduce a new prefix for a new layer).
4. Update **Section 3** rollup totals and **Section 4** deferred list accordingly.
