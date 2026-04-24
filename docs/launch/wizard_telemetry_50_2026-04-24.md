# Wizard install-funnel telemetry — PR #50 re-port

**Date:** 2026-04-24
**Issue:** #50 (PostHog install-funnel)
**Tree-audit origin:** PR #56 (Session E's Verdict C)
**Branch:** `claude/installer-telemetry-report-50-v2`
**Why `-v2`:** the canonical branch name is locked by an orphaned local worktree (`agent-a2faebf9`). The `-v2` suffix side-steps the collision.

---

## Why this exists

PR #56 resolved the `desktop/` vs `desktop-installer/` ambiguity and declared the Tauri wizard in `desktop-installer/` the live funnel surface. It surfaced a gap:

- `desktop-installer/` (Tauri, Rust, ~8 MB signed `AetherCloud-Setup.exe`) is the wizard that runs FIRST. Download -> verify -> install -> launch. This was DARK to analytics.
- `desktop/` (Electron, ~90 MB `AetherCloud-L-Payload-<ver>.exe`) is the payload the wizard extracts and hands off to. Issue #50's 13 events were wired here, at `desktop/pages/installer/installer.js` — which only ever renders on the POST-install welcome page.

Result: users who dropped off mid-wizard never showed up in PostHog. We saw 100% conversion from "launched welcome page" to "welcome page rendered," because users who never got that far weren't counted at all.

This module closes the gap by firing all 13 funnel events at their TRUE call sites — Rust-side for the trust-boundary events (signature verify, SHA-256 verify, NSIS spawn outcomes) so a compromised WebView cannot suppress them.

## Architecture

