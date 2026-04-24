# AetherCloud Installer Filesystem Audit — 2026-04-23

Session B audit of every path the installer touches across its lifecycle.

## 1. Download Phase

| Path | Purpose | Lifetime |
|------|---------|----------|
| `%TEMP%\aether-installer-<uuid>.exe` | Downloaded NSIS payload (via `payload::temp_payload_path()`) | Deleted after NSIS runs or on error |
| `%TEMP%\aether-installer-<uuid>.exe.part` | In-progress download (new in `download.rs`) | Renamed to final on SHA-256 match; deleted on failure; stale ones cleaned on startup if >24h old |

**Pre-hygiene gaps found:**
- No `.part` suffix — a crash left a fully-named but truncated `.exe` that could be mistaken for a valid payload.
- No retry logic — a transient network failure required the user to restart the entire wizard.
- No stale temp cleanup — interrupted downloads accumulated in `%TEMP%` indefinitely.

## 2. Extraction Phase

The installer does not perform its own extraction. NSIS handles this internally during `run_payload_silent()`.

## 3. Install Phase (NSIS)

| Path | Purpose |
|------|---------|
| `%LOCALAPPDATA%\Programs\AetherCloud-L\` | Primary install directory (electron-builder default for per-user, one-click) |
| `%LOCALAPPDATA%\Programs\aethercloud-l\` | Alternate casing (NSIS creates based on `artifactName`) |
| `%LOCALAPPDATA%\AetherCloud-L\` | Legacy install path (some early builds) |

## 4. Runtime Paths

| Path | Purpose | Created By |
|------|---------|------------|
| `%LOCALAPPDATA%\AetherCloud\` | App data, cache, secure store | Electron app at runtime |
| `%APPDATA%\AetherCloud\` | Roaming config, user preferences | Electron app at runtime |
| `%LOCALAPPDATA%\AetherCloud-Setup\install.log` | Installer wizard log (append-mode) | `main.rs::init_logging()` |
| `%LOCALAPPDATA%\AetherCloud\install_manifest.json` | Install manifest (new) | `install_manifest.rs` after NSIS completes |
| `%LOCALAPPDATA%\AetherCloud\install_health_check.json` | Post-install health check (new) | `install_manifest.rs` health_check |

## 5. Registry

| Key | Purpose |
|-----|---------|
| `HKCU\Software\AetherCloud` | App settings, license state |

## 6. Credentials

| Store | Pattern |
|-------|---------|
| Windows Credential Manager | Entries matching `aethercloud.*` |

## 7. Shortcuts

| Path | Purpose |
|------|---------|
| `%APPDATA%\Microsoft\Windows\Start Menu\Programs\AetherCloud.lnk` | Start Menu shortcut |
| `%APPDATA%\Microsoft\Windows\Start Menu\Programs\AetherCloud-L.lnk` | Alt Start Menu shortcut |
| `%USERPROFILE%\Desktop\AetherCloud.lnk` | Desktop shortcut |
| `%USERPROFILE%\Desktop\AetherCloud-L.lnk` | Alt Desktop shortcut |

## 8. Uninstall Phase (Before Hygiene)

**What was cleaned:** NSIS uninstaller removes its own install directory.

**What was left behind (gaps):**
- `%LOCALAPPDATA%\AetherCloud\` — NOT removed
- `%APPDATA%\AetherCloud\` — NOT removed
- `%LOCALAPPDATA%\AetherCloud-Setup\` — NOT removed
- `HKCU\Software\AetherCloud` — NOT removed
- Credential Manager entries — NOT removed
- Shortcuts — Left if NSIS uninstaller did not create them
- `%TEMP%\aether-installer-*.exe` — Orphaned downloads left indefinitely

## 9. After Hygiene (This PR)

**Cleanup lifecycle guarantees:**
- Startup: stale `.part` files >24h are removed from `%TEMP%`
- Shutdown: pending writes flushed
- Uninstall (`cleanup::uninstall_teardown()`): removes ALL paths in sections 3-7 above
- QA purge (`--purge` flag): identical to uninstall teardown
- Install manifest tracks every placed file for deterministic cleanup

**Target leftover count after clean uninstall: 0 files, 0 registry keys.**
