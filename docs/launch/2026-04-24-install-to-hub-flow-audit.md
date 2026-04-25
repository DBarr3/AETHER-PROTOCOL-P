# Install-to-Hub Flow Audit — Session M

**Date:** 2026-04-24  
**Branch:** `claude/install-to-hub-flow-verification`  
**Scope:** Non-destructive code audit of the complete download → Tauri wizard → Electron launch → license key → login → central hub flow  
**Status:** Phase 1 complete — code audit done, builds not attempted (see §7)

---

## 1. Flow Map

```
[Step 1] User downloads installer EXE from website
             │
             ▼
[Step 2] Tauri wizard renders (desktop-installer/src/index.html)
          decorations:false window, consent checkbox, Install button
             │
             ▼
[Step 3] download.rs fetches payload over HTTPS
          SHA-256 verified → .part file → atomic rename → installer.rs unpacks
          installer://progress events → tauri-bridge.js → installer.js
             │
             ▼
[Step 4] commands.rs:launch_app() spawns Electron binary
          wizard window closes
             │
             ▼
[Step 5a] Electron opens desktop/pages/installer.html (first-time flow)
          4-page simulated wizard: Welcome → Location → Install → Complete
             │
             ▼
[Step 5b] desktop/pages/installer/installer.html (branded variant)
          welcome → setup → download → final (uses window.installerAPI bridge)
             │
             ▼
[Step 6] desktop/pages/login.html
          health check → first-time (license key shown) or returning user
          POST /auth/login → session_token → aetherAPI.authSet
          session restore if rememberMe + valid token
             │
             ▼
[Step 7] desktop/pages/dashboard.html
          Central hub (audited separately in Session L)
```

---

## 2. Per-Step Entry Points and State Transitions

### Step 2 — Tauri Wizard

| File | Role |
|------|------|
| `desktop-installer/src-tauri/tauri.conf.json` | Window config: 1000×680, `decorations: false`, no `transparent`, no `backgroundColor` |
| `desktop-installer/src-tauri/src/main.rs` | Plugins: fs, dialog, shell, http, notification, process, updater. Fires `WizardLaunched` telemetry before event loop. |
| `desktop-installer/src-tauri/capabilities/default.json` | ACL: HTTP scoped to aethersystems.net + posthog only. FS scoped to APPDATA subdirs + TEMP/AetherCloud-*. shell:allow-open scoped to aethersystems.net only. |
| `desktop-installer/src/index.html` | Wizard UI: consent checkbox, progress bar, Install/Cancel buttons |
| `desktop-installer/src/installer.css` | Body background: `linear-gradient(180deg, #05070d, #0a0f1c)` — fully opaque |
| `desktop-installer/src/installer.js` | 10s backend watchdog. Handles progress events, error/cancel/done states. IPC resolve path handles missing progress events. |
| `desktop-installer/src/tauri-bridge.js` | Wraps `window.__TAURI__.core.invoke` + `window.__TAURI__.event.listen` into `window.installerAPI` |

**State machine (installer.js):**
```
idle → installing → {done, error, cancelled}
  done: renderProgress(100) → launchApp() after 800ms
  error: surfaceError() → re-enable consent + Retry button
  cancelled: hide progress, re-enable form
  watchdog: fires if no event within 10s → surfaceError with log path hint
```

### Step 3 — Download + Verify

| File | Key behavior |
|------|--------------|
| `download.rs` | HTTPS-only (rejects `http://` with `InsecureUrl` error). SHA-256 verified before atomic rename. 500 MB cap (both Content-Length check and streaming cap). 3 retries w/ exponential backoff (2s, 4s, 8s). 30s stall timeout per chunk. Writes to `.part` file; renames on success; deletes on failure. |
| `installer.rs` | Download → unpack → register install. Emits `installer://progress` events via Tauri Emitter. |
| `cleanup.rs` | `startup_cleanup()` drains stale `.part` files from `%TEMP%` on wizard launch. |

### Step 4 — Tauri → Electron Handoff

`commands.rs:launch_app()`:
```rust
std::process::Command::new(&path).spawn()
// then closes wizard window via app.get_webview_window("main").close()
```

