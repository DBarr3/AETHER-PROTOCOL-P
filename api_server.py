#!/usr/bin/env python3
"""
AetherCloud-L — FastAPI Server
REST API on localhost:8741 for the Electron desktop app.

Aether Systems LLC — Patent Pending
"""

import json
import os
import sys
import time
import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from datetime import datetime

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load secure key store FIRST — before any service that needs API keys
from config.key_manager import load_all_keys, get_anthropic_key, get_ibm_token, get_dev_key, mask
load_all_keys()

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import uvicorn

from config.settings import (
    APP_NAME, APP_VERSION, DEFAULT_VAULT_ROOT, DEFAULT_AUDIT_DIR,
)
from config.storage import (
    ensure_system_dirs, ensure_user_dirs,
    CREDENTIALS_FILE as STORAGE_CREDENTIALS_FILE,
    AUDIT_LOG as STORAGE_AUDIT_LOG,
    user_tasks_file, user_task_history, user_task_qopc,
)
from auth.login import AetherCloudAuth
from auth.session import SessionManager
from vault.filebase import AetherVault
from vault.watcher import VaultWatcher
from vault.read_detector import ReadDetector
from agent.file_agent import AetherFileAgent
from agent.task_scheduler import (
    TaskScheduler, execute_task, load_task_store, save_task_store,
    get_task_history, parse_schedule,
)
from agent.task_qopc import TaskQOPC, TaskSignal
from aether_protocol.audit import AuditLog

log = logging.getLogger("aethercloud.api")

# ═══════════════════════════════════════════════════
# FILE METADATA — single source of truth for ext → (icon, category)
# ═══════════════════════════════════════════════════
_EXT_META: dict[str, tuple[str, str]] = {
    # CODE
    ".py":   ("🐍", "CODE"),   ".js":  ("📜", "CODE"),   ".ts": ("📜", "CODE"),
    ".html": ("🌐", "CODE"),   ".css": ("🎨", "CODE"),
    # CONFIG
    ".json": ("📋", "CONFIG"), ".yaml": ("📋", "CONFIG"), ".yml": ("📋", "CONFIG"),
    ".toml": ("📋", "CONFIG"),
    # DOCUMENT / PATENT / LEGAL
    ".pdf":  ("📄", "PATENT"), ".docx": ("📝", "LEGAL"),  ".doc": ("📝", "LEGAL"),
    ".txt":  ("📃", "PERSONAL"), ".md": ("📖", "PERSONAL"), ".rst": ("📖", "PERSONAL"),
    # FINANCE / TRADING
    ".xlsx": ("📊", "FINANCE"), ".csv": ("📊", "FINANCE"), ".xls": ("📊", "FINANCE"),
    # ARCHIVE / BACKUP
    ".zip":  ("🗜", "ARCHIVE"), ".tar": ("🗜", "ARCHIVE"), ".gz":  ("🗜", "ARCHIVE"),
    ".rar":  ("🗜", "ARCHIVE"),
    # MEDIA
    ".png":  ("🖼", "PERSONAL"), ".jpg": ("🖼", "PERSONAL"), ".jpeg": ("🖼", "PERSONAL"),
    ".gif":  ("🖼", "PERSONAL"), ".svg": ("🖼", "PERSONAL"),
    ".mp4":  ("🎬", "PERSONAL"), ".mp3": ("🎵", "PERSONAL"), ".wav":  ("🎵", "PERSONAL"),
    # SECURITY
    ".key":  ("🔑", "SECURITY"), ".pem": ("🔑", "SECURITY"), ".enc": ("🔑", "SECURITY"),
    # DATA
    ".db":   ("💾", "BACKUP"),  ".sqlite": ("💾", "BACKUP"),
    # LOG
    ".log":  ("📋", "LOG"),
}


def _file_icon(ext: str) -> str:
    """Return emoji icon for file extension."""
    meta = _EXT_META.get(ext.lower())
    return meta[0] if meta else "📄"


def _guess_category(ext: str) -> str:
    """Guess file category from extension."""
    meta = _EXT_META.get(ext.lower())
    return meta[1] if meta else "PERSONAL"


def _format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    for unit, threshold in [("B", 1024), ("KB", 1024**2), ("MB", 1024**3)]:
        if size_bytes < threshold:
            divisor = threshold // 1024 if unit != "B" else 1
            return f"{size_bytes / divisor:.1f} {unit}" if unit != "B" else f"{size_bytes} B"
    return f"{size_bytes / (1024**3):.1f} GB"


