# AetherCloud-L — Secure Distribution Build Script
# Aether Systems LLC — Patent Pending
#
# Usage:
#   .\build-dist.ps1                  # Unsigned build (SmartScreen warning)
#   .\build-dist.ps1 -CertFile cert.pfx -CertPass "yourpass"   # Signed build
#
# For signed builds, obtain a code signing certificate from:
#   - DigiCert  (https://www.digicert.com/code-signing/)
#   - Sectigo   (https://sectigo.com/ssl-certificates/code-signing)
#   - Azure Trusted Signing (cheapest — ~$10/mo via Microsoft)
#   - GlobalSign

param(
    [string]$CertFile = "",
    [string]$CertPass = "",
    [switch]$SkipClean
)

$ErrorActionPreference = "Stop"
$version = (Get-Content "package.json" | ConvertFrom-Json).version

Write-Host ""
Write-Host "═══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  AetherCloud-L v$version — Distribution Build" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── Certificate check ────────────────────────────────
$signed = $false
if ($CertFile -ne "" -and (Test-Path $CertFile)) {
    Write-Host "[+] Code signing certificate found: $CertFile" -ForegroundColor Green
    $env:CSC_LINK         = (Resolve-Path $CertFile).Path
    $env:CSC_KEY_PASSWORD = $CertPass
    $signed = $true
} elseif ($env:CSC_LINK -ne "") {
    Write-Host "[+] Code signing certificate from environment (CSC_LINK)" -ForegroundColor Green
    $signed = $true
} else {
    Write-Host "[!] No code signing certificate — build will be UNSIGNED" -ForegroundColor Yellow
    Write-Host "    Users will see a SmartScreen warning on first launch." -ForegroundColor Yellow
    Write-Host "    Set CSC_LINK + CSC_KEY_PASSWORD env vars to sign." -ForegroundColor Yellow
    Write-Host ""
    $env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
}

# ── Clean previous release ───────────────────────────
if (-not $SkipClean) {
    Write-Host "[*] Cleaning previous release..." -ForegroundColor Gray
    if (Test-Path "release") { Remove-Item -Recurse -Force "release" }
}

# ── Install dependencies ─────────────────────────────
Write-Host "[*] Installing dependencies..." -ForegroundColor Gray
npm install --production=false
if ($LASTEXITCODE -ne 0) { throw "npm install failed" }

# ── Build ────────────────────────────────────────────
Write-Host ""
if ($signed) {
    Write-Host "[*] Building SIGNED installer..." -ForegroundColor Green
} else {
    Write-Host "[*] Building UNSIGNED installer..." -ForegroundColor Yellow
}
Write-Host ""

npm run dist
if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }

# ── Verify output ────────────────────────────────────
Write-Host ""
$installer = Get-ChildItem "release\*.exe" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike "*.blockmap" }
if (-not $installer) { throw "No installer .exe found in release/" }

$sizeMB = [math]::Round($installer.Length / 1MB, 1)
Write-Host "═══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  BUILD COMPLETE" -ForegroundColor Green
Write-Host "  File   : $($installer.Name)" -ForegroundColor White
Write-Host "  Size   : ${sizeMB} MB" -ForegroundColor White
Write-Host "  Signed : $(if ($signed) { 'YES' } else { 'NO (unsigned)' })" -ForegroundColor $(if ($signed) { "Green" } else { "Yellow" })
Write-Host "  Path   : release\$($installer.Name)" -ForegroundColor White
Write-Host "═══════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── Compute SHA256 for distribution verification ─────
$hash = (Get-FileHash $installer.FullName -Algorithm SHA256).Hash
Write-Host "SHA256: $hash" -ForegroundColor Gray
Write-Host ""
Write-Host "Share this hash alongside the installer so users can verify integrity." -ForegroundColor Gray
$hash | Out-File "release\$($installer.BaseName).sha256.txt"
Write-Host "Hash saved to: release\$($installer.BaseName).sha256.txt" -ForegroundColor Gray
Write-Host ""
