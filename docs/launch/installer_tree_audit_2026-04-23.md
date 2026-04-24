# Installer Tree Audit — `desktop/` vs `desktop-installer/` Resolution Plan

**Date:** 2026-04-23
**Session:** E (tree resolution, docs-only)
**Branch:** `claude/installer-tree-resolution` (from `origin/main` @ `891765e`)
**Scope:** Audit-only. NO code changes. NO deletions.

---

## TL;DR — VERDICT C (both trees live, different roles)

**`desktop/` and `desktop-installer/` are NOT redundant.** They are two halves of
a deliberate two-binary split-install architecture documented in
`docs/superpowers/specs/2026-04-18-branded-installer-wizard-design.md` and its
matching implementation plan. Neither tree is dead. Both must ship together.

**Confidence:** HIGH.

- `desktop-installer/` (Tauri, Rust + HTML) = **`AetherCloud-Setup.exe`** — the ~8 MB
  signed wizard a user downloads from `api.aethersystems.net/downloads/AetherCloud-Setup.exe`.
  It renders the 4-page consent UI, fetches a signed manifest, verifies Ed25519,
  downloads the payload, verifies SHA-256, runs it silently.
- `desktop/` (Electron + electron-builder) = **`AetherCloud-L-Payload-<ver>.exe`** — the
  ~90 MB NSIS payload that the Tauri wizard fetches and runs. This IS the app itself.
  Also contains a post-install first-run branded page (`desktop/pages/installer/installer.html`)
  rendered by the Electron main process on first launch.

Nothing gets deleted. Cleanup is narrow: correct one mis-targeted telemetry branch
and add clarifying comments / READMEs pointing to the architecture doc.

---

## 1. Inventory

### `desktop/` (Electron — the app payload)
- Top-level: `main.js` (58 KB), `preload.js` (14 KB), `analysis-cache.js`,
  `auth-store.js`, `telemetry.js`, `package.json`, `package-lock.json` (183 KB),
  `build-dist.ps1`, `.gitignore`, `assets/`, `build/`, `pages/`, `tests/`.
- Total tracked size: **2.3 MB** (excludes build artifacts / node_modules).
- `package.json`:
  - `"name": "aethercloud-l"`, `"version": "0.9.8"`, `"main": "main.js"`
  - deps: `electron ^41.2.1`, `electron-builder ^26.8.1`, `electron-store`,
    `node-machine-id`, `dompurify`, `@electron/fuses`
  - `build.win.target: nsis`, `build.win.artifactName: "AetherCloud-L-Payload-${version}.exe"`
  - Scripts: `start: electron .`, `dist: electron-builder --win`
- Pages: `dashboard.html` (833 KB — the main app UI), `login.html`, `terminal.html`,
  `report-panel.html`, `installer.html`, `installer/installer.html`,
  `uvt-meter/`, `vendor/`.
- **Last commit touching tree (any time):** `7a02194` (2026-04-22 area, router group C).
  Explicit release commit: `301a259 release(desktop): v0.9.8 — UVT Meter v3 + BYOK removal`.
  Security/installer-adjacent: `8f13e66`, `6314942`, `f19f460`, `6b76ea6`.

### `desktop-installer/` (Tauri — the download wizard)
- Top-level: `package.json` (329 B, only `@tauri-apps/cli`), `package-lock.json`,
  `README.md` (8.6 KB, detailed), `src/` (HTML/CSS/JS frontend), `src-tauri/`
  (Rust backend), `.gitignore`.
- Total tracked size: **317 KB**.
- `src/`: `index.html`, `installer.html`, `installer.js`, `installer.css`,
  `dot-background.js`, `tauri-bridge.js`, `agents/`.
- `src-tauri/`:
  - `Cargo.toml`: package `aethercloud-installer` v1.0.0, bin + lib targets.
    Deps: `tauri 2`, `reqwest rustls`, `ed25519-dalek 2`, `sha2`, `tokio`, `uuid`,
    `thiserror`, `tracing`.
  - `tauri.conf.json`: `productName: "AetherCloud Setup"`,
    `identifier: "com.aethersystems.aethercloud.setup"`,
    `frontendDist: "../src"`, `bundle.active: false`,
    icon reference `../../desktop/assets/icon.ico` (cross-tree linkage).
  - `src/main.rs` — tauri bootstrap + tracing + `%LOCALAPPDATA%/AetherCloud-Setup/install.log`.
  - `src/installer.rs` — MANIFEST_URL `https://api.aethersystems.net/downloads/manifest-latest.json`,
    Ed25519 pinned pub key loaded via `include_bytes!`.
  - `src/payload.rs`, `src/manifest.rs`, `src/commands.rs`, `src/errors.rs`.
  - `keys/manifest-signing.pub.bin` (production key, pinned at compile time).
  - `tests/` (integration tests).