def _commitment_hash(data) -> str:
    """Compute a short commitment hash for response integrity."""
    return hashlib.sha256(str(data).encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════
# DIRECTORY BROWSING HELPERS (for /vault/browse)
# ═══════════════════════════════════════════════════

def _get_category_by_name(name: str, ext: str) -> str:
    """Categorize file by name keywords, then extension."""
    name_lower = name.lower()
    if any(k in name_lower for k in ("patent", "filing", "uspto", "claim")):
        return "PATENT"
    if any(k in name_lower for k in ("trade", "position", "pnl", "option", "futures", "ym_", "spy_")):
        return "TRADING"
    if any(k in name_lower for k in ("password", "key", "secret", "credential", "token", "api_key")):
        return "SECURITY"
    # Fall back to extension-based via _EXT_META, with broader coverage
    _extra = {
        ".jsx": "CODE", ".tsx": "CODE", ".sh": "CODE", ".go": "CODE", ".rs": "CODE",
        ".cpp": "CODE", ".c": "CODE", ".java": "CODE", ".rb": "CODE", ".bat": "CODE",
        ".env": "CONFIG", ".ini": "CONFIG",
        ".7z": "ARCHIVE",
        ".jpeg": "PERSONAL", ".mov": "PERSONAL",
        ".sql": "BACKUP",
    }
    meta = _EXT_META.get(ext.lower())
    if meta:
        return meta[1]
    return _extra.get(ext.lower(), "PERSONAL")


def _get_folder_icon(name: str) -> str:
    """Return emoji icon based on folder name."""
    n = name.lower()
    if any(k in n for k in ("patent", "legal", "law")):
        return "📋"
    if any(k in n for k in ("code", "src", "dev", "github", "project", "aether")):
        return "💻"
    if any(k in n for k in ("trad", "finance", "invest", "stock", "market")):
        return "📈"
    if any(k in n for k in ("security", "secure", "key", "vault", "crypto")):
        return "🛡"
    if any(k in n for k in ("backup", "archive", "old", "bak")):
        return "💾"
    if any(k in n for k in ("photo", "image", "picture", "media", "video")):
        return "🖼"
    if any(k in n for k in ("doc", "document", "report", "note")):
        return "📝"
    if any(k in n for k in ("download", "dl")):
        return "📥"
    if "desktop" in n:
        return "🖥"
    return "📁"


# ═══════════════════════════════════════════════════
# SERVICE CONTAINER
# ═══════════════════════════════════════════════════
@dataclass
class Services:
    """Holds all initialized backend services."""
    audit_log: Optional[AuditLog] = None
    auth: Optional[AetherCloudAuth] = None
    session_mgr: Optional[SessionManager] = None
    vault: Optional[AetherVault] = None
    watcher: Optional[VaultWatcher] = None
    agent: Optional[AetherFileAgent] = None
    scheduler: Optional[TaskScheduler] = None
    read_detector: Optional[ReadDetector] = None

    @property
    def ready(self) -> bool:
        return self.auth is not None and self.vault is not None


svc = Services()
session_context: dict[str, str] = {}
_task_stores: dict[str, dict[str, dict]] = {}  # username → {task_id → task_dict}
_task_qopcs: dict[str, TaskQOPC] = {}  # username → TaskQOPC instance
_start_time = time.time()


def _get_task_store(username: str) -> dict[str, dict]:
    """Get or lazily load a user's task store."""
    if username not in _task_stores:
        tasks_path = user_tasks_file(username)
        if tasks_path.exists():
            try:
                tasks = json.loads(tasks_path.read_text())
                _task_stores[username] = {t["task_id"]: t for t in tasks}
            except Exception:
                _task_stores[username] = {}
        else:
            _task_stores[username] = {}
    return _task_stores[username]


def _save_task_store(username: str):
    """Persist a user's task store to their data directory."""
    store = _task_stores.get(username, {})
    path = user_tasks_file(username)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(list(store.values()), indent=2))
    except Exception as e:
        log.error("Failed to save task store for %s: %s", username, e)


def _get_task_qopc(username: str) -> TaskQOPC:
    """Get or lazily create a user's TaskQOPC instance."""
    if username not in _task_qopcs:
        _task_qopcs[username] = TaskQOPC(username)
    return _task_qopcs[username]
_PROTOCOL_VARIANT = os.environ.get("AETHER_PROTOCOL_VARIANT", "C")
_ibm_status_cache: dict = {
    "value": "CSPRNG" if _PROTOCOL_VARIANT == "C" else "OS_URANDOM",
    "expires": 0.0,
}

security = HTTPBearer(auto_error=False)


def _init_services():
    """Initialize all backend services into the container."""
    # Bootstrap all system directories via storage.py
    ensure_system_dirs()

    # Audit log — resolves via storage.py crypto/ path
    audit_dir = STORAGE_AUDIT_LOG.parent
    audit_dir.mkdir(parents=True, exist_ok=True)
    svc.audit_log = AuditLog(str(STORAGE_AUDIT_LOG))

    # Session manager
    svc.session_mgr = SessionManager()

    # Auth
    svc.auth = AetherCloudAuth(
        audit_log=svc.audit_log,
        session_manager=svc.session_mgr,
    )

    # Vault
    vault_root = str(DEFAULT_VAULT_ROOT)
    os.makedirs(vault_root, exist_ok=True)
    svc.vault = AetherVault(
        vault_root=vault_root,
        session_token="server_init",
        audit_log=svc.audit_log,
    )

    # Watcher
    svc.watcher = VaultWatcher(
        vault_root=vault_root,
        audit_log=svc.audit_log,
    )
    try:
        svc.watcher.start()
    except Exception as e:
        log.warning("Vault watcher failed to start: %s", e)

    # Read Detector (st_atime polling)
    svc.read_detector = ReadDetector(
        vault_root=vault_root,
        audit_log=svc.audit_log,
    )
    try:
        svc.read_detector.start()
    except Exception as e:
        log.warning("Read detector failed to start: %s", e)

    # Agent
    svc.agent = AetherFileAgent(vault=svc.vault)

    # Task scheduler
    svc.scheduler = TaskScheduler()
    svc.scheduler.start()

    # Migrate any legacy config/scheduled_tasks.json into dev user's store
    legacy_tasks = load_task_store()
    if legacy_tasks:
        dev_store = _get_task_store("ZO")
        dev_store.update(legacy_tasks)
        _save_task_store("ZO")
        log.info("Migrated %d legacy tasks to user ZO", len(legacy_tasks))

    # Load all user task stores and schedule enabled tasks
    total_tasks = 0
    users_dir = Path("data") / "users"
    if users_dir.exists():
        for user_dir in users_dir.iterdir():
            if user_dir.is_dir():
                uname = user_dir.name
                store = _get_task_store(uname)
                for task in store.values():
                    if task.get("enabled", True):
                        svc.scheduler.add_task(task)
                total_tasks += len(store)
    log.info("Loaded %d scheduled tasks across all users", total_tasks)

    # Dev user — password is bcrypt-hashed on registration, never stored in plaintext
    _dev_pass = get_dev_key()
    if svc.auth.register_user("ZO", _dev_pass):
        log.info("Registered dev user: ZO")
    del _dev_pass  # scrub from memory immediately


# ═══════════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialize services on startup, cleanup on shutdown."""
    _init_services()
    yield

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Quantum-Secured AI File Intelligence API",
    lifespan=lifespan,
)

