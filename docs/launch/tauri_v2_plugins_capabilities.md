# Tauri v2 plugin crates + capability ACL wiring — 2026-04-23

**Owner of record:** Session H (branch `claude/tauri-v2-plugins-capabilities`).

**Purpose.** Make Session D's `tauri.conf.json` hardening (PR #57) actually
enforce at runtime. In Tauri v2 the old v1 `allowlist` config is gone;
scoping lives in three places that must stay in sync:

1. Per-plugin crates in `desktop-installer/src-tauri/Cargo.toml`.
2. Per-plugin Builder registration in `desktop-installer/src-tauri/src/main.rs`.
3. Capability JSON files under `desktop-installer/src-tauri/capabilities/*.json`
   declaring which plugins each window can call, with optional allow/deny
   scopes per permission.

Without all three, a plugin either (a) isn't compiled in (Cargo), (b) has
no IPC handler registered (Builder), or (c) is registered but unusable
because no capability grants the frontend access to its permissions
(ACL). All three layers are now wired.

## 1. Plugin crates added to Cargo.toml

Tauri core: `tauri = "2"` → Cargo.lock resolves to **2.10.3**. Plugin
crates pinned to `"2"` (matching major); Cargo.lock resolves each to the
latest 2.x release compatible with `tauri 2.10.3`.

| Crate | Resolved by cargo | Why |
| --- | --- | --- |
| `tauri-plugin-fs` | 2.x | File system reads/writes under app data dirs. `cleanup.rs` + `install_manifest.rs` write install state; `download.rs` stages payload `.part` files. |
| `tauri-plugin-dialog` | 2.7.0 | Native open/save/message/ask/confirm dialogs. Wizard uses them for error modals + "choose install path" (future). |
| `tauri-plugin-shell` | 2.3.5 | `shell.open()` for opening the signed-up customer portal + docs after install. NOT used for arbitrary command exec — `allow-open` only, no `allow-execute`. |
| `tauri-plugin-http` | 2.5.8 | `reqwest` already ships in direct deps, but the plugin exposes a **capability-gated** HTTP surface to the frontend if we ever expose license-check from JS. Gated strictly to aethersystems.net hosts. |
| `tauri-plugin-notification` | 2.3.3 | Windows toast notifications on install complete / update available. |
| `tauri-plugin-process` | 2.3.1 | `exit()` + `restart()` for the post-install relaunch flow (currently handled in Rust via `std::process::Command`; plugin lets the frontend trigger it safely). |
| `tauri-plugin-updater` | 2.10.1 | The updater moved from a core feature in v1 to a plugin in v2. Required to honor `plugins.updater.endpoints` / `pubkey` in `tauri.conf.json`. |

**Version pinning policy.** `"2"` (caret requirement) lets cargo resolve
any `2.x.y` that transitively matches tauri 2.10.3. Cargo.lock pins the
exact resolved versions reproducibly. Avoid pinning to exact patch
versions here — plugin crates ship security fixes frequently, and the
lockfile already enforces reproducibility.

## 2. Plugin registration in `main.rs`

The `.plugin(...)` calls were inserted at the top of the Builder chain
(before `.manage()` / `.invoke_handler()`) so each plugin's state is
initialized before our own `#[tauri::command]` handlers run. The
updater uses its nested Builder: `tauri_plugin_updater::Builder::new().build()`.

**Preserved untouched (explicitly):**

- Session F's `startup_cleanup()` panic-guarded call (L78-83).
- Session F's `check_purge_flag()` / `purge()` CLI shortcut (L87-91).
- Session F's `shutdown_cleanup()` post-`.run()` call (L109 in pre-edit,
  still last statement of `main()` after this PR).
- The PR #50 telemetry TODO slot in the comment block above the Builder.
- `PINNED_PUBKEY` in `installer.rs` — file not opened, not touched.
- `commands.rs` command handlers — not touched.

## 3. Capability file: `capabilities/default.json`