- **Recent commits:** `0d6ad01`, `5945a60`, `de400df`, `c9c297c`, `20431cb`,
  `400c4dd` ("release: point wizard at api.aethersystems.net/downloads/ (live host)"),
  `7d97770` ("release: swap to production Ed25519 pubkey"),
  `474a6f3` ("docs(installer-wizard): operator runbook").

---

## 2. Side-by-side comparison

| Dimension | `desktop/` | `desktop-installer/` |
|---|---|---|
| Technology | Electron + electron-builder | Tauri v2 + Rust |
| Role | The app itself (payload) | The download wizard |
| Output binary | `AetherCloud-L-Payload-<ver>.exe` (~90 MB NSIS) | `AetherCloud-Setup.exe` (~8 MB) |
| Public download URL | No — payload is wizard-only consumer | Yes — `api.aethersystems.net/downloads/AetherCloud-Setup.exe` |
| Entry point | `main.js` (Electron main) | `src-tauri/src/main.rs` (Rust) |
| Frontend | `desktop/pages/*.html` (dashboard, login, etc.) | `desktop-installer/src/index.html` (single-view wizard) |
| Signing | Authenticode + Electron fuses + NSIS sign | Authenticode only (same cert) |
| Update model | Payload version bumped per release; wizard fetches signed manifest | Wizard itself rarely changes; manifest signature is the trust root |
| Telemetry | In-app PostHog via `desktop/telemetry.js` + preload bridge | **NONE** in Rust layer; frontend has no tracking calls |
| Last substantive activity | 2026-04-22 (v0.9.8 release) | 2026-04-22 (wizard UI v4 + live-host wiring) |
| Git activity since 2026-03-01 | 10+ commits | 15+ commits |

---

## 3. Signal-by-signal evidence

### Signal 1 — CI (`.github/workflows/ci.yml`)
Neither tree has a CI build job. CI runs:
- `site/` TypeScript tests + typecheck
- `tests/test_router.py` suite (Python)
- OTel PII lint
- Anthropic import isolation

**No GitHub Actions job builds `desktop/` OR `desktop-installer/`.** Release builds
are manual from a dev machine (see `desktop-installer/README.md` §Release build, and
`desktop/package.json` `dist:signed` script). This is neutral — does not discriminate.

### Signal 2 — Download URLs (site / docs grep)
- `web/src/lib/config.js:32` — default `VITE_DOWNLOAD_URL` points to
  `https://api.aethersystems.net/downloads/AetherCloud-Setup.exe`.
- `web/CLOUDFLARE-DEPLOY.md:70,93` — same.
- `docs/superpowers/specs/2026-04-20-aethersystems-net-checkout-wiring-design.md:34` —
  same URL, labeled "already live on vps1".
- `desktop-installer/README.md` — entire file is the operator runbook for staging
  the wizard + signing the manifest + uploading both the wizard and the payload.
- `desktop-installer/src-tauri/src/installer.rs:10` — manifest URL hard-coded to the
  same live host.

The **user-facing download is `AetherCloud-Setup.exe` (the Tauri wizard)**, not the
NSIS payload. The payload URL only appears inside a signed manifest that the wizard
fetches after consent.

### Signal 3 — Vercel/site links
`web/src/pages/welcome/index.jsx:12` — "Shows the AetherCloud-Setup.exe download button".
Confirms the site points at the wizard.

### Signal 4 — Recent commit dates
Both trees were touched within the last week:
- `desktop/` last: `301a259 release(desktop): v0.9.8` and follow-on security/router fixes.
- `desktop-installer/` last: `0d6ad01 fix(installer-wizard): Tauri v2 capabilities + installed_app_path`.

Both are active. Neither is abandoned.