# CORS: allow Electron renderer (file://), localhost, and VPS origins
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(file://|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?|http://143\.198\.162\.111(:\d+)?|http://198\.211\.115\.41(:\d+)?)$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# ═══════════════════════════════════════════════════
# AUTH DEPENDENCY
# ═══════════════════════════════════════════════════
def get_session_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Extract and validate session token from Authorization header."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    token = credentials.credentials
    if not svc.session_mgr or not svc.session_mgr.is_valid(token):
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    return token


def get_username_from_token(token: str) -> str:
    """Resolve username from active session token."""
    username = svc.session_mgr.get_username(token)
    if not username:
        raise HTTPException(status_code=401, detail="Cannot resolve user from token")
    return username


# ═══════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ═══════════════════════════════════════════════════
class SetupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    authenticated: bool
    session_token: Optional[str] = None
    commitment_hash: Optional[str] = None
    timestamp: str
    reason: Optional[str] = None


class LogoutRequest(BaseModel):
    session_token: str


class LogoutResponse(BaseModel):
    success: bool
    audit_id: Optional[str] = None


class ChatRequest(BaseModel):
    query: str
    vault_context: Optional[dict] = None


class ChatResponse(BaseModel):
    response: str
    commitment_hash: Optional[str] = None
    verified: bool = False
    threat_level: str = "NONE"


class AnalyzeRequest(BaseModel):
    filename: str
    extension: str
    directory: str


class AnalyzeResponse(BaseModel):
    suggested_name: str
    category: str
    confidence: float
    commitment_hash: Optional[str] = None
    reasoning: Optional[str] = None


class ScanResponse(BaseModel):
    threat_level: str
    findings: list
    recommended_action: str
    commitment_hash: Optional[str] = None


class AuditEntry(BaseModel):
    timestamp: Optional[str] = None
    phase: Optional[str] = None
    order_id: Optional[str] = None
    event_type: Optional[str] = None
    data: Optional[dict] = None


class AuditTrailResponse(BaseModel):
    entries: list


class VaultListResponse(BaseModel):
    folders: list
    stats: dict


class VaultScanRequest(BaseModel):
    vault_path: str


class ContextRequest(BaseModel):
    context: str


class StatusResponse(BaseModel):
    protocol_l: str
    watcher: str
    agent: str
    read_detector: str = "INACTIVE"
    session_active: bool
    vault_root: str
    ibm_status: str
    uptime: float
    version: str
    needs_setup: bool = False


# ── Scheduled Task Models ────────────────────────
class TaskCreateRequest(BaseModel):
    name: str
    natural_language: str
    schedule_cron: Optional[str] = None
    schedule_label: Optional[str] = None
    agent_type: str = "custom"
    mcp_servers: Optional[list] = []
    enabled: bool = True


class TaskResponse(BaseModel):
    task_id: str
    name: str
    natural_language: str
    schedule_cron: str
    schedule_label: str
    agent_type: str
    enabled: bool
    created_at: str
    last_run: Optional[str] = None
    last_status: Optional[str] = None
    last_output_preview: Optional[str] = None
    next_run: Optional[str] = None
    run_count: int = 0
    qopc_score: float = 0.0


class TaskUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    schedule_cron: Optional[str] = None
    schedule_label: Optional[str] = None


class TaskRunResult(BaseModel):
    task_id: str
    status: str
    output_preview: str
    ran_at: str
    duration_ms: int


class TaskSignalRequest(BaseModel):
    signal_type: str        # "OPENED" | "USED" | "EDITED" | "IGNORED" | "DELETED"
    metadata: Optional[dict] = {}


class ProofExportRequest(BaseModel):
    entry_ids: list[str]   # list of order_ids to include
    label: Optional[str] = None


class ProofExportResponse(BaseModel):
    filename: str
    entry_count: int
    commitment_hash: str
    created_at: str


# ═══════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════

# ── Auth ──────────────────────────────────────────
@app.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """Authenticate user and return quantum-seeded session token."""
    if not svc.auth:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    result = svc.auth.login(req.username, req.password)

    return LoginResponse(
        authenticated=result.get("authenticated", False),
        session_token=result.get("session_token"),
        commitment_hash=result.get("commitment_hash") or result.get("audit_id"),
        timestamp=result.get("timestamp", datetime.now().isoformat()),
        reason=result.get("reason"),
    )


@app.post("/auth/logout", response_model=LogoutResponse)
async def logout(req: LogoutRequest):
    """Terminate session and log event."""
    if not svc.auth:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    result = svc.auth.logout(req.session_token)
    return LogoutResponse(
        success=result.get("success", True),
        audit_id=result.get("audit_id"),
    )


@app.post("/auth/setup")
async def setup_first_user(request: SetupRequest):
    """Create initial admin user. Only works once."""
    if not svc.auth:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    # Check if non-dev users already exist
    creds_file = STORAGE_CREDENTIALS_FILE
    if creds_file.exists():
        try:
            existing = json.loads(creds_file.read_text())
            # Allow setup if only the dev user (ZO) exists
            non_dev_users = [u for u in existing if u != "ZO"]
            if non_dev_users:
                raise HTTPException(
                    status_code=403,
                    detail="Setup already complete — admin user exists",
                )
        except (json.JSONDecodeError, ValueError):
            pass

    success = svc.auth.register_user(request.username, request.password)
    if not success:
        raise HTTPException(
            status_code=409,
            detail=f"User '{request.username}' already exists",
        )

    log.info("Setup: created admin user '%s'", request.username)
    return {
        "success": True,
        "username": request.username,
        "message": "Admin user created successfully",
    }


# ── Vault ─────────────────────────────────────────
@app.get("/vault/list", response_model=VaultListResponse)
async def vault_list(token: str = Depends(get_session_token)):
    """List vault contents organized by folder."""
    if not svc.vault:
        raise HTTPException(status_code=503, detail="Vault not initialized")

    try:
        files = svc.vault.list_files(recursive=True)
    except Exception as e:
        log.warning("vault.list_files failed: %s", e)
        files = []

    # Organize files into folders (single pass — folders contain file refs)
    folder_map: dict[str, dict] = {}

    for f in files:
        file_path = Path(f.get("path", f.get("name", "")))
        parent = str(file_path.parent) if file_path.parent != Path(".") else "root"

        file_entry = {
            "name": f.get("name", file_path.name),
            "path": str(file_path),
            "size": f.get("size", 0),
            "size_display": _format_size(f.get("size", 0)),
            "extension": f.get("extension", file_path.suffix),
            "modified": f.get("modified", ""),
            "category": f.get("category", _guess_category(file_path.suffix)),
            "icon": _file_icon(file_path.suffix),
            "content_hash": f.get("content_hash", ""),
        }

        if parent not in folder_map:
            folder_map[parent] = {
                "id": parent.replace("/", "_").replace("\\", "_"),
                "name": parent,
                "icon": "📁",
                "files": [],
            }
        folder_map[parent]["files"].append(file_entry)

    folders = []
    for folder in folder_map.values():
        folder["count"] = len(folder["files"])
        folders.append(folder)

    try:
        stats = svc.vault.get_stats()
    except Exception as e:
        log.warning("vault.get_stats failed: %s", e)
        stats = {"vault_root": str(DEFAULT_VAULT_ROOT)}

    stats["file_count"] = sum(f["count"] for f in folders)
    stats["folder_count"] = len(folders)

    return VaultListResponse(folders=folders, stats=stats)


# ── Agent ─────────────────────────────────────────
@app.post("/agent/chat", response_model=ChatResponse)
async def agent_chat(req: ChatRequest, token: str = Depends(get_session_token)):
    """Chat with the AI agent. Response is Protocol-L committed."""
    if not svc.agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        # If frontend sent vault context, inject it into the query
        query = req.query
        if req.vault_context:
            vc = req.vault_context
            ctx_lines = [f"\n\n[VAULT CONTEXT — {vc.get('file_count', 0)} items, {vc.get('folder_count', 0)} folders]"]
            for f in (vc.get('files') or [])[:50]:
                name = f.get('name', '?')
                size = f.get('size', '')
                ext = f.get('extension', '')
                cat = f.get('category', '')
                ctx_lines.append(f"  {name}  {size}  {ext}  {cat}")
            ctx_lines.append("[END VAULT CONTEXT]")
            query = query + '\n'.join(ctx_lines)

        response_text = svc.agent.chat(query)
    except Exception as e:
        log.warning("agent.chat failed: %s", e)
        response_text = f"Agent error: {str(e)}"

    verified = hasattr(svc.agent, 'is_hardened') and svc.agent.is_hardened

    return ChatResponse(
        response=response_text,
        commitment_hash=_commitment_hash(response_text),
        verified=verified,
        threat_level="NONE",  # Threat assessment via /agent/scan, not text parsing
    )


@app.post("/agent/analyze", response_model=AnalyzeResponse)
async def agent_analyze(req: AnalyzeRequest, token: str = Depends(get_session_token)):
    """Analyze a file and suggest renaming."""
    if not svc.agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        result = svc.agent.analyze_file(req.filename)
    except Exception as e:
        log.warning("agent.analyze_file failed: %s", e)
        result = {
            "suggested_name": req.filename,
            "category": _guess_category(req.extension),
            "confidence": 0.5,
            "reasoning": "Rule-based fallback analysis",
        }

    return AnalyzeResponse(
        suggested_name=result.get("suggested_name", req.filename),
        category=result.get("category", "UNKNOWN"),
        confidence=result.get("confidence", 0.5),
        commitment_hash=_commitment_hash(result),
        reasoning=result.get("reasoning"),
    )


@app.post("/agent/scan", response_model=ScanResponse)
async def agent_scan(token: str = Depends(get_session_token)):
    """Run security scan on vault."""
    if not svc.agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        result = svc.agent.security_scan()
    except Exception as e:
        log.warning("agent.security_scan failed: %s", e)
        result = {
            "threat_level": "UNKNOWN",
            "findings": [],
            "recommended_action": "Manual review recommended",
        }

    return ScanResponse(
        threat_level=result.get("threat_level", "NONE"),
        findings=result.get("findings", []),
        recommended_action=result.get("recommended_action", "No action required"),
        commitment_hash=_commitment_hash(result),
    )


@app.post("/agent/context")
async def set_agent_context(
    request: ContextRequest,
    token: str = Depends(get_session_token),
):
    """Store user context preferences. Injected into every agent call."""
    session_context[token] = request.context

    # Update the agent's context scorer
    if svc.agent and svc.agent._claude_available and svc.agent._claude_agent:
        try:
            svc.agent._claude_agent.set_user_context(request.context)
        except Exception as e:
            log.warning("Failed to set agent context: %s", e)

    from agent.qopc_feedback import UserContextScorer
    scorer = UserContextScorer(request.context)

    return {
        "stored": True,
        "context_length": len(request.context),
        "signals_detected": scorer.active_signals,
    }


@app.get("/agent/context")
async def get_agent_context(token: str = Depends(get_session_token)):
    """Get current user context."""
    ctx = session_context.get(token, "")
    return {
        "context": ctx,
        "has_context": bool(ctx.strip()),
    }


# ── MCP Agent ─────────────────────────────────────
class MCPAgentRequest(BaseModel):
    query: str
    mcp_servers: Optional[list] = []
    vault_context: Optional[dict] = None
    max_tokens: int = 2000
    conversation_history: Optional[list] = []


class MCPAgentResponse(BaseModel):
    response: str
    tools_used: list = []
    commitment_hash: Optional[str] = None
    verified: bool = False


def _build_mcp_system_prompt(vault_context: Optional[dict], username: str) -> str:
    base = (
        f"You are AetherCloud's autonomous agent for {username}.\n\n"
        "You have access to external tools via MCP servers. Use them proactively.\n\n"
        "RULES:\n"
        "1. When asked about emails — USE the Gmail tool to actually read them. "
        "Never say you cannot access email.\n"
        "2. When asked about calendar — USE the calendar tool to check actual events.\n"
        "3. When you have vault context — use the file manifest to propose specific operations.\n"
        "4. Always complete the full task autonomously before responding.\n"
        "5. Format your response cleanly — the user sees your final output, not your tool calls.\n"
        "6. After using tools, summarize what you found and what you did or propose to do.\n"
        "7. Format rename proposals as: `old_filename` → `new_filename`\n"
    )

    if vault_context and vault_context.get("files"):
        file_lines = "\n".join(
            f"- {f['name']} ({f.get('size', '?')}) [{f.get('category', '?')}]"
            for f in vault_context["files"][:50]
        )
        base += (
            f"\nVAULT CONTENTS ({vault_context.get('file_count', 0)} files):\n"
            f"{file_lines}\n\n"
            "Use these exact filenames when proposing file operations.\n"
        )

    return base


@app.post("/agent/mcp-chat", response_model=MCPAgentResponse)
async def agent_mcp_chat(
    req: MCPAgentRequest,
    token: str = Depends(get_session_token),
):
    """
    MCP-enabled agent endpoint. Attaches MCP servers to Claude API call
    so Claude can autonomously use external tools (Gmail, Calendar, etc.).
    """
    import httpx
    from agent.mcp_registry import detect_required_servers

    api_key = get_anthropic_key()
    username = get_username_from_token(token)

    system = _build_mcp_system_prompt(req.vault_context, username)

    messages = list(req.conversation_history or [])
    messages.append({"role": "user", "content": req.query})

    payload = {
        "model": os.environ.get("AETHER_AGENT_MODEL", "claude-sonnet-4-20250514"),
        "max_tokens": req.max_tokens,
        "system": system,
        "messages": messages,
    }

    # Auto-detect MCP servers from query if none explicitly provided
    mcp_servers = req.mcp_servers or detect_required_servers(req.query)
    if mcp_servers:
        payload["mcp_servers"] = mcp_servers

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if mcp_servers:
        headers["anthropic-beta"] = "mcp-client-2025-04-04"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning("MCP agent call failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Agent error: {str(e)}")

    # Extract text and tool use from response content blocks
    response_text = ""
    tools_used = []
    for block in data.get("content", []):
        btype = block.get("type", "")
        if btype == "text":
            response_text += block.get("text", "")
        elif btype in ("tool_use", "mcp_tool_use"):
            tools_used.append(block.get("name", "unknown"))

    commitment_hash = _commitment_hash(response_text)

    # Audit log
    if svc.audit_log:
        try:
            svc.audit_log.append_commitment(
                order_id=f"mcp_chat_{int(time.time())}",
                trade_details={
                    "event_type": "MCP_CHAT",
                    "username": username,
                    "query_hash": hashlib.sha256(req.query.encode()).hexdigest()[:16],
                    "tools_used": tools_used,
                    "mcp_servers": [s.get("name") for s in mcp_servers],
                },
                commitment_hash=commitment_hash,
            )
        except Exception:
            pass

    return MCPAgentResponse(
        response=response_text,
        tools_used=tools_used,
        commitment_hash=commitment_hash,
        verified=True,
    )


# ── Audit ─────────────────────────────────────────
@app.get("/audit/trail", response_model=AuditTrailResponse)
async def audit_trail(
    token: str = Depends(get_session_token),
    limit: int = Query(default=50, ge=1, le=500),
    path: Optional[str] = Query(default=None),
):
    """Retrieve audit trail entries."""
    if not svc.audit_log:
        raise HTTPException(status_code=503, detail="Audit log not initialized")

    # Over-fetch when filtering by path so we can still return `limit` results
    fetch_limit = limit * 3 if path else limit

    try:
        raw_entries = svc.audit_log.query(limit=fetch_limit)
    except Exception as e:
        log.warning("audit_log.query failed: %s", e)
        raw_entries = []

    entries = []
    for entry in raw_entries:
        data = entry if isinstance(entry, dict) else {}
        e = {
            "timestamp": data.get("timestamp", ""),
            "phase": data.get("phase", data.get("record_type", "")),
            "order_id": data.get("order_id", ""),
            "event_type": data.get("event_type", data.get("phase", "")),
            "data": data.get("data", {}),
        }
        if path:
            entry_path = str(data.get("data", {}).get("path", ""))
            if path.lower() not in entry_path.lower():
                continue
        entries.append(e)
        if len(entries) >= limit:
            break

    return AuditTrailResponse(entries=entries)


@app.get("/audit/trail/live")
async def audit_trail_live(
    token: str = Depends(get_session_token),
    since: Optional[float] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    event_type: Optional[str] = Query(default=None),
):
    """Live audit trail with filtering — powers the LOGS tab."""
    if not svc.audit_log:
        raise HTTPException(status_code=503, detail="Audit log not initialized")

    try:
        raw = svc.audit_log.query(since=since, limit=limit * 2)
    except Exception as e:
        log.warning("audit_log.query failed: %s", e)
        raw = []

    entries = []
    for r in raw:
        data = r if isinstance(r, dict) else {}
        trade = data.get("data", {}).get("trade_details", data.get("data", {}))
        evt = trade.get("event_type", data.get("phase", "UNKNOWN"))

        if event_type and event_type.upper() != evt.upper():
            continue

        entries.append({
            "timestamp": data.get("timestamp", 0),
            "phase": data.get("phase", ""),
            "order_id": data.get("order_id", ""),
            "event_type": evt,
            "path": trade.get("path", ""),
            "source": trade.get("source", ""),
            "severity": trade.get("severity", ""),
            "commitment_hash": data.get("signature", {}).get("commitment_hash", ""),
            "data": trade,
        })
        if len(entries) >= limit:
            break

    return {"entries": entries, "count": len(entries)}


@app.post("/audit/export-proof")
async def export_proof(
    req: ProofExportRequest,
    token: str = Depends(get_session_token),
):
    """Export a cryptographic proof package for selected audit entries."""
    if not svc.audit_log:
        raise HTTPException(status_code=503, detail="Audit log not initialized")

    username = get_username_from_token(token)

    # Collect entries by order_id
    proof_entries = []
    for oid in req.entry_ids:
        try:
            results = svc.audit_log.read_by_order_id(oid)
            for entry in results:
                proof_entries.append(entry.to_json())
        except Exception:
            pass

    if not proof_entries:
        raise HTTPException(status_code=404, detail="No matching audit entries found")

    # Build proof package
    package = {
        "proof_package_version": "1.0",
        "generated_by": "AetherCloud-L",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generated_for": username,
        "label": req.label or f"Proof export ({len(proof_entries)} entries)",
        "entry_count": len(proof_entries),
        "entries": proof_entries,
    }

    # Commitment hash over entire package
    package_hash = hashlib.sha256(
        json.dumps(package, sort_keys=True, default=str).encode()
    ).hexdigest()
    package["package_commitment_hash"] = package_hash

    # Save to exports directory
    from config.storage import CRYPTO_ROOT
    exports_dir = CRYPTO_ROOT / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"proof_{ts}_{package_hash[:8]}.json"
    filepath = exports_dir / filename
    filepath.write_text(json.dumps(package, indent=2, default=str))

    # Log the export itself as an audit event
    seed = os.urandom(32)
    seed_hash = hashlib.sha256(seed).hexdigest()
    now = int(time.time())
    from aether_protocol.quantum_crypto import QuantumSeedCommitment
    seed_commitment = QuantumSeedCommitment(seed_hash, now, "OS_URANDOM", now, now + 3600)

    export_audit = {
        "order_id": f"proof_export_{package_hash[:12]}",
        "trade_details": {
            "event_type": "PROOF_EXPORT",
            "username": username,
            "filename": filename,
            "entry_count": len(proof_entries),
            "package_hash": package_hash,
            "timestamp": time.time(),
        },
        "quantum_seed_commitment": seed_commitment.seed_hash,
        "seed_measurement_method": "OS_URANDOM",
        "timestamp": time.time(),
    }
    try:
        svc.audit_log.append_commitment(export_audit, {"commitment_hash": package_hash})
    except Exception:
        pass

    return ProofExportResponse(
        filename=filename,
        entry_count=len(proof_entries),
        commitment_hash=package_hash,
        created_at=package["generated_at"],
    )


@app.get("/audit/exports")
async def list_exports(token: str = Depends(get_session_token)):
    """List all proof export packages."""
    from config.storage import CRYPTO_ROOT
    exports_dir = CRYPTO_ROOT / "exports"

    exports = []
    if exports_dir.exists():
        for f in sorted(exports_dir.glob("proof_*.json"), reverse=True):
            try:
                pkg = json.loads(f.read_text())
                exports.append({
                    "filename": f.name,
                    "label": pkg.get("label", ""),
                    "entry_count": pkg.get("entry_count", 0),
                    "generated_at": pkg.get("generated_at", ""),
                    "package_hash": pkg.get("package_commitment_hash", ""),
                })
            except Exception:
                continue

    return {"exports": exports[:50]}


@app.get("/audit/download/{filename}")
async def download_proof(filename: str, token: str = Depends(get_session_token)):
    """Download a proof package JSON file."""
    from config.storage import CRYPTO_ROOT
    filepath = CRYPTO_ROOT / "exports" / filename

    if not filepath.exists() or not filepath.name.startswith("proof_"):
        raise HTTPException(status_code=404, detail="Proof package not found")

    try:
        content = json.loads(filepath.read_text())
        return content
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to read proof package")


# ── Scan (POST — structured vault scan, no auth) ──
@app.post("/vault/scan")
async def scan_vault(request: VaultScanRequest):
    """
    Scan a real filesystem path and return structured vault data.
    No auth required (same as /vault/browse) so it works during initial setup.
    """
    vault_path = request.vault_path
    path = Path(vault_path)

    if not path.exists():
        raise HTTPException(status_code=404, detail="Vault path does not exist")
    if not path.is_dir():
        raise HTTPException(status_code=400, detail="Vault path must be a directory")

    folders = []
    root_files = []
    total_files = 0

    try:
        for item in sorted(path.iterdir()):
            if item.name.startswith('.') or item.name.startswith('$'):
                continue

            if item.is_dir():
                folder_files = []
                try:
                    for f in sorted(item.iterdir()):
                        if f.name.startswith('.') or f.name.startswith('$'):
                            continue
                        if f.is_file():
                            try:
                                st = f.stat()
                                folder_files.append({
                                    "name": f.name,
                                    "extension": f.suffix,
                                    "size": _format_size(st.st_size),
                                    "size_bytes": st.st_size,
                                    "modified": st.st_mtime,
                                    "icon": _file_icon(f.suffix),
                                    "category": _get_category_by_name(f.name, f.suffix),
                                    "path": str(f),
                                })
                                total_files += 1
                            except (PermissionError, OSError):
                                pass
                except PermissionError:
                    pass

                folders.append({
                    "id": item.name.lower().replace(' ', '_'),
                    "name": item.name,
                    "path": str(item),
                    "count": len(folder_files),
                    "file_count": len(folder_files),
                    "files": folder_files[:8],
                    "icon": _get_folder_icon(item.name),
                    "modified": item.stat().st_mtime,
                })

            elif item.is_file():
                try:
                    st = item.stat()
                    root_files.append({
                        "name": item.name,
                        "extension": item.suffix,
                        "size": _format_size(st.st_size),
                        "size_bytes": st.st_size,
                        "icon": _file_icon(item.suffix),
                        "category": _get_category_by_name(item.name, item.suffix),
                        "path": str(item),
                    })
                    total_files += 1
                except (PermissionError, OSError):
                    pass

    except PermissionError as e:
        raise HTTPException(status_code=403, detail=f"Permission denied: {e}")

    # Cap folders at 12 for visual clarity
    folders = sorted(folders, key=lambda f: f["name"])[:12]

    if root_files:
        folders.insert(0, {
            "id": "_root_files",
            "name": "root files",
            "path": str(path),
            "count": len(root_files),
            "file_count": len(root_files),
            "files": root_files[:8],
            "icon": "📄",
            "modified": path.stat().st_mtime,
        })

    return {
        "vault_path": str(path),
        "vault_name": path.name,
        "folder_count": len(folders),
        "file_count": total_files,
        "folders": folders,
        "scanned_at": datetime.now().isoformat(),
    }


# ── Browse (scan any directory — no auth, localhost only) ──
@app.get("/vault/browse")
async def vault_browse(
    path: str = Query(default=None, description="Directory path to scan"),
):
    """
    Scan a directory and return its structure for the vault graph.
    Only names, sizes, extensions, modified dates — no file contents.
    """
    vault_root = path or os.getenv("AETHER_VAULT_ROOT", str(DEFAULT_VAULT_ROOT))
    vault_path = Path(vault_root)

    if not vault_path.exists():
        return {"error": "Path does not exist", "folders": [], "files": [],
                "stats": {"total_files": 0, "total_folders": 0}}
    if not vault_path.is_dir():
        return {"error": "Path is not a directory", "folders": [], "files": [],
                "stats": {"total_files": 0, "total_folders": 0}}

    folders = []
    files = []

    try:
        for item in vault_path.iterdir():
            if item.name.startswith(".") or item.name.startswith("$"):
                continue
            try:
                stat = item.stat()
                modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")

                if item.is_dir():
                    try:
                        file_count = sum(1 for f in item.iterdir() if not f.name.startswith("."))
                    except PermissionError:
                        file_count = 0
                    folders.append({
                        "id": item.name.lower().replace(" ", "_"),
                        "name": item.name,
                        "path": str(item),
                        "file_count": file_count,
                        "modified": modified,
                        "icon": _get_folder_icon(item.name),
                    })
                elif item.is_file():
                    ext = item.suffix.lower()
                    files.append({
                        "name": item.name,
                        "path": str(item),
                        "size": _format_size(stat.st_size),
                        "size_bytes": stat.st_size,
                        "extension": ext,
                        "category": _get_category_by_name(item.name, ext),
                        "modified": modified,
                        "icon": _file_icon(ext),
                    })
            except PermissionError:
                continue
            except Exception:
                continue
    except PermissionError:
        return {"error": "Permission denied", "folders": [], "files": [],
                "stats": {"total_files": 0, "total_folders": 0}}

    folders.sort(key=lambda x: x["name"].lower())
    files.sort(key=lambda x: x["size_bytes"], reverse=True)

    display_folders = folders[:12]
    display_files = files[:8]

    return {
        "vault_root": vault_root,
        "folders": display_folders,
        "files": display_files,
        "stats": {
            "total_files": len(files),
            "total_folders": len(folders),
            "displayed_folders": len(display_folders),
            "displayed_files": len(display_files),
        },
    }


# ── Scheduled Tasks ───────────────────────────────
@app.post("/tasks/create", response_model=TaskResponse)
async def create_task(req: TaskCreateRequest, token: str = Depends(get_session_token)):
    """Create a new scheduled task."""
    username = get_username_from_token(token)
    task_id = str(uuid.uuid4())

    # Auto-parse schedule from natural language if not provided
    cron_expr = req.schedule_cron
    cron_label = req.schedule_label
    if not cron_expr:
        cron_expr, cron_label = parse_schedule(req.natural_language)
    if not cron_label:
        _, cron_label = parse_schedule(req.natural_language)

    task = {
        "task_id": task_id,
        "name": req.name,
        "natural_language": req.natural_language,
        "schedule_cron": cron_expr,
        "schedule_label": cron_label,
        "agent_type": req.agent_type,
        "mcp_servers": req.mcp_servers or [],
        "enabled": req.enabled,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "last_run": None,
        "last_status": None,
        "last_output_preview": None,
        "run_count": 0,
        "_owner": username,
    }

    # Inject user context if available
    ctx = session_context.get(token, "")
    if ctx:
        task["_user_context"] = ctx

    store = _get_task_store(username)
    store[task_id] = task
    _save_task_store(username)

    # Schedule it
    if svc.scheduler and req.enabled:
        svc.scheduler.add_task(task)

    # Get next run
    next_run = None
    if svc.scheduler:
        next_run = svc.scheduler.get_next_run(task_id)

    return TaskResponse(
        task_id=task_id,
        name=req.name,
        natural_language=req.natural_language,
        schedule_cron=cron_expr,
        schedule_label=cron_label,
        agent_type=req.agent_type,
        enabled=req.enabled,
        created_at=task["created_at"],
        next_run=next_run,
    )


@app.get("/tasks/list")
async def list_tasks(token: str = Depends(get_session_token)):
    """List all scheduled tasks with current status."""
    username = get_username_from_token(token)
    store = _get_task_store(username)
    qopc = _get_task_qopc(username)

    tasks = []
    for task in store.values():
        tid = task["task_id"]
        next_run = None
        if svc.scheduler:
            next_run = svc.scheduler.get_next_run(tid)

        qscore = qopc.get_score(tid)

        tasks.append(TaskResponse(
            task_id=tid,
            name=task["name"],
            natural_language=task.get("natural_language", ""),
            schedule_cron=task.get("schedule_cron", "0 9 * * *"),
            schedule_label=task.get("schedule_label", "Daily 9:00 AM"),
            agent_type=task.get("agent_type", "custom"),
            enabled=task.get("enabled", True),
            created_at=task.get("created_at", ""),
            last_run=task.get("last_run"),
            last_status=task.get("last_status"),
            last_output_preview=task.get("last_output_preview"),
            next_run=next_run,
            run_count=task.get("run_count", 0),
            qopc_score=qscore,
        ))

    return tasks


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str, token: str = Depends(get_session_token)):
    """Delete a scheduled task."""
    username = get_username_from_token(token)
    store = _get_task_store(username)

    if task_id not in store:
        raise HTTPException(status_code=404, detail="Task not found")

    if svc.scheduler:
        svc.scheduler.remove_task(task_id)

    del store[task_id]
    _save_task_store(username)

    return {"deleted": True, "task_id": task_id}


