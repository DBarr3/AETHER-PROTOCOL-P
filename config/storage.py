"""
AetherCloud-L -- Storage Architecture
All file paths resolve through this module. Never hardcode paths elsewhere.

Aether Systems LLC -- Patent Pending

Directory Layout:
─────────────────────────────────────────────────────
aethercloud/
├── config/
│   ├── storage.py              ← this file
│   ├── credentials.json        ← bcrypt hashed, never moved
│   └── settings.json           ← app-level config
│
├── data/
│   ├── users/
│   │   └── {username}/
│   │       ├── profile.json            ← user preferences, context
│   │       ├── tasks/
│   │       │   ├── scheduled_tasks.json        ← all task definitions
│   │       │   ├── history/
│   │       │   │   └── {task_id}.json          ← run history per task
│   │       │   └── qopc/
│   │       │       └── {task_id}.json          ← behavioral signals
│   │       └── agents/
│   │           └── tone_profiles/
│   │               └── {agent_type}.json       ← learned tone per agent
│   │
├── vault/
│   └── {username}/             ← per-user vault root
│
├── crypto/
│   ├── audit/
│   │   └── aether_audit.jsonl          ← Protocol-L append-only audit log
│   ├── signatures/
│   │   └── {session_id}/
│   │       └── {commitment_hash}.json  ← per-session ECDSA signatures
│   ├── timestamps/
│   │   └── {year}/{month}/
│   │       └── {commitment_hash}.rfc3161  ← RFC 3161 timestamp receipts
│   └── seeds/
│       └── quantum_seeds.jsonl         ← IBM quantum seed pool log
│
└── logs/
    ├── server.log
    ├── scheduler.log
    └── qopc.log
─────────────────────────────────────────────────────
"""

from pathlib import Path

# ═══════════════════════════════════════════════
# SEPARATION RULES -- NEVER VIOLATE
# ═══════════════════════════════════════════════
# crypto/     -> Protocol-L ONLY. Cryptographic records.
#               Never touched by task scheduler, QOPC, or agents.
# data/users/ -> App logic ONLY. Behavioral data, tasks, tone.
#               Never touched by Protocol-L signing code.
# vault/      -> User files ONLY. Raw filesystem content.
#               Never touched by crypto or task systems.
# ═══════════════════════════════════════════════


# ── Root ─────────────────────────────────────────
ROOT = Path(__file__).parent.parent
DATA_ROOT = ROOT / "data"
CRYPTO_ROOT = ROOT / "crypto"
LOGS_ROOT = ROOT / "logs"
CONFIG_ROOT = ROOT / "config"

# ── Credentials (app-level, never per-user) ──────
CREDENTIALS_FILE = CONFIG_ROOT / "credentials.json"
SETTINGS_FILE = CONFIG_ROOT / "settings.json"

# ── Crypto (Protocol-L -- never mixed with app data) ──
AUDIT_LOG = CRYPTO_ROOT / "audit" / "aether_audit.jsonl"
SIGNATURES_DIR = CRYPTO_ROOT / "signatures"
TIMESTAMPS_DIR = CRYPTO_ROOT / "timestamps"
SEEDS_LOG = CRYPTO_ROOT / "seeds" / "quantum_seeds.jsonl"

# ── Logs ─────────────────────────────────────────
SERVER_LOG = LOGS_ROOT / "server.log"
SCHEDULER_LOG = LOGS_ROOT / "scheduler.log"
QOPC_LOG = LOGS_ROOT / "qopc.log"


# ── Per-User Path Resolvers ──────────────────────

def user_root(username: str) -> Path:
    return DATA_ROOT / "users" / username


def user_profile(username: str) -> Path:
    return user_root(username) / "profile.json"


def user_tasks_file(username: str) -> Path:
    return user_root(username) / "tasks" / "scheduled_tasks.json"


def user_task_history(username: str, task_id: str) -> Path:
    return user_root(username) / "tasks" / "history" / f"{task_id}.json"


def user_task_qopc(username: str, task_id: str) -> Path:
    return user_root(username) / "tasks" / "qopc" / f"{task_id}.json"


def user_tone_profile(username: str, agent_type: str) -> Path:
    return user_root(username) / "agents" / "tone_profiles" / f"{agent_type}.json"


def user_vault_root(username: str) -> Path:
    return ROOT / "vault" / username


# ── Crypto Path Resolvers (Protocol-L) ───────────

def signature_path(session_id: str, commitment_hash: str) -> Path:
    return SIGNATURES_DIR / session_id / f"{commitment_hash}.json"


def timestamp_path(commitment_hash: str) -> Path:
    from datetime import datetime
    now = datetime.now()
    return TIMESTAMPS_DIR / str(now.year) / f"{now.month:02d}" / f"{commitment_hash}.rfc3161"


# ── Directory Bootstrap ──────────────────────────

def ensure_user_dirs(username: str) -> None:
    """Create all required directories for a new user. Call on registration."""
    dirs = [
        user_root(username),
        user_root(username) / "tasks" / "history",
        user_root(username) / "tasks" / "qopc",
        user_root(username) / "agents" / "tone_profiles",
        user_vault_root(username),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def ensure_system_dirs() -> None:
    """Create all system-level directories on startup."""
    dirs = [
        CRYPTO_ROOT / "audit",
        CRYPTO_ROOT / "signatures",
        CRYPTO_ROOT / "timestamps",
        CRYPTO_ROOT / "seeds",
        LOGS_ROOT,
        CONFIG_ROOT,
        DATA_ROOT / "users",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
