"""
AetherCloud-L — Configuration & Constants
Aether Systems LLC — Patent Pending
"""

import os
from pathlib import Path

# ─── Paths ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VAULT_ROOT = Path(os.getenv("AETHER_VAULT_ROOT", str(PROJECT_ROOT / "vault_data")))
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

# ─── Claude API Agent ──────────────────────────────────
# Key loaded via key_manager — never hardcoded
from config.key_manager import get_anthropic_key
CLAUDE_API_KEY = get_anthropic_key()
CLAUDE_MODEL = os.getenv("AETHER_AGENT_MODEL", "claude-opus-4-5")
CLAUDE_MAX_TOKENS = 1024

# System prompt — full specialist version in config/agent_prompt.py
# This legacy constant is kept for backward compat with standard (non-hardened) agent
from config.agent_prompt import AETHER_AGENT_SYSTEM_PROMPT
AGENT_SYSTEM_PROMPT = AETHER_AGENT_SYSTEM_PROMPT

# ─── Hardened Agent ───────────────────────────────────
HARDENED_AGENT_ENABLED = os.getenv("AETHER_HARDENED_AGENT", "true").lower() == "true"
RFC3161_ENABLED = os.getenv("AETHER_RFC3161_ENABLED", "true").lower() == "true"

# ─── Legacy (kept for backward compat) ─────────────────
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
APP_VERSION = "0.5.0"
APP_BANNER = f"""
╔══════════════════════════════════════════════╗
║   AETHER CLOUD-L  v{APP_VERSION}                     ║
║   Quantum-Secured File Intelligence System   ║
║   Powered by Aether Protocol-L               ║
║   AI Agent: Claude {CLAUDE_MODEL}            ║
║   Aether Systems LLC — Patent Pending        ║
╚══════════════════════════════════════════════╝
"""
