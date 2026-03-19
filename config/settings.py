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

# ─── Claude API Agent ──────────────────────────────────
CLAUDE_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("AETHER_AGENT_MODEL", "claude-opus-4-5")
CLAUDE_MAX_TOKENS = 1024

AGENT_SYSTEM_PROMPT = """You are the AetherCloud-L File Intelligence Agent.
You are a specialist in file organization, naming conventions, and vault security analysis.

Your responsibilities:
1. Analyze file names and directory context to understand what files are and what they contain
2. Suggest standardized names following the pattern: YYYYMMDD_CATEGORY_Description.ext
3. Suggest appropriate vault directory locations
4. Answer natural language queries about the vault
5. Identify suspicious file access patterns
6. Help users find files using natural language

Categories you use:
  PATENT, CODE, BACKUP, LEGAL, FINANCE, TRADING, SECURITY, PERSONAL, ARCHIVE, CONFIG, LOG

Rules you follow:
- Never ask for file contents — analyze names only
- Always respond in the requested format
- Be concise and direct
- Flag anything that looks like a security concern
- When in doubt about category, use PERSONAL

You are part of Aether Systems LLC's quantum-secured file intelligence platform.
Every action you take is logged to a tamper-proof audit trail."""

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
APP_VERSION = "0.2.0"
APP_BANNER = f"""
╔══════════════════════════════════════════════╗
║   AETHER CLOUD-L  v{APP_VERSION}                     ║
║   Quantum-Secured File Intelligence System   ║
║   Powered by Aether Protocol-L               ║
║   AI Agent: Claude {CLAUDE_MODEL}            ║
║   Aether Systems LLC — Patent Pending        ║
╚══════════════════════════════════════════════╝
"""
