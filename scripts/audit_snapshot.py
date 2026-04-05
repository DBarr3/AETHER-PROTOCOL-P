#!/usr/bin/env python3
"""
Aether Audit Log Snapshot — External Integrity Anchor

Runs periodically (via cron/systemd timer) on VPS2.
1. Computes SHA-256 of the entire audit JSONL file
2. Verifies the internal hash chain
3. POSTs the snapshot to VPS5 for external storage
4. Appends to a local snapshot ledger for quick comparison

Usage:
    python3 scripts/audit_snapshot.py

Environment:
    AETHER_AUDIT_LOG    — path to audit JSONL (default: data/aethercloud_audit.jsonl)
    VPS5_SNAPSHOT_URL   — VPS5 endpoint to POST snapshots to (over Tailscale)
    MCP_ALERT_KEY       — shared secret for VPS5 auth header
"""

import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SNAPSHOT] %(message)s")
log = logging.getLogger("audit_snapshot")

AUDIT_LOG_PATH  = Path(os.getenv("AETHER_AUDIT_LOG", "data/aethercloud_audit.jsonl"))
SNAPSHOT_LEDGER = AUDIT_LOG_PATH.parent / "audit_snapshots.jsonl"
VPS5_URL        = os.getenv("VPS5_SNAPSHOT_URL", "http://100.84.205.12:8095/audit/snapshot")
ALERT_KEY       = os.getenv("MCP_ALERT_KEY", "")


def hash_file(path: Path) -> str:
    """SHA-256 of entire file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_chain(path: Path) -> dict:
    """Walk the JSONL and verify prev_hash chain integrity."""
    total = 0
    broken_at = None
    missing_prev = 0
    prev_hash = "GENESIS"

    with open(path, "rb") as f:
        for raw in f:
            stripped = raw.strip()
            if not stripped:
                continue
            total += 1
            try:
                data = json.loads(stripped.decode("utf-8"))
            except Exception:
                if broken_at is None:
                    broken_at = total
                continue

            entry_prev = data.get("prev_hash")
            if entry_prev is None:
                missing_prev += 1
                prev_hash = hashlib.sha256(stripped).hexdigest()
                continue

            if entry_prev != prev_hash and broken_at is None:
                broken_at = total

            prev_hash = hashlib.sha256(stripped).hexdigest()

    return {
        "total_entries": total,
        "chain_valid": broken_at is None,
        "broken_at_entry": broken_at,
        "missing_prev_hash": missing_prev,
    }


def post_to_vps5(snapshot: dict) -> bool:
    """POST snapshot to VPS5 over Tailscale for external storage."""
    if not VPS5_URL:
        return False
    try:
        import urllib.request
        body = json.dumps(snapshot).encode()
        req = urllib.request.Request(
            VPS5_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Aether-Alert-Key": ALERT_KEY,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        log.warning("Failed to POST snapshot to VPS5: %s", e)
        return False


def main():
    if not AUDIT_LOG_PATH.exists():
        log.error("Audit log not found: %s", AUDIT_LOG_PATH)
        sys.exit(1)

    log.info("Hashing audit log: %s", AUDIT_LOG_PATH)
    file_hash = hash_file(AUDIT_LOG_PATH)
    file_size = AUDIT_LOG_PATH.stat().st_size

    log.info("Verifying hash chain...")
    chain = verify_chain(AUDIT_LOG_PATH)

    snapshot = {
        "timestamp": time.time(),
        "iso_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "log_path": str(AUDIT_LOG_PATH),
        "file_sha256": file_hash,
        "file_size_bytes": file_size,
        "chain_integrity": chain,
        "node": "VPS2",
    }

    # Append to local ledger
    SNAPSHOT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(SNAPSHOT_LEDGER, "a") as f:
        f.write(json.dumps(snapshot) + "\n")
    log.info("Snapshot saved to local ledger: %s", SNAPSHOT_LEDGER)

    # Post to VPS5
    if post_to_vps5(snapshot):
        log.info("Snapshot posted to VPS5 successfully")
    else:
        log.warning("VPS5 snapshot POST failed — local ledger still updated")

    # Report
    log.info(
        "RESULT: entries=%d chain_valid=%s file_sha256=%s...%s",
        chain["total_entries"],
        chain["chain_valid"],
        file_hash[:8],
        file_hash[-8:],
    )

    if not chain["chain_valid"]:
        log.error(
            "CHAIN INTEGRITY BROKEN at entry %d — audit log may have been tampered!",
            chain["broken_at_entry"],
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