@app.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, req: TaskUpdateRequest, token: str = Depends(get_session_token)):
    """Update task enabled state or schedule."""
    username = get_username_from_token(token)
    store = _get_task_store(username)

    if task_id not in store:
        raise HTTPException(status_code=404, detail="Task not found")

    task = store[task_id]

    if req.enabled is not None:
        old_enabled = task.get("enabled", True)
        task["enabled"] = req.enabled
        if svc.scheduler:
            if req.enabled and not old_enabled:
                svc.scheduler.add_task(task)
            elif not req.enabled and old_enabled:
                svc.scheduler.pause_task(task_id)

    if req.schedule_cron is not None:
        task["schedule_cron"] = req.schedule_cron
        if req.schedule_label:
            task["schedule_label"] = req.schedule_label
        # Reschedule
        if svc.scheduler and task.get("enabled", True):
            svc.scheduler.remove_task(task_id)
            svc.scheduler.add_task(task)

    _save_task_store(username)

    next_run = None
    if svc.scheduler:
        next_run = svc.scheduler.get_next_run(task_id)

    return TaskResponse(
        task_id=task["task_id"],
        name=task["name"],
        natural_language=task.get("natural_language", ""),
        schedule_cron=task.get("schedule_cron", ""),
        schedule_label=task.get("schedule_label", ""),
        agent_type=task.get("agent_type", "custom"),
        enabled=task.get("enabled", True),
        created_at=task.get("created_at", ""),
        last_run=task.get("last_run"),
        last_status=task.get("last_status"),
        last_output_preview=task.get("last_output_preview"),
        next_run=next_run,
        run_count=task.get("run_count", 0),
    )


