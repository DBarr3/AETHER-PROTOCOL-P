# AetherCloud Installer Lifecycle

## Filesystem Map

### Directories

| Path | Phase | Cleaned on Uninstall |
|------|-------|---------------------|
| `%LOCALAPPDATA%\Programs\AetherCloud-L\` | Install (NSIS) | Yes |
| `%LOCALAPPDATA%\AetherCloud\` | Runtime (app data, cache, manifest) | Yes |
| `%APPDATA%\AetherCloud\` | Runtime (roaming config) | Yes |
| `%LOCALAPPDATA%\AetherCloud-Setup\` | Install (wizard logs) | Yes |
| `%TEMP%\aether-installer-*.exe` | Download (transient) | Cleaned on startup if stale >24h |

### Registry

| Key | Cleaned on Uninstall |
|-----|---------------------|
| `HKCU\Software\AetherCloud` | Yes |

### Credentials

| Store | Pattern | Cleaned on Uninstall |
|-------|---------|---------------------|
| Windows Credential Manager | `aethercloud.*` | Yes |

### Shortcuts

| Path | Cleaned on Uninstall |
|------|---------------------|
| Start Menu: `AetherCloud.lnk`, `AetherCloud-L.lnk` | Yes |
| Desktop: `AetherCloud.lnk`, `AetherCloud-L.lnk` | Yes |

## Cleanup Guarantees

### On Startup
- `cleanup::startup_cleanup()` scans `%TEMP%` for `.part` files older than 24 hours
- Removes orphaned downloads from interrupted/crashed previous installs

### On Shutdown
- `cleanup::shutdown_cleanup()` flushes any pending write buffers

### On Uninstall
- `cleanup::uninstall_teardown()` removes all artifacts listed above
- If an install manifest exists (`install_manifest.json`), it is read first for deterministic file-by-file cleanup
- Falls back to known-path removal if no manifest is present
- Returns an `UninstallReport` with counts of removed items and any errors

### QA Purge
- Pass `--purge` on the command line for full cleanup identical to uninstall
- Useful for QA reset between test runs

## Install Manifest

After NSIS completes, the installer writes `%LOCALAPPDATA%\AetherCloud\install_manifest.json`:

```json
{
  "version": "1.0.0",
  "install_date": "1745452800",
  "install_dir": "C:\\Users\\<user>\\AppData\\Local\\Programs\\AetherCloud-L",
  "files": [
    {
      "path": "C:\\...\\AetherCloud-L.exe",
      "sha256": null,
      "size_bytes": 94371840
    }
  ],
  "registry_keys": ["HKCU\\Software\\AetherCloud"],
  "shortcuts": []
}
```

A post-install health check writes `install_health_check.json`:

```json
{
  "timestamp": "1745452801",
  "version": "1.0.0",
  "all_files_present": true,
  "missing_files": [],
  "total_files": 12,
  "verified_files": 12,
  "status": "Healthy"
}
```

Health statuses: `Healthy` (all files present), `Degraded` (some missing), `Failed` (none present).

## Download Hygiene

- Downloads use a `.part` suffix while in progress
- Only renamed to final path after SHA-256 verification passes
- 60s connect timeout, 10 min total timeout, 30s stall detection
- Retries up to 3 times with exponential backoff (2s, 4s, 8s)
- 500 MB max download size cap
- Content-Length validated when present

## Debugging Leftover State

### Check for leftover files
```cmd
dir "%LOCALAPPDATA%\AetherCloud" 2>nul
dir "%APPDATA%\AetherCloud" 2>nul
dir "%LOCALAPPDATA%\AetherCloud-Setup" 2>nul
dir "%LOCALAPPDATA%\Programs\AetherCloud-L" 2>nul
dir "%TEMP%\aether-installer-*" 2>nul
```

### Check for leftover registry keys
```cmd
reg query "HKCU\Software\AetherCloud" 2>nul
```

### Check for leftover credentials
```cmd
cmdkey /list | findstr /i "aethercloud"
```

### Check for leftover scheduled tasks
```cmd
schtasks /query /fo CSV /nh | findstr /i "aethercloud"
```

### Check for leftover shortcuts
```cmd
dir "%APPDATA%\Microsoft\Windows\Start Menu\Programs\AetherCloud*" 2>nul
dir "%USERPROFILE%\Desktop\AetherCloud*" 2>nul
```

### Full manual cleanup (equivalent to --purge)
```cmd
rmdir /s /q "%LOCALAPPDATA%\AetherCloud" 2>nul
rmdir /s /q "%APPDATA%\AetherCloud" 2>nul
rmdir /s /q "%LOCALAPPDATA%\AetherCloud-Setup" 2>nul
rmdir /s /q "%LOCALAPPDATA%\Programs\AetherCloud-L" 2>nul
reg delete "HKCU\Software\AetherCloud" /f 2>nul
del "%TEMP%\aether-installer-*.exe" 2>nul
del "%TEMP%\aether-installer-*.exe.part" 2>nul
```
