# Group C Patch Report — 2026-04-23

**Scope:** Sweep #2 M1 + M4 + L1 (Python hardening).
**Branch:** `claude/group-c-python-hardening` (new, off `origin/main` at `5f4475e`).
**Live DB impact:** none — pure code + test changes.

---

## Commits landed

| # | SHA | Finding | Severity | Scope |
|---|---|---|---|---|
| 1 | `c068161` | **MR-M1** | Medium | Remove surviving `downgrade_reason` refs in harness + desktop UI + `_normalize` dead code |
| 2 | `4ea39b4` | **MR-M4** | Medium | Remove `_warned_once` log short-circuit + lock `policy_bypass_by_gate` writes under threaded workers |
| 3 | `a7ab967` | **MR-L1** | Low | Sanitize `chosen_model` before `log.info` interpolation in shadow dispatch |

---

## Per-finding patch summary

### MR-M1 — `downgrade_reason` ghost ref cleanup

**Files changed:**

- `aether/harness/simulate.py` — dropped `downgrade_reason` from `CallRecord` constructor calls at `_record_for_allow` and `_record_for_denial`.
- `aether/harness/report.py` — dropped the dataclass field, CSV column, rendering block, and orphaned `_normalize` helper (its sole caller was the rendering block).
- `desktop/pages/uvt-meter/uvt-meter.js` — dropped `body.downgrade_reason || null` from `ingestRouterResponse`'s `lastCall` shape. Added a guard comment warning future editors against resurrecting the field.

**Verification:** `tests/security/modelrouter/poc_2_10_ghost_downgrade_reason.py` PoC flipped from RED (10 ghost refs found) to PASS.

**Why it matters:** the UI was silently reading a field the backend no longer emits. Any future PR that reintroduces `downgrade_reason` on the response would be consumed by the UI, re-enabling the "buried fallback" UX the arch doc explicitly forbids.

### MR-M4 — `_warned_once` + unlocked `policy_bypass_by_gate`

**Files changed:**

- `lib/router.py`:
  - Removed `_warned_once: bool = False` module variable.
  - Removed the `if not _warned_once: log.warning(...); _warned_once = True` gate around the `ROUTER_POLICY_BYPASS` WARN log. Every bypass now logs unconditionally.
  - Added `import threading` + module-level `_policy_bypass_lock = threading.Lock()`.
  - Wrapped `policy_bypass_detected += 1` and both `policy_bypass_by_gate[...] += 1` sites in `with _policy_bypass_lock:` blocks.
  - Comment at lock declaration explains the CPython-GIL atomicity caveat for future readers.

**Verification:** `tests/security/modelrouter/poc_2_10_warned_once_silences_bypass_logs.py` was converted from a vulnerability-confirm PoC to a **post-fix regression guard** with 3 checks:
  1. No surviving `_warned_once` patterns in `lib/router.py`.
  2. Every `policy_bypass_by_gate[...] += 1` site has `with _policy_bypass_lock:` within the 3 lines above it.
  3. The lock declaration + `import threading` still present.
All 3 pass. Existing 33 router/invariant tests unchanged.

**Why it matters:**

1. **Log suppression.** `journalctl | grep ROUTER_POLICY_BYPASS` workflows previously saw only the first bypass per worker process. Long-lived uvicorn workers that had one legit bypass on day 0 went silent to every adversarial bypass on day 1+. The OTel counter kept ticking so alert-on-counter workflows worked; alert-on-log-line workflows did not.
2. **Race-lossy counter.** CPython GIL makes `d[k] += 1` atomic only at single-threaded bytecode level. uvicorn `--workers N --threads M>1` and Gunicorn `gthread` both schedule multiple OS threads onto one interpreter; their `BINARY_ADD` reads interleave, dropping increments. Each lost increment is an un-alerted bypass.

### MR-L1 — `chosen_model` log injection

**Files changed:**

- `lib/uvt_routes.py`:
  - New module-level helper `_sanitize_log_value(s)` that strips ASCII control chars (0x00–0x1F + DEL 0x7F) via `str.translate`. Non-ASCII printable unicode passes through unchanged.
  - Shadow-dispatch log site wraps the value: `log.info("router_would_pick: %s", _sanitize_log_value(shadow.chosen_model))`.
  - Inline comment documents the M2 precondition (attacker-controlled `AETHER_ROUTER_URL`) and what the sanitization prevents.

**Verification:** new `tests/security/modelrouter/poc_2_L1_log_injection.py` with 8 regression guards: strips newline/CR/ANSI/every 0x00-0x1F/DEL, preserves printable ASCII, preserves non-control unicode, handles empty + pure-control inputs, and grep-asserts the shadow-log call site still wraps in `_sanitize_log_value` (catches any future refactor that drops the call).

**Why it matters:** Python's `logging` does NOT escape control chars in `%s` substitution. A hostile `AETHER_ROUTER_URL` (the M2 precondition — future risk at PR 2 cutover) can return a `chosen_model` containing `\n` + a forged log line, which then lands in the aggregator as if it were a legitimate router event.

---

## Aggregate verification

| Check | Result |
|---|---|
| `pytest tests/test_router.py tests/test_uvt_routes.py tests/test_router_client.py tests/test_pricing_guard.py tests/test_uvt_parity.py tests/test_model_router_invariant.py tests/test_token_accountant.py tests/security/modelrouter/` | **308 passed** |
| `pytest tests/security/test_anthropic_import_isolation.py` | 3 passed |
| `bash tests/lint/no_pii_in_otel.sh` | PASS |
| TS suite (not touched in Group C) | CI will run `npm test` on PR push |

---

## Status update — Sweep #2 residuals

### Closed in Group C

- **MR-M1** ✅ (`c068161`)
- **MR-M4** ✅ (`4ea39b4`)
- **MR-L1** ✅ (`a7ab967`)

### Still open after Group C

- **MR-H1** classifier prompt-injection via `context_compressor` tail-trim — **bigger fix**, not in the M1/M4/L1 scope. Either strip JSON-looking substrings from `hydrated_context` before the classifier call or stop feeding context into the classifier entirely. Deferred.
- **MR-M2** `AETHER_ROUTER_URL` hostname allowlist — PR 2 prerequisite. Severity escalates to Critical at shadow→enforce cutover. Deferred.
- **MR-M3** Concurrent-preflight TOCTOU — move balance check inside `rpc_record_usage` transaction. PR 2 scope.
- **MR-M5** Reclassify burns extra Haiku call on crafted ambiguous prompts. Acceptable for PR 1; defer to PR 2 with `temperature=0` + cache.
- **MR-M6** `Router._plans_cache` never evicts without explicit call — PR 2 scope: 60s TTL or Postgres NOTIFY subscription.

### Overall Sweep #2 status after this PR

| Severity | Fixed | Open |
|---|---|---|
| Critical | 1 of 1 | 0 |
| High | 2 of 3 | 1 (MR-H1) |
| Medium | **2 of 6** | 4 |
| Low | **1 of 1** | 0 |

---

## `tests/security/README.md` updated

Status table now reflects Group C's 3 closures. Total fixed count: **14 → 17**.

## Nothing blocked

PR ready to open against `main`. Awaiting user signal to merge.