@app.post("/tasks/{task_id}/run", response_model=TaskRunResult)
async def run_task(task_id: str, token: str = Depends(get_session_token)):
    """Manually trigger a task immediately."""
    username = get_username_from_token(token)
    store = _get_task_store(username)
    qopc = _get_task_qopc(username)

    if task_id not in store:
        raise HTTPException(status_code=404, detail="Task not found")

    task = store[task_id]

    # Inject user context from session
    ctx = session_context.get(token, "")
    if ctx:
        task["_user_context"] = ctx

    # QOPC prompt injection — prepend learned context to natural_language
    prompt_injection = qopc.get_prompt_injection(task_id)
    if prompt_injection:
        task["_qopc_injection"] = prompt_injection

    result = execute_task(task)

    # Update store
    task["last_run"] = result["ran_at"]
    task["last_status"] = result["status"]
    task["last_output_preview"] = result["output_preview"]
    task["run_count"] = task.get("run_count", 0) + 1
    _save_task_store(username)

    # Record MANUAL_RUN signal
    qopc.record_signal(TaskSignal(
        task_id=task_id,
        signal_type="MANUAL_RUN",
        timestamp=datetime.utcnow().isoformat() + "Z",
        metadata={
            "duration_ms": result.get("duration_ms", 0),
            "output_length": len(result.get("output_preview", "")),
        },
    ))

    return TaskRunResult(**result)


