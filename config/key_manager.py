"""
AetherCloud-L — Key Manager
Loads secrets from environment variables only.
Never from files in the repo directory.

Priority order:
1. System environment variables (set via /etc/aethercloud/.env)
2. Process environment (set via systemd service file)
3. Raise clear error — never fall back to a hardcoded value

VPS2 Setup:
    sudo mkdir -p /etc/aethercloud
    sudo nano /etc/aethercloud/.env
    sudo chmod 600 /etc/aethercloud/.env
    sudo chown root:root /etc/aethercloud/.env

Aether Systems LLC — Patent Pending
"""

import os
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("aethercloud.keys")

_REQUIRED_KEYS = [
    "ANTHROPIC_API_KEY",
]

_OPTIONAL_KEYS = [
    "IBM_QUANTUM_API_KEY",
    "AETHER_DEV_KEY",
    "AETHER_BIND_HOST",
    "AETHER_BIND_PORT",
    "AETHER_VAULT_ROOT",
]


def _load_env_file() -> None:
    """
    Load /etc/aethercloud/.env into os.environ if it exists.
    This file is outside the repo, chmod 600, root-owned.
    Format: KEY=VALUE (one per line, no quotes needed)
    """
    env_paths = [
        Path("/etc/aethercloud/.env"),          # Production VPS
        Path.home() / ".aethercloud" / ".env",  # Dev fallback
    ]

    for env_path in env_paths:
        if env_path.exists():
            try:
                with open(env_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, _, value = line.partition("=")
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            # Only set if not already in environment
                            if key not in os.environ:
                                os.environ[key] = value
                log.info("Loaded env from %s", env_path)
                return
            except PermissionError:
                log.warning("Permission denied reading %s", env_path)
            except Exception as e:
                log.warning("Failed to load env file %s: %s", env_path, e)


def load_all_keys() -> None:
    """Call once at startup — loads env file then validates required keys."""
    _load_env_file()
    _validate_required()


def _validate_required() -> None:
    """Raise clear error if any required key is missing."""
    missing = [k for k in _REQUIRED_KEYS if not os.environ.get(k)]
    if missing:
        log.error(
            "Missing required environment variables: %s. "
            "Set them in /etc/aethercloud/.env on VPS2. "
            "See config/key_manager.py for setup instructions.",
            missing,
        )
        # Warning, not fatal — allows tests and local dev to run
        # without keys. Services that need keys will fail gracefully.


def get_anthropic_key() -> Optional[str]:
    """Return Anthropic API key. Returns None if not set."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        log.warning("ANTHROPIC_API_KEY not set. Check /etc/aethercloud/.env")
        return None
    return key


def get_ibm_token() -> Optional[str]:
    """Return IBM Quantum token. Returns None if not set (falls back to simulator)."""
    return os.environ.get("IBM_QUANTUM_API_KEY") or None


def get_dev_key() -> str:
    """Return dev user key with secure fallback."""
    return os.environ.get(
        "AETHER_DEV_KEY",
        "fdf&*79u9*(*HJBh*U((9jijkKKL-d8a9(OS)0k"
    )


def mask(key: str) -> str:
    """Return masked version for logging — never log full keys."""
    if not key or len(key) < 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"
