"""
AetherCloud-L — Configuration & Constants
Aether Systems LLC — Patent Pending
"""

import os
from pathlib import Path

# ─── Paths ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VAULT_ROOT = PROJECT_ROOT / "vault_data"
DEFAULT_AUDIT_DIR = PROJECT_ROOT / "data" / "audit"
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
CREDENTIALS_FILE = DEFAULT_CONFIG_DIR / "credentials.json"

# ─── Auth ───────────────────────────────────────────────
SESSION_TIMEOUT_HOURS = int(os.getenv("AETHER_SESSION_TIMEOUT", "8"))
SESSION_TIMEOUT_SECONDS = SESSION_TIMEOUT_HOURS * 3600
MAX_LOGIN_ATTEMPTS = int(os.getenv("AETHER_MAX_LOGIN_ATTEMPTS", "5"))
LOCKOUT_DURATION_SECONDS = int(os.getenv("AETHER_LOCKOUT_DURATION", "900"))

# ─── Vault ──────────────────────────────────────────────
AUDIT_LOG_MAX_SIZE_MB = int(os.getenv("AETHER_AUDIT_MAX_MB", "100"))
FILE_HASH_ALGORITHM = "sha256"

# ─── Agent ──────────────────────────────────────────────
DEFAULT_OLLAMA_MODEL = os.getenv("AETHER_OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# ─── Naming Convention ──────────────────────────────────
NAMING_PATTERN = "{date}_{category}_{description}{ext}"
CATEGORIES = frozenset({
    "patent", "code", "backup", "legal",
    "finance", "trading", "security",
    "personal", "archive", "config", "log",
})

# ─── UI ─────────────────────────────────────────────────
APP_NAME = "AetherCloud-L"
APP_VERSION = "0.1.0"
APP_BANNER = f"""
╔══════════════════════════════════════════════╗
║   AETHER CLOUD-L  v{APP_VERSION}                     ║
║   Quantum-Secured File Intelligence System   ║
║   Powered by Aether Protocol-L               ║
║   Aether Systems LLC — Patent Pending        ║
╚══════════════════════════════════════════════╝
"""