@app.get("/tasks/{task_id}/history")
async def task_history(task_id: str, token: str = Depends(get_session_token)):
    """Get last 20 run results for a task."""
    username = get_username_from_token(token)
    store = _get_task_store(username)

    if task_id not in store:
        raise HTTPException(status_code=404, detail="Task not found")

    history_path = user_task_history(username, task_id)
    if history_path.exists():
        try:
            return json.loads(history_path.read_text())
        except Exception:
            return []
    return []


@app.post("/tasks/{task_id}/signal")
async def record_task_signal(task_id: str, req: TaskSignalRequest, token: str = Depends(get_session_token)):
    """Record a QOPC signal for a task and return updated score + recommendations."""
    username = get_username_from_token(token)
    store = _get_task_store(username)
    qopc = _get_task_qopc(username)

    if task_id not in store:
        raise HTTPException(status_code=404, detail="Task not found")

    qopc.record_signal(TaskSignal(
        task_id=task_id,
        signal_type=req.signal_type,
        timestamp=datetime.utcnow().isoformat() + "Z",
        metadata=req.metadata or {},
    ))

    score = qopc.get_score(task_id)
    recs = qopc.get_recommendations(task_id)

    return {
        "recorded": True,
        "qopc_score": score,
        "recommendations": recs,
        "insights": recs.get("insights", []),
    }