### Signal 5 — PR #55 test target
`gh pr view 55 --json files` shows PR #55 creates:
- `.github/workflows/installer-e2e.yml`
- `desktop-installer/tests/e2e/happy_path.spec.ts`
- `desktop-installer/tests/e2e/uninstall.spec.ts`
- `desktop-installer/tests/e2e/package.json`
- `desktop-installer/tests/e2e/playwright.config.ts`

**PR #55 targets `desktop-installer/` (Tauri).** It is valid against the live wizard tree.

### Signal 6 — Telemetry branch (`claude/installer-telemetry-and-router-e2e` = PR #50 work)
Diff vs `origin/main`:
- `desktop/main.js` (+8 lines)
- `desktop/pages/installer/installer.js` (+32 lines — 13 PostHog track calls
  for `installer_opened`, `installer_license_shown`, `installer_install_started`,
  `installer_completed`, `installer_download_started`, `installer_download_completed`,
  `installer_verify_passed`, `installer_welcome_clicked`, `installer_launch_clicked`, etc.)
- `desktop/preload.js` (+1 line — `installerAPI.track` bridge)
- `site/tests/integration/router_pick_e2e.live.test.ts` (new file — unrelated to installer)

**The telemetry was added to the Electron app's first-run in-app onboarding page
(`desktop/pages/installer/installer.html`), NOT to the Tauri download wizard
(`desktop-installer/src/installer.js`).** Those are two different "installers":
- The first runs INSIDE the Electron app on first launch (a branded welcome screen
  loaded by `desktop/main.js:210` → `createWindow('installer')` at
  `main.js:404` when `isFirstRun()` is true).
- The second is the actual download + install orchestrator a user sees BEFORE the
  app is on their machine.

**Reachability verdict for the `#50` telemetry:**
- The events ARE reachable at runtime — they fire during the post-install
  first-run welcome flow inside the Electron app, after the user has already
  run the Tauri wizard. The preload `installerAPI.track` bridge exists
  (post-patch) and forwards to Electron main.
- But they do NOT track the download-wizard funnel (pre-install consent,
  download progress, Ed25519 verify, payload launch). If the PM intent of the
  `#50` work was "measure the funnel from site-visit → install complete", the
  wizard-side half of that funnel is unrecorded.
- `desktop-installer/src/installer.js` has ZERO `track()` / `posthog` / analytics
  calls (grep confirmed).

---

## 4. Architecture (per `docs/superpowers/specs/2026-04-18-branded-installer-wizard-design.md`)

```
[Download page]
     │
     ▼
AetherCloud-Setup.exe   ◄── desktop-installer/ (Tauri wizard, ~8 MB signed)
 │  1. Render 4-page UI
 │  2. Consent gate (checkbox)
 │  3. Fetch signed manifest + Ed25519 verify
 │  4. Stream-download AetherCloud-L-Payload-<ver>.exe + SHA-256 verify
 │  5. Spawn payload silently (/S)
 │  6. Launch installed app
 ▼
AetherCloud-L-Payload-<ver>.exe   ◄── desktop/ (Electron app as NSIS installer, ~90 MB)
 │  1. Writes to %LOCALAPPDATA%\aethercloud-l
 │  2. Creates Start Menu + desktop shortcut
 │  3. On first launch, loads desktop/pages/installer/installer.html
 │     (in-app branded welcome) → login → dashboard
```

Both trees ARE the product. Removing either breaks the shipping path.

---

## 5. Cleanup plan (per file / area)

### `desktop/`
| Path | Action | Why |
|---|---|---|
| `desktop/main.js` | **Keep** | Electron main process — live |
| `desktop/preload.js` | **Keep** | IPC contract — live |
| `desktop/pages/**` | **Keep** | App UI — live |
| `desktop/pages/installer/**` | **Keep, rename in comments** | Post-install first-run welcome (NOT the download wizard). Rename internal references to "first-run welcome" or "onboarding wizard" to avoid confusion with `desktop-installer/`. Docs-only change, no file renames (churn risk). |
| `desktop/build/`, `desktop/assets/` | **Keep** | Build helpers + branding |
| `desktop/package.json` | **Keep** | Payload build config |
| `desktop/tests/` | **Keep** | Electron unit tests |

