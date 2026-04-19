# AetherCloud Installer Wizard

Tauri-based branded installer for AetherCloud-L. Gates filesystem writes on
explicit consent. See the [design spec](../docs/superpowers/specs/2026-04-18-branded-installer-wizard-design.md)
and [implementation plan](../docs/superpowers/plans/2026-04-18-branded-installer-wizard-implementation.md).

## What this is

A small (~8 MB) Windows `.exe` (`AetherCloud-Setup.exe`) that:

1. Renders the branded 4-page HTML wizard (in `src/`) locally — no network yet
2. On page 2, the user checks a consent box and clicks "Download & install"
3. Only THEN does the wizard fetch a signed `manifest-latest.json` from the CDN,
   verify its Ed25519 signature against a pinned public key, download the NSIS
   payload (`AetherCloud-L-Payload-<ver>.exe`), verify its SHA-256, and run it
   silently (`/S`)
4. On success, page 4 gives a Launch button that starts the installed app and exits

**Nothing is written to disk before consent.** Cancel at any time leaves no trace.

## Development

```bash
cd desktop-installer
npm install                 # tauri-cli only; no runtime deps
export PATH="$USERPROFILE/.cargo/bin:$PATH"  # if not already set
npx tauri dev               # runs against src/ in dev mode
```

## Release build

```bash
cd desktop-installer/src-tauri
cargo build --release
# Binary: target/release/aethercloud-installer.exe
```

Then rename and stage:
```bash
cp target/release/aethercloud-installer.exe \
   ../release/AetherCloud-Setup.exe
```

`desktop-installer/release/` is gitignored — you must sign and upload from there
manually (see below).

## Testing

```bash
cd desktop-installer/src-tauri
cargo test --release
# Expected: 25 passing (23 unit + 2 integration)
```

## Signing the wizard binary

Use the same Authenticode cert as the main app (see `desktop/package.json`
`build.win.signtoolOptions`). From a PowerShell shell with the cert in the current
user's `CurrentUser\My` store:

```powershell
$cert = (Get-ChildItem Cert:\CurrentUser\My |
         Where-Object { $_.Subject -like "*Aether Systems LLC*" })[0]

signtool sign `
  /fd SHA256 /td SHA256 `
  /tr http://timestamp.digicert.com `
  /sha1 $cert.Thumbprint `
  /n "Aether Systems LLC" `
  "C:\path\to\desktop-installer\release\AetherCloud-Setup.exe"
```

## Manifest signing (per release)

### One-time setup: generate an Ed25519 keypair

The test keypair committed at `src-tauri/keys/manifest-signing-test.pub.bin` is
for development only. Generate a production keypair BEFORE shipping the first
public wizard build.

Since the `gen_test_fixtures` bin was removed after Task 6, regenerate it
briefly OR run this one-liner with the `ed25519-dalek` crate on any machine
with Rust installed:

```rust
// cargo new keygen && cd keygen
// Cargo.toml: add ed25519-dalek = { version = "2", features = ["rand_core"] }, rand = "0.8"
use ed25519_dalek::SigningKey;
use rand::rngs::OsRng;
use std::fs;

fn main() {
    let sk = SigningKey::generate(&mut OsRng);
    fs::write("manifest-signing.pub.bin", sk.verifying_key().to_bytes()).unwrap();
    fs::write("manifest-signing.priv.bin", sk.to_bytes()).unwrap();
    println!("wrote 32-byte pub + 32-byte priv");
}
```

**Private key MUST stay offline** (USB, password manager vault, HSM — anywhere
but git). It's 32 bytes; put it somewhere encrypted and recoverable.

**Public key** replaces the test pub at
`desktop-installer/src-tauri/keys/manifest-signing-test.pub.bin`.

Update `desktop-installer/src-tauri/src/installer.rs` to reference the
production pub key:
```rust
const PINNED_PUBKEY: &[u8; 32] = include_bytes!("../keys/manifest-signing.pub.bin");
```

Rebuild the wizard — the pub key is compile-time-embedded.

### Per release: sign the manifest

1. Build the NSIS payload: `cd desktop && npm run dist`
   - Output: `desktop/release/AetherCloud-L-Payload-<ver>.exe`
2. Compute SHA-256:
   ```powershell
   (Get-FileHash "AetherCloud-L-Payload-0.9.7.exe" -Algorithm SHA256).Hash.ToLower()
   ```
3. Write the manifest JSON:
   ```json
   {
     "version": "0.9.7",
     "payload_url": "https://aethersystems.io/downloads/AetherCloud-L-Payload-0.9.7.exe",
     "payload_sha256": "<paste SHA-256 from step 2>",
     "payload_size_bytes": <file size in bytes>,
     "min_wizard_version": "1.0.0",
     "released_at": "2026-04-18T23:00:00Z"
   }
   ```
4. Sign the manifest bytes with your private key (short Rust program or any
   Ed25519 signer that produces a raw 64-byte signature over the JSON bytes).
   Output: `manifest-latest.sig` (64 bytes, binary).
5. Upload to vps1 via scp/rsync:
   ```bash
   scp manifest-latest.json aether-vps1:/var/www/aethercloud-downloads/
   scp manifest-latest.sig  aether-vps1:/var/www/aethercloud-downloads/
   scp AetherCloud-L-Payload-0.9.7.exe aether-vps1:/var/www/aethercloud-downloads/
   ```

### Nginx config on vps1

Add this location block to the `aethersystems.io` server section (see spec §8 for
full rationale — short cache on manifest, long cache on payload):

```nginx
location /downloads/ {
  alias /var/www/aethercloud-downloads/;
  autoindex off;
  add_header Cache-Control "public, max-age=60" always;

  location ~ ^/downloads/manifest-.* {
    add_header Cache-Control "public, max-age=60" always;
  }
  location ~ ^/downloads/AetherCloud-L-Payload-.*\.exe$ {
    add_header Cache-Control "public, max-age=31536000, immutable" always;
  }
}
```

## Key rotation

If the private key is ever compromised:

1. Generate a fresh Ed25519 keypair
2. Rebuild the wizard with the new `PINNED_PUBKEY`
3. Sign a NEW manifest with the new private key
4. Re-sign and upload a NEW `AetherCloud-Setup.exe` (wizards with the old pub key
   will fail-closed against manifests signed by the new key — which is correct)
5. Update `aethersystems.io/download` to link the new wizard

Old wizards in the wild will continue to fail signature verification until users
download the new one. There is no rollback.

## Verifying a clean install

Final validation runs on a clean Windows 11 22H2+ VM (operator task, post-spec):

- [ ] Download `AetherCloud-Setup.exe` from `aethersystems.io/downloads/AetherCloud-Setup.exe`
- [ ] Run. SmartScreen should NOT warn (signed binary with established reputation)
- [ ] All 4 pages render (welcome → consent → download → launch)
- [ ] Consent checkbox gates the install (primary button disabled until checked)
- [ ] Cancel mid-download leaves no trace: `%TEMP%` clean, no Start Menu entry,
      no `%LOCALAPPDATA%\aethercloud-l\`
- [ ] Tamper test: edit `manifest-latest.json` on vps1 without re-signing,
      wizard should show signature failure on the next download attempt
- [ ] Hash tamper test: swap the payload for a different signed build without
      updating the manifest, wizard should show hash-mismatch failure
- [ ] Final page Launch button opens the installed app, wizard closes
- [ ] Uninstall works via Add/Remove Programs