@app.get("/tasks/{task_id}/qopc")
async def get_task_qopc(task_id: str, token: str = Depends(get_session_token)):
    """Return full QOPC state for a task."""
    username = get_username_from_token(token)
    store = _get_task_store(username)
    qopc = _get_task_qopc(username)

    if task_id not in store:
        raise HTTPException(status_code=404, detail="Task not found")

    score = qopc.get_score(task_id)
    count = qopc.get_signal_count(task_id)
    recs = qopc.get_recommendations(task_id)
    injection = qopc.get_prompt_injection(task_id)
    history = qopc.get_last_signals(task_id, 20)

    return {
        "task_id": task_id,
        "qopc_score": score,
        "signal_count": count,
        "recommendations": recs,
        "insights": recs.get("insights", []),
        "prompt_injection": injection,
        "signal_history": history,
    }


# ── Status ────────────────────────────────────────
@app.get("/status", response_model=StatusResponse)
async def status():
    """System health check — no auth required."""
    watcher_status = "INACTIVE"
    if svc.watcher:
        try:
            watcher_status = "ACTIVE" if svc.watcher.is_running else "STANDBY"
        except Exception:
            watcher_status = "STANDBY"

    agent_status = "UNAVAILABLE"
    if svc.agent:
        agent_status = "HARDENED" if (
            hasattr(svc.agent, "is_hardened") and svc.agent.is_hardened
        ) else "ACTIVE"

    read_detector_status = "INACTIVE"
    if svc.read_detector:
        try:
            read_detector_status = "ACTIVE" if svc.read_detector.is_running else "STANDBY"
        except Exception:
            read_detector_status = "STANDBY"

    session_active = bool(svc.session_mgr and svc.session_mgr.active_count > 0)

    # IBM Quantum / CSPRNG status — cached with 30s TTL
    now = time.time()
    if now > _ibm_status_cache["expires"]:
        if _PROTOCOL_VARIANT == "C":
            _ibm_status_cache["value"] = "CSPRNG"
        else:
            try:
                from aether_protocol.quantum_crypto import get_quantum_seed
                _, method = get_quantum_seed()
                _ibm_status_cache["value"] = method
            except Exception:
                _ibm_status_cache["value"] = "OS_URANDOM"
        _ibm_status_cache["expires"] = now + 30.0

    # Check if setup is needed (no credentials file or only dev user)
    creds_path = STORAGE_CREDENTIALS_FILE
    needs_setup = True
    if creds_path.exists():
        try:
            _creds = json.loads(creds_path.read_text())
            non_dev = [u for u in _creds if u != "ZO"]
            needs_setup = len(non_dev) == 0
        except Exception:
            needs_setup = True

    return StatusResponse(
        protocol_l="ACTIVE",
        watcher=watcher_status,
        agent=agent_status,
        read_detector=read_detector_status,
        session_active=session_active,
        vault_root=str(DEFAULT_VAULT_ROOT),
        ibm_status=_ibm_status_cache["value"],
        uptime=round(time.time() - _start_time, 1),
        version=APP_VERSION,
        needs_setup=needs_setup,
    )