### `desktop-installer/`
| Path | Action | Why |
|---|---|---|
| `desktop-installer/src/` | **Keep** | Wizard frontend — live |
| `desktop-installer/src-tauri/` | **Keep** | Wizard backend — live |
| `desktop-installer/src-tauri/keys/manifest-signing.pub.bin` | **Keep** | Production pub key, compile-embedded |
| `desktop-installer/README.md` | **Keep** | Operator runbook (key rotation, manifest signing, nginx config) |
| `desktop-installer/tests/` | **Keep** | Rust integration tests |

### Docs / clarification
| Path | Action |
|---|---|
| Repo-root `README.md` | **Add** short section explaining the two-binary split so new contributors don't mistake `desktop/pages/installer/installer.html` for the download wizard. |
| `desktop/pages/installer/installer.html` header comment | **Add** comment: "This is the post-install in-app welcome page. For the pre-install download wizard see `desktop-installer/src/installer.html`." |
| `desktop-installer/src/installer.html` header comment | **Add** mirror comment pointing to `desktop/pages/installer/installer.html`. |

### Risk
- **Low**: no file deletions, no module moves. All changes are docs / comments.
- **Rollback**: trivial — revert the comment/docs commit.

---

## 6. Impact on pending work

### PR #55 (Session A — `claude/installer-e2e-verification`)
**VALID.** Targets `desktop-installer/tests/e2e/` — the live Tauri tree. No action needed.

### Session B branch (`claude/installer-cleanup-hygiene`)
**VALID.** Touches `desktop-installer/src-tauri/src/{cleanup,download,install_manifest,lib}.rs`
— the live Tauri tree. No action needed.

### Session D (tauri.conf hardening, running in parallel)
**VALID.** Works on `desktop-installer/src-tauri/tauri.conf.json` — live tree.

### PR #50 telemetry (`claude/installer-telemetry-and-router-e2e`)
**PARTIAL.** The events reach PostHog at runtime (reachable, not dead code), but
they instrument the wrong funnel stage:
- Instrumented: post-install first-run welcome inside the Electron app.
- Not instrumented: the download + verify + install funnel inside the Tauri wizard.

**Recommended re-port (~45 min):** add an equivalent `track()` channel from the
Tauri wizard's HTML frontend (`desktop-installer/src/installer.js`) through a
Tauri command in `desktop-installer/src-tauri/src/commands.rs` that POSTs to the
PostHog capture endpoint. Events to mirror (with site-spec consent):
`wizard_opened`, `wizard_consent_given`, `wizard_manifest_verified`,
`wizard_download_started`, `wizard_download_completed`, `wizard_payload_verified`,
`wizard_payload_launched`, `wizard_cancelled`, `wizard_error{stage}`.

**This is NOT urgent for shipping** — the existing `#50` events are still useful
signal for the first-run flow. Flag it as follow-up.

---

## 7. Next-step instructions for Session F (read-only on `installer.rs` / `main.rs`)

**Proceed with Tauri.** `desktop-installer/src-tauri/src/installer.rs` and
`desktop-installer/src-tauri/src/main.rs` are the LIVE download wizard
implementation. Session F's work is well-targeted.

Recommended focus areas (if Session F is doing hardening / review):
- Confirm `installer.rs:10-11` `MANIFEST_URL` and `MANIFEST_SIG_URL` both point
  at `api.aethersystems.net` (they do, verified).
- Confirm `PINNED_PUBKEY` at `installer.rs:29` matches the production pub bin
  (do NOT regenerate — key rotation invalidates all released wizards).
- Confirm `main.rs:15` log dir `%LOCALAPPDATA%/AetherCloud-Setup/` aligns with
  Session B's cleanup lifecycle (`desktop-installer/src-tauri/src/cleanup.rs`).
- `main.rs:71-79` tauri Builder wires `start_install`, `cancel_install`,
  `launch_app`, `detect_existing` — no telemetry command yet. Flag as a
  follow-up slot if PR #50 re-port lands here.

---

## 8. Hard constraints honored

- [x] No files deleted from either tree.
- [x] No code modified — audit + docs only.
- [x] Evidence tabulated with concrete file:line citations.
- [x] Verdict is C (both live) with HIGH confidence — not a hedge, the two
      trees are architecturally distinct.
- [x] PR will not be self-merged.