- **Direct HTTPS to PostHog.** No Rust SDK. A single POST to `https://us.i.posthog.com/capture/` with JSON body. Mirrors the existing pattern in `aethercloud/supabase/functions/_shared/license.ts::captureServerEvent` (Deno runtime, where `posthog-node` doesn't work).
- **Fire-and-forget.** `capture_fire_and_forget(...)` spawns a detached `tokio::spawn`, or (when called from `main()` before the Tauri runtime exists) a detached OS thread with a throwaway current-thread runtime. Never blocks the caller.
- **Never throws.** `capture(...)` returns `Result<(), TelemetryError>` so tests can assert success, but every install-path call site uses `capture_fire_and_forget` which swallows the error. A PostHog outage CANNOT break an install.
- **Anonymous distinct_id.** Generated UUIDv4 on first capture, cached at `%LOCALAPPDATA%\AetherCloud-Setup\telemetry-distinct-id.txt`. Same directory `cleanup::startup_cleanup` manages; `cleanup::uninstall_teardown` wipes it as part of `purge()`.
- **Gating.** `AETHER_TELEMETRY_ENABLED=1` forces on, `=0` forces off. Default: ON in release, OFF in `debug_assertions` so `cargo run` doesn't pollute the funnel. Legacy `AETHER_TELEMETRY_OFF=1` still disables (honored from the old Electron client).

## The 13 events

| # | Event wire name | Rust call site (file) | Trigger | Properties | Sanitization justification |
|---|---|---|---|---|---|
| 1 | `wizard_launched` | `main.rs` pre-Builder block (replaces Session F's reserved slot) | Wizard process started, before Tauri runtime spins up | `wizard_version`, `os` | No user input at this stage — fixed constants only |
| 2 | `installer_started` | `commands.rs::start_install`, post-consent re-verify | User clicked Install and backend re-verified consent | `wizard_version`, `os` | Fires AFTER the compromised-WebView guard so a crafted IPC can't fake a pre-consent emit |
| 3 | `download_started` | `installer.rs::run_install`, after `emit(downloading_payload)` | HTTPS GET for the payload is about to begin | `percent=8`, `wizard_version`, `os` | Constants only; URL is known-good manifest-supplied |
| 4 | `download_progress` | `installer.rs::run_install`, inside the download-progress closure | Crosses 25/50/75% bucket boundaries (NOT per-byte) | `percent`, `bytes_written`, `attempt`, `wizard_version`, `os` | `bytes_written` is a counter; `attempt` is bounded `1..=MAX_RETRIES`; never pass URL/path |
| 5 | `download_completed` | `installer.rs::run_install`, after `download_verified` returns Ok | SHA-256 match; payload safely on disk | `percent=85`, `bytes_written`, `sha256_prefix` (first 16 hex only), `wizard_version`, `os` | Full hash NEVER leaves the process — only the 16-char prefix (64 bits of entropy, enough to bucket) |
| 6 | `verify_started` | `installer.rs::run_install`, before `manifest::verify_signature` | Ed25519 signature verification begins | `percent=6`, `wizard_version`, `os` | Rust-side by design — WebView cannot skip |
| 7 | `verify_completed` | `installer.rs::run_install`, after signature OK | Signature matched `PINNED_PUBKEY` | `percent=6`, `wizard_version`, `os` | Same as above |
| 8 | `verify_failed` | `installer.rs::run_install`, inside the Err branch of `verify_signature` | Signature mismatch — install is aborted | `error_code` (static `InstallerError::state_label()` string), `wizard_version`, `os` | `state_label()` is `&'static str` from a fixed enum — never the `Display` string which may contain URLs |
| 9 | `install_started` | `installer.rs::run_install`, before `payload::run_payload_silent` | NSIS /S spawn point | `percent=92`, `wizard_version`, `os` | Constants only |
| 10 | `install_progress` | `installer.rs::run_install`, after `scan_installed_files` | Post-NSIS manifest scan, before health verdict | `percent=96`, `file_count`, `wizard_version`, `os` | `file_count` is a bounded `usize` count, no paths |
| 11 | `install_completed` | `commands.rs::start_install`, Ok arm | NSIS exited 0 AND health check Healthy | `percent=100`, `error_code=<redact_path>`, `wizard_version`, `os` | `redact_path()` reduces the installed path to one of four static tokens; user-home path never leaves |
| 12 | `install_failed` | Multiple: `commands.rs::start_install` Err arm; `installer.rs::run_install` download-err, NSIS-spawn-err, and health-failed arms | NSIS exited non-zero, download failed, signature mismatch cascade, or health check Degraded/Failed | `error_code` (static state label), `closed_reason` (`"cancelled"` / `"error"` / `"download_failed"` / `"nsis_spawn_failed"` / `"health_check_failed"`), optionally `missing_count`, `file_count` | All values are static strings or bounded counts |
| 13 | `wizard_closed` | `main.rs`, after `tauri::Builder::...run(...)` returns | Tauri event loop exited normally | `closed_reason="normal_exit"`, `wizard_version`, `os` | Constant only |

## Why Rust-side vs frontend

| Event | Side | Rationale |
|---|---|---|
| `wizard_launched` | Rust (main.rs) | Emits BEFORE the webview exists — frontend couldn't fire it even if we wanted. Top-of-funnel must be captured pre-compromise. |
| `installer_started` | Rust (commands.rs) | Fires AFTER the `if !consent { return Err }` guard — a WebView that bypassed the consent checkbox via crafted IPC would never reach this emit. |
| `download_started` / `_progress` / `_completed` | Rust (installer.rs) | The WebView doesn't observe the HTTPS download at all — it's driven by Rust. Frontend can't fire these. |
| `verify_started` / `_completed` / `_failed` | Rust (installer.rs) | Trust-boundary events. A compromised WebView MUST NOT be able to fake a `verify_completed` to paper over a signature mismatch. |
| `install_started` / `_progress` | Rust (installer.rs) | NSIS spawn and file-scan happen in Rust; WebView can't observe them directly. |
| `install_completed` / `_failed` | Rust (commands.rs + installer.rs) | Terminal events. Must survive a crashed WebView — emitted from the backend so they land even if the browser process died mid-render. |
| `wizard_closed` | Rust (main.rs) | Fires after the Tauri event loop exits; webview is already gone. |

**None of the 13 events are frontend-only.** This is deliberate: every event is security-relevant or must survive a WebView crash. Frontend UX events (button hovers, copy-read events, etc.) are explicitly NOT in this module.

## Funnel diagram

```
wizard_launched  [main.rs]
     |
     v
installer_started  [commands.rs - post-consent re-verify]
     |
     v
verify_started  [installer.rs - Ed25519 signature]
     |
     +-- verify_failed  (signature mismatch -> install_failed closed_reason=error)
     |
     v
verify_completed
     |
     v
download_started  [installer.rs - payload HTTPS GET]
     |
     +-- download_progress  (fires at 25/50/75 boundaries)
     |
     +-- (download error) -> install_failed closed_reason=download_failed
     |
     v
download_completed  [installer.rs - SHA-256 match, atomic rename]
     |
     v
install_started  [installer.rs - NSIS /S spawn]
     |
     +-- (NSIS spawn error) -> install_failed closed_reason=nsis_spawn_failed
     +-- (NSIS non-zero exit) -> install_failed closed_reason=error
     |
     v
install_progress  [installer.rs - post-NSIS file scan]
     |
     +-- (health check Degraded/Failed) -> install_failed closed_reason=health_check_failed
     |
     v
install_completed  [commands.rs Ok arm]
     |
     v
wizard_closed  [main.rs - Tauri event loop exit]
```

## Relationship to the old `desktop/` events

The 13 events that currently fire in `desktop/pages/installer/installer.js` are POST-install — they render on the welcome page of the installed application, after the wizard has already completed. We explicitly kept them in place (they're useful as "user reached the installed app" signals) and added a single comment at the top of that file:

```js
// POST-INSTALL events only. Wizard funnel is instrumented in desktop-installer/src-tauri/. See issue #50.
```

The two funnels are complementary:
- **Wizard funnel (Rust, this PR):** dropoff between `wizard_launched` and `install_completed`. Measures installer quality.
- **Post-install funnel (JS, existing):** dropoff AFTER `install_completed`. Measures welcome-page engagement.

The dashboard should JOIN them on `distinct_id` to get a full "download -> launched app" funnel.

## Capability change

Added one entry to `desktop-installer/src-tauri/capabilities/default.json` under `http:default`:

```json
{ "url": "https://us.i.posthog.com/*" }
```

Without this, Session H's plugin ACL blocks the outbound POST. No other scope changes.

## Verification

- `cargo check --lib --bin aethercloud-installer --tests` — clean, zero warnings
- `cargo test --test telemetry_test` — 6/6 passed
- `cargo test --lib` — 53/54 passed (one pre-existing unrelated failure in `manifest::tests::verifies_good_signature`, present on `ba5be2c` before any of this work; likely a fixture-data drift)
- `python -m json.tool capabilities/default.json` — valid
- `PINNED_PUBKEY` — byte-for-byte unchanged (sha256 of `keys/manifest-signing.pub.bin`: `0d8e2c1fa0aa506a9730940e7975933381733acd521fe673358613811bee0194`)
- Session F wiring (`startup_cleanup`, `--purge`, `shutdown_cleanup`) — preserved, zero lines removed from that flow

## Sensitive data contract (what MUST NOT appear in any POST body)

- Raw Windows user-home paths (`C:\Users\<name>\...`)
- Full SHA-256 hashes (only first 16 hex allowed)
- Stripe-id-like strings (`cs_test_...`, `pi_live_...`)
- `Display`-format error messages (may include URLs, user input)
- License keys, email addresses, any PII

Enforced by:
- `EventProperties` only exposes typed builders for the whitelisted fields
- `with_sha256_prefix` truncates to 16 hex chars
- `with_error_code` accepts `&'static str` only — forces the caller to use a constant or enum label, never a runtime string
- `redact_path()` maps any `Path` to one of four static tokens (`programs_aethercloud_l`, `aethercloud_l_flat`, `aethercloud_generic`, `unknown_install_path`)
- Integration test `properties_payload_shape_and_sanitization` asserts the absence of user-home paths, Stripe-id prefixes, and the full hash in every POST body

## Future work (not in this PR)

- Add a PostHog project key to release builds — currently compiled-in default is `""`, which no-ops capture silently (safe default for the open-source wizard binary; real key should be injected at release-build time via `AETHER_POSTHOG_KEY` env var or a build-script).
- Dashboard queries using the 13 wire names above.
- Optional: track Tauri webview errors to a 14th event if Session D's webview-crash reporting lands.