Security: Electron binary was SHA-256 verified in Step 3 before this `path` was set. No re-verification here, but the atomic rename in `download.rs` ensures only a hash-matched binary lands at the expected path.

### Step 5a — Electron Installer (`desktop/pages/installer.html`)

4-page wizard: Welcome → Location → Install → Complete.  
`startInstall()` is a **pure simulation** using `sleep()` timers. No real IPC — it does not call `window.aether` for actual installation work (the Tauri wizard already completed the real install in Step 3).

Consequence: The progress log always shows "All 410 tests passed ✓" even if the Tauri install had issues that weren't fatal enough to block launch. This is cosmetic, not functional.

After page 4, navigates to `login.html` via `window.aether.navigate('login')`.

Background solid: `background: var(--bg)` where `--bg: #0a0a0a` — fully opaque.

### Step 5b — Branded Installer (`desktop/pages/installer/installer.html`)

Alternative branded variant. Connected to `window.installerAPI` (listens to `onProgress` events). Has `launchApp` and `cancelInstall` calls. CSS background: `linear-gradient(180deg, #060912, #091020)` — fully opaque.

### Step 6 — Login Screen (`desktop/pages/login.html`)

**Background:** `--bg: #0a0a0a` — fully opaque. No transparency.

**Init flow:**
1. `checkUpdateBanner()` — calls `window.aether.getUpdateInfo()`, shows amber banner if outdated
2. `tryRestoreSession()` — reads `window.aetherAPI.authGet()`, POSTs to `/auth/verify`, navigates to dashboard if valid
3. Health check — GET `/auth/health`, sets dot indicators, shows license key field if `health.needs_setup = true`

**First-time setup path:**
- License key field hidden by default (`display:none`), shown when `health.needs_setup = true`
- `handleLogin()` collects `licenseKey` from field and includes in POST body
- Session token stored via `window.aetherAPI.authSet()`; plaintext password never stored

**Auth error handling:** Maps reason codes (`USER_NOT_FOUND`, `INVALID_PASSWORD`, `ACCOUNT_LOCKED`, `LICENSE_INVALID`, `LICENSE_EXPIRED`) to user-readable messages.

**CSP:** `connect-src 'self' https://api.aethersystems.net https://license.aethersystems.net https://aethersecurity.net`

### Step 7 — Central Hub (`desktop/pages/dashboard.html`)

Audited in Session L. See `docs/bugs/2026-04-24-agent-terminal-launch-investigation.md`.

---

## 3. Transparency Risk Assessment

| Location | Risk | Status |
|----------|------|--------|
| `tauri.conf.json` — no `backgroundColor` set | Brief white flash on first paint before CSS loads (frameless window + dark CSS = visible flash on slow machines) | **LOW** — cosmetic only, not persistent |
| `installer.css` body background | Solid gradient ending at `#05070d` | **CLEARED** — `transparent` used only as gradient color stop, not as background value |
| `login.html` body | `background: var(--bg)` = `#0a0a0a` | **CLEARED** |
| `installer.html` (pages/) body | `background: var(--bg)` = `#0a0a0a` | **CLEARED** |
| `installer/installer.css` body | Solid gradient ending at `#060912` | **CLEARED** |

**Only actionable item:** Add `"backgroundColor": "#05070d"` to the window entry in `tauri.conf.json` to prevent the white flash on cold start. One-line fix.

---

## 4. Security Findings

### S1 — Download: HTTPS + SHA-256 enforced (PASS)
`download.rs` hard-errors on non-HTTPS URLs. Hash verified before any filesystem rename. .part file deleted on mismatch. Solid.

### S2 — ACL scope (PASS)
`capabilities/default.json` scopes every plugin surface tightly:
- HTTP: only `api.aethersystems.net`, `license.aethersystems.net`, `app.aethersystems.net`, `us.i.posthog.com`
- FS: only `$APPLOCALDATA/**`, `$APPDATA/**`, `$LOCALDATA/AetherCloud/**`, `$TEMP/AetherCloud-*/**`
- Shell: only `https://aethersystems.net/*` and `https://*.aethersystems.net/*`