# ── Routing Diagnostics ──────────────────────────
@app.get("/routing-check")
async def routing_check():
    """
    No auth required. Returns routing info so Electron can verify
    it's hitting the right server (VPS1 proxy → VPS2 backend).
    """
    return {
        "server": "VPS2",
        "ip": "198.211.115.41",
        "port": int(os.environ.get("AETHER_BIND_PORT", 8080)),
        "protocol_l": "ACTIVE",
        "anthropic_key_set": bool(get_anthropic_key()),
        "ibm_token_set": bool(get_ibm_token()),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/auth/health")
async def auth_health():
    """
    No auth required. Returns auth system status.
    Used by Electron login screen to verify backend is auth-ready.
    """
    if not svc.auth or not svc.session_mgr:
        return {
            "ready": False,
            "reason": "Auth service not initialized",
        }

    # Check credentials file exists and has users
    has_users = False
    if STORAGE_CREDENTIALS_FILE.exists():
        try:
            creds = json.loads(STORAGE_CREDENTIALS_FILE.read_text())
            non_dev = [u for u in creds if u != "ZO"]
            has_users = len(non_dev) > 0
        except Exception:
            pass

    return {
        "ready": True,
        "has_users": has_users,
        "needs_setup": not has_users,
        "active_sessions": svc.session_mgr.active_count,
        "timestamp": datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════
def run_server():
    """Run the FastAPI server. Binds 0.0.0.0 on VPS, 127.0.0.1 locally."""
    host = os.environ.get("AETHER_BIND_HOST", "0.0.0.0")
    port = int(os.environ.get("AETHER_BIND_PORT", "8741"))
    uvicorn.run(
        "api_server:app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    run_server()