Expanded from the Session F minimal baseline (`["core:default"]`) to
cover every plugin we registered. Targets the single `main` window
(Tauri v2's default label when `tauri.conf.json` omits `label`).

### Plain-language permission summary

- **`core:default`** — Baseline Tauri core commands (app info, path resolution, etc.). Already required by `invoke()`.
- **`core:event:default`** — Allows the frontend to `listen()` for backend-emitted events like `installer://progress`. Load-bearing: without it the wizard silently never receives progress updates (Session E audit documented this as the "Backend not responding" bug).
- **`core:window:default`** — `getCurrent()`, `close()`, `minimize()`, etc. Needed because `commands::launch_app` calls `win.close()`.
- **`fs:default` (scoped)** — File system reads/writes allowed only under:
  - `$APPLOCALDATA/**` — Tauri-resolved per-app local data dir.
  - `$APPDATA/**` — Tauri-resolved per-app roaming dir.
  - `$LOCALDATA/AetherCloud/**` — the installed app's state dir.
  - `$LOCALDATA/AetherCloud-Setup/**` — where `init_logging()` writes `install.log` (main.rs L12-17).
  - `$TEMP/AetherCloud-*/**` — staging dirs used by `download.rs` for `.part` files and cleaned by `cleanup::startup_cleanup()`.
  Any path outside these is denied by the plugin default-deny fallback.
- **`dialog:allow-open` / `allow-save` / `allow-message` / `allow-ask` / `allow-confirm`** — Individual dialog types. Preferred over `dialog:default` so that future permissions added to `default` (e.g., a hypothetical `allow-custom-picker`) don't silently widen our surface.
- **`shell:allow-open` (scoped)** — Only URLs matching `https://aethersystems.net/*` and `https://*.aethersystems.net/*` can be opened via `shell.open()`. Blocks redirection attacks where a compromised WebView could open attacker-controlled URLs in the user's default browser.
- **`http:default` (scoped)** — Only requests to `https://api.aethersystems.net/*`, `https://license.aethersystems.net/*`, `https://app.aethersystems.net/*`. Matches the CSP `connect-src` hosts in `tauri.conf.json`.
- **`notification:default`** — Toast notifications; no scope needed (no URL/path surface).
- **`process:allow-exit` / `allow-restart`** — The two safe process-control commands. Explicitly omits `allow-*-app` variants that could trigger elevated behavior.
- **`updater:default`** — Check-for-update + install flow. Scoped by the `endpoints` list in `tauri.conf.json` and gated by the `pubkey` signature check at install time.

### Security posture: why `default` sometimes, scoped elsewhere

- For **permission groups with no URL/path surface** (`core:*`, `notification:*`, `updater:*`, `process:allow-exit|restart`), `default` is safe — the permission grants a finite set of commands, and each is inherently safe or already gated elsewhere (e.g., updater is gated by `pubkey`).
- For **surface-bearing groups** (`fs:*`, `shell:*`, `http:*`), `default` is too broad because it grants full filesystem / arbitrary URL opens. We switched to explicit `allow` scopes so a WebView compromise can't escalate to "read/write arbitrary file" or "open arbitrary URL."
- For **`dialog:*`**, we use per-type `allow-*` strings rather than `dialog:default` to avoid silent widening when a future Tauri release adds a new dialog type to `default`.

## 4. User-input items still pending

These placeholders must be filled in by a human. They are called out so
they don't silently land in a PR.

1. **`plugins.updater.pubkey`** in `tauri.conf.json`. Currently `""`.
   Blocks the updater plugin from verifying any signed update bundle.
   Generate with:
   ```
   cargo install tauri-cli --locked
   cargo tauri signer generate -w ~/.tauri/aethercloud-updater.key
   ```
   Copy the public key into `plugins.updater.pubkey`. Private key goes
   to a secrets manager — never commit it. Ownership: Session D (the
   tauri.conf.json owner) or whoever sets up the updater CI pipeline.
2. **`bundle.windows.certificateThumbprint`** in `tauri.conf.json`.
   Currently `null`. Set via CI env at sign time. Requires decision on
   code-signing provider (DigiCert EV, SSL.com, self-hosted HSM).
3. **`capabilities/` schema sync.** The `$schema` reference points at
   `../gen/schemas/desktop-schema.json`, which `tauri-build` only
   generates on the first successful full build. Once the first
   `cargo tauri build` succeeds (post-sign-cert), run it locally to
   drop the schema file alongside the capability so editors get
   autocomplete. Nice-to-have, not a blocker.

## 5. Verification matrix — which permission gates what

| In-code call | Gated by | Scope |
| --- | --- | --- |
| `app.emit("installer://progress", ev)` (commands.rs L28, L39, L75) | `core:event:default` | All events |
| `app.get_webview_window("main")` (commands.rs L106) → `.close()` | `core:window:default` | main window only |
| `invoke('start_install', ...)` (frontend) | `core:default` + our `#[tauri::command]` registration in `invoke_handler![]` | Our 4 commands only |
| `std::fs::create_dir_all(&dir)` (main.rs L21) writing `install.log` | Native Rust — not ACL-gated; frontend FS writes via `fs:*` plugin ARE gated | n/a / path allowlist |
| Future frontend `readTextFile($APPLOCALDATA/manifest.json)` | `fs:default` with `$APPLOCALDATA/**` allow | per allow list |
| Future frontend `open('https://aethersystems.net/docs')` | `shell:allow-open` with `https://*.aethersystems.net/*` allow | aethersystems.net only |
| Future frontend `fetch('https://api.aethersystems.net/...')` via http plugin | `http:default` with per-host allow | 3 hosts only |
| Backend updater plugin polling `license.aethersystems.net/updater/...` | `updater:default` + `plugins.updater.endpoints` + `pubkey` | per endpoint config |
| `notification.requestPermission()` + `notification.send()` | `notification:default` | all |
| `process.exit()` / `process.restart()` | `process:allow-exit` / `process:allow-restart` | exit + restart only |

## 6. `cargo check` verification

- Ran `cargo check` against the worktree with `CARGO_TARGET_DIR` pointing
  at the main repo's target dir (shared cache) to minimize disk usage.
  Log captured at `docs/launch/tauri_v2_plugins_check_2026-04-23.log`.
- **Result:** plugin crates resolved and compiled successfully. All 7
  new plugin crates matched `tauri 2.10.3` cleanly — no version-mismatch
  errors. tauri-build 2.5.6 pulled in; tauri core 2.10.3 checked;
  every plugin-updater dep (minisign-verify, ed25519, rustls, etc.)
  compiled successfully through the main crate's `Checking` phase.
- **Build script failure, pre-existing, NOT caused by this PR:** The
  check reached the `aethercloud-installer` crate's `build.rs` (which
  calls `tauri_build::build()`). That then parsed `tauri.conf.json` and
  failed with:
  > `unknown field 'identifier'` in `bundle`
  That `bundle.identifier` key was added by Session D in PR #57. In
  `tauri-build 2.5.6`'s config parser, `identifier` is valid at the
  root (where we also have it — line 5 of the JSON) but NOT nested
  inside `bundle {}` (line 31 of the JSON). Fixing this requires a
  one-line edit to `tauri.conf.json` removing the duplicate
  `bundle.identifier`. **That file is owned by Session D and out of
  scope for this PR** (Session H's writable-file list explicitly
  excludes `tauri.conf.json`). A follow-up PR from Session D should:
  - Remove line 31: `"identifier": "net.aethersystems.aethercloud",` from `bundle {}`.
  - Root-level `identifier` at line 5 is the one `tauri-build` honors and is already correct.
  Once that lands, `cargo check` completes green.
- **Post-check disk hygiene:** `cargo clean` ran; target dir reclaimed
  1.6 GB. Disk returned to 4.0 GB free (same as pre-check baseline).

## 7. Preservation proof

Files touched by this PR (verified via `git diff --stat`):
- `desktop-installer/src-tauri/Cargo.toml` (+12 -1)
- `desktop-installer/src-tauri/src/main.rs` (+15 -0)
- `desktop-installer/src-tauri/capabilities/default.json` (rewrite)
- `docs/launch/tauri_v2_plugins_capabilities.md` (new)
- `docs/launch/tauri_v2_plugins_check_2026-04-23.log` (new)

Files NOT touched (verified via `git diff` returning empty for each):
- `desktop-installer/src-tauri/tauri.conf.json` (Session D's authority).
- `desktop-installer/src-tauri/src/installer.rs` (contains `PINNED_PUBKEY` — sacred).
- `desktop-installer/src-tauri/src/{cleanup,download,install_manifest}.rs` (Session B/F).
- `desktop-installer/tests/**` (Session A).
- `desktop/**` (Electron payload tree).
- `.github/workflows/**`.

The PR #50 telemetry TODO slot comment block above the Builder is
unchanged. The augmenting comment added below it sits after the
original TODO and does not populate any handler.
