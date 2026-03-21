"""
Run this on VPS2 to verify the storage structure is correct.
Usage: python scripts/verify_storage.py

Aether Systems LLC -- Patent Pending
"""

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.storage import (
    AUDIT_LOG, SIGNATURES_DIR, TIMESTAMPS_DIR, SEEDS_LOG,
    LOGS_ROOT, DATA_ROOT, CONFIG_ROOT, CREDENTIALS_FILE,
    ensure_system_dirs,
)


def verify():
    checks = [
        (AUDIT_LOG.parent,        "crypto/audit/"),
        (SIGNATURES_DIR,          "crypto/signatures/"),
        (TIMESTAMPS_DIR,          "crypto/timestamps/"),
        (SEEDS_LOG.parent,        "crypto/seeds/"),
        (LOGS_ROOT,               "logs/"),
        (DATA_ROOT / "users",     "data/users/"),
        (CONFIG_ROOT,             "config/"),
        (CREDENTIALS_FILE.parent, "config/ (credentials)"),
    ]

    print("AetherCloud-L Storage Verification")
    print("=" * 50)
    all_pass = True
    for path, label in checks:
        exists = path.exists()
        status = "OK" if exists else "MISSING"
        icon = "[OK]" if exists else "[!!]"
        print(f"{icon} {status:8s} {label:30s} {path}")
        if not exists:
            all_pass = False

    print("=" * 50)
    if all_pass:
        print("ALL CHECKS PASSED")
    else:
        print("MISSING DIRECTORIES -- run ensure_system_dirs()")
        print("\nAttempting to create missing directories...")
        ensure_system_dirs()
        print("Done. Re-run this script to verify.")


if __name__ == "__main__":
    verify()