### S3 — Consent re-verified server-side (PASS)
`commands.rs:start_install` re-checks `consent` param before any network request. Frontend cannot bypass this with a crafted IPC call.

### S4 — Login: session token stored, password never stored (PASS)
`login.html:handleLogin()` explicitly notes "NEVER store the plaintext password". Only `session_token`, `userId`, `licenseKey`, `plan` stored via `aetherAPI.authSet`.

### S5 — Pre-existing: MCP auth namespace bug (KNOWN)
`terminal.html:281`: `window.aether.authGet()` should be `window.aetherAPI.authGet()` — MCP agents send unauthenticated requests. Already documented in Session L. Not in scope for this audit.

### S6 — Electron installer simulation can mislead (LOW)
`installer.html:startInstall()` always shows success regardless of actual install state. If the Tauri wizard failed silently (partial install), the Electron simulation would still show "All 410 tests passed ✓". Risk is low because the Tauri wizard blocks on errors before spawning Electron, but worth flagging.

---

## 5. State Transitions — Wiring Status

| Transition | Mechanism | Status |
|-----------|-----------|--------|
| Consent → startInstall | `installerAPI.startInstall(consent)` via `tauri-bridge.js` | WORKS |
| Backend progress → UI | `installer://progress` Tauri event → `installerAPI.onProgress` | WORKS |
| Install done → launchApp | `installerAPI.launchApp()` | WORKS |
| Tauri → Electron spawn | `commands.rs:launch_app()` → `std::process::Command::spawn()` | WORKS |
| Electron start → installer page | Electron main.js routing (not audited in this session) | NOT AUDITED |
| Installer page 4 → login | `window.aether.navigate('login')` | WORKS |
| Login → session restore | `aetherAPI.authGet()` + `/auth/verify` | WORKS |
| Login → first-time setup | `health.needs_setup = true` → show license field | WORKS |
| Login success → dashboard | `window.aether.navigate('dashboard')` | WORKS |

**Gap: `main.js` routing on first launch** — Not audited in this session. How Electron decides to show `installer.html` vs `login.html` on cold start is unverified. This is the key missing piece for a complete end-to-end trace.

---

## 6. Bugs Found

| ID | Severity | Location | Description | Fix |
|----|----------|----------|-------------|-----|
| M-1 | LOW | `tauri.conf.json` | Missing `backgroundColor` → brief white flash on frameless window cold start | Add `"backgroundColor": "#05070d"` to window config |
| M-2 | LOW | `desktop/pages/installer.html:startInstall()` | Pure simulation — always shows success regardless of actual install state | Either link to real post-install validation IPC or document as cosmetic UX |
| L-1 | MEDIUM | `desktop/pages/terminal.html:281` | `window.aether.authGet()` should be `window.aetherAPI.authGet()` — MCP agents send unauthenticated requests | Already documented in Session L |

---

## 7. Build Attempt Status

Not attempted in Phase 1. Disk space is available (569 GB free). Blocked by:
- `cargo tauri build` requires Rust toolchain + Node.js + Tauri CLI configured — not verified in this session
- `npm run build` for `desktop/` requires checking `package.json` for build script

Recommend attempting in a follow-up session with a clean build environment check first.

---

## 8. Open Questions Requiring User Input

1. **`main.js` cold-start routing:** How does Electron decide which page to show on first launch (`installer.html` vs `login.html`)? Should this be audited?
2. **Two installer pages:** `desktop/pages/installer.html` and `desktop/pages/installer/installer.html` appear to serve the same role. Which is the canonical post-Tauri installer page? Can the other be removed?
3. **M-2 simulation:** Is the `installer.html` simulation intentionally cosmetic (Tauri wizard already did the real work), or should it be wired to real validation?
4. **M-1 flash:** Should the `backgroundColor` fix be a quick commit or bundled with the terminal fix from Session L (PR #73)?
5. **ACL gap check:** `tauri.conf.json` still has no `transparent` field set. Is this intentional (Tauri defaults to `false`) or should it be explicitly set for documentation clarity?

**Do NOT merge until questions above are reviewed. This PR contains only the investigation doc — no production code changes.**
