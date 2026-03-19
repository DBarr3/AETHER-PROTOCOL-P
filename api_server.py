#!/usr/bin/env python3
"""
AetherCloud-L — FastAPI Server
REST API on localhost:8741 for the Electron desktop app.

Aether Systems LLC — Patent Pending
"""

import os
import sys
import time
import hashlib
from pathlib import Path
from typing import Optional
from datetime import datetime

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import uvicorn

from config.settings import (
    APP_NAME, APP_VERSION, DEFAULT_VAULT_ROOT, DEFAULT_AUDIT_DIR,
    HARDENED_AGENT_ENABLED, CLAUDE_API_KEY, CLAUDE_MODEL,
)
from auth.login import AetherCloudAuth
from auth.session import SessionManager
from vault.filebase import AetherVault
from vault.watcher import VaultWatcher
from agent.file_agent import AetherFileAgent
from aether_protocol.audit import AuditLog

# ═══════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════
_start_time = time.time()

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

# CORS: allow only localhost origins (Electron renderer)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8741",
        "http://127.0.0.1",
        "http://127.0.0.1:8741",
        "file://",
    ],
    allow_origin_regex=r"^(file://|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Shared state ──────────────────────────────────
_audit_log: Optional[AuditLog] = None
_auth: Optional[AetherCloudAuth] = None
_session_mgr: Optional[SessionManager] = None
_vault: Optional[AetherVault] = None
_watcher: Optional[VaultWatcher] = None
_agent: Optional[AetherFileAgent] = None

security = HTTPBearer(auto_error=False)


def _init_services():
    """Initialize all backend services."""
    global _audit_log, _auth, _session_mgr, _vault, _watcher, _agent

    # Audit log
    audit_dir = DEFAULT_AUDIT_DIR
    audit_dir.mkdir(parents=True, exist_ok=True)
    _audit_log = AuditLog(audit_dir / "aether_audit.jsonl")

    # Session manager
    _session_mgr = SessionManager()

    # Auth
    _auth = AetherCloudAuth(
        audit_log=_audit_log,
        session_manager=_session_mgr,
    )

    # Vault
    vault_root = str(DEFAULT_VAULT_ROOT)
    os.makedirs(vault_root, exist_ok=True)
    _vault = AetherVault(
        vault_root=vault_root,
        session_token="server_init",
        audit_log=_audit_log,
    )

    # Watcher
    _watcher = VaultWatcher(
        vault_root=vault_root,
        audit_log=_audit_log,
    )
    try:
        _watcher.start()
    except Exception:
        pass  # Watcher may fail if vault root doesn't exist yet

    # Agent
    _agent = AetherFileAgent(vault=_vault)


## Lifespan handles startup — see lifespan() above


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
    if not _session_mgr or not _session_mgr.is_valid(token):
        raise HTTPException(status_code=401, detail="Invalid or expired session token")
    return token


# ═══════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ═══════════════════════════════════════════════════
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
    files: list
    stats: dict


class StatusResponse(BaseModel):
    protocol_l: str
    watcher: str
    agent: str
    session_active: bool
    vault_root: str
    ibm_status: str
    uptime: float
    version: str


# ═══════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════

# ── Auth ──────────────────────────────────────────
@app.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """Authenticate user and return quantum-seeded session token."""
    if not _auth:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    result = _auth.login(req.username, req.password)

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
    if not _auth:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    result = _auth.logout(req.session_token)
    return LogoutResponse(
        success=result.get("success", True),
        audit_id=result.get("audit_id"),
    )


# ── Vault ─────────────────────────────────────────
@app.get("/vault/list", response_model=VaultListResponse)
async def vault_list(token: str = Depends(get_session_token)):
    """List vault contents organized by folder."""
    if not _vault:
        raise HTTPException(status_code=503, detail="Vault not initialized")

    try:
        files = _vault.list_files(recursive=True)
    except Exception:
        files = []

    # Organize files into folders
    folder_map = {}
    flat_files = []

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

        flat_files.append(file_entry)

        if parent not in folder_map:
            folder_map[parent] = {
                "id": parent.replace("/", "_").replace("\\", "_"),
                "name": parent,
                "icon": "📁",
                "files": [],
            }
        folder_map[parent]["files"].append(file_entry)

    folders = []
    for name, folder in folder_map.items():
        folder["count"] = len(folder["files"])
        folders.append(folder)

    try:
        stats = _vault.get_stats()
    except Exception:
        stats = {
            "file_count": len(flat_files),
            "folder_count": len(folders),
            "vault_root": str(DEFAULT_VAULT_ROOT),
        }

    stats["folder_count"] = len(folders)

    return VaultListResponse(
        folders=folders,
        files=flat_files,
        stats=stats,
    )


# ── Agent ─────────────────────────────────────────
@app.post("/agent/chat", response_model=ChatResponse)
async def agent_chat(req: ChatRequest, token: str = Depends(get_session_token)):
    """Chat with the AI agent. Response is Protocol-L committed."""
    if not _agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        response_text = _agent.chat(req.query)
    except Exception as e:
        response_text = f"Agent error: {str(e)}"

    # Compute commitment hash for the response
    commitment_hash = hashlib.sha256(response_text.encode()).hexdigest()[:16]

    # Check if response mentions threats
    threat_level = "NONE"
    lower = response_text.lower()
    if any(w in lower for w in ["threat", "unauthorized", "intrusion", "alert"]):
        threat_level = "LOW"
    if any(w in lower for w in ["critical", "breach", "compromised"]):
        threat_level = "HIGH"

    # Check verification status
    verified = False
    if hasattr(_agent, 'is_hardened') and _agent.is_hardened:
        verified = True

    return ChatResponse(
        response=response_text,
        commitment_hash=commitment_hash,
        verified=verified,
        threat_level=threat_level,
    )


@app.post("/agent/analyze", response_model=AnalyzeResponse)
async def agent_analyze(req: AnalyzeRequest, token: str = Depends(get_session_token)):
    """Analyze a file and suggest renaming."""
    if not _agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        result = _agent.analyze_file(req.filename)
    except Exception:
        # Fallback analysis
        result = {
            "suggested_name": req.filename,
            "category": _guess_category(req.extension),
            "confidence": 0.5,
            "reasoning": "Rule-based fallback analysis",
        }

    commitment_hash = hashlib.sha256(
        str(result).encode()
    ).hexdigest()[:16]

    return AnalyzeResponse(
        suggested_name=result.get("suggested_name", req.filename),
        category=result.get("category", "UNKNOWN"),
        confidence=result.get("confidence", 0.5),
        commitment_hash=commitment_hash,
        reasoning=result.get("reasoning"),
    )


@app.post("/agent/scan", response_model=ScanResponse)
async def agent_scan(token: str = Depends(get_session_token)):
    """Run security scan on vault."""
    if not _agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        result = _agent.security_scan()
    except Exception:
        result = {
            "threat_level": "UNKNOWN",
            "findings": [],
            "recommended_action": "Manual review recommended",
        }

    commitment_hash = hashlib.sha256(
        str(result).encode()
    ).hexdigest()[:16]

    return ScanResponse(
        threat_level=result.get("threat_level", "NONE"),
        findings=result.get("findings", []),
        recommended_action=result.get("recommended_action", "No action required"),
        commitment_hash=commitment_hash,
    )


# ── Audit ─────────────────────────────────────────
@app.get("/audit/trail", response_model=AuditTrailResponse)
async def audit_trail(
    token: str = Depends(get_session_token),
    limit: int = Query(default=50, ge=1, le=500),
    path: Optional[str] = Query(default=None),
):
    """Retrieve audit trail entries."""
    if not _audit_log:
        raise HTTPException(status_code=503, detail="Audit log not initialized")

    try:
        raw_entries = _audit_log.query(limit=limit)
    except Exception:
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
        # Filter by path if specified
        if path:
            entry_path = str(data.get("data", {}).get("path", ""))
            if path.lower() not in entry_path.lower():
                continue
        entries.append(e)

    return AuditTrailResponse(entries=entries[:limit])


# ── Status ────────────────────────────────────────
@app.get("/status", response_model=StatusResponse)
async def status():
    """System health check — no auth required."""
    watcher_status = "INACTIVE"
    if _watcher:
        try:
            watcher_status = "ACTIVE" if _watcher.is_running else "STANDBY"
        except Exception:
            watcher_status = "STANDBY"

    agent_status = "UNAVAILABLE"
    if _agent:
        agent_status = "HARDENED" if (
            hasattr(_agent, "is_hardened") and _agent.is_hardened
        ) else "ACTIVE"

    session_active = False
    if _session_mgr:
        session_active = _session_mgr.active_count > 0

    # IBM Quantum status
    ibm_status = "SIMULATOR"
    try:
        from aether_protocol.quantum_backend import get_quantum_seed
        _, method = get_quantum_seed()
        ibm_status = method
    except Exception:
        ibm_status = "OS_URANDOM"

    return StatusResponse(
        protocol_l="ACTIVE",
        watcher=watcher_status,
        agent=agent_status,
        session_active=session_active,
        vault_root=str(DEFAULT_VAULT_ROOT),
        ibm_status=ibm_status,
        uptime=round(time.time() - _start_time, 1),
        version=APP_VERSION,
    )


# ═══════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════
def _format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024*1024):.1f} MB"
    else:
        return f"{size_bytes / (1024*1024*1024):.1f} GB"


_ICON_MAP = {
    ".py": "🐍", ".js": "📜", ".ts": "📜", ".html": "🌐", ".css": "🎨",
    ".json": "📋", ".yaml": "📋", ".yml": "📋", ".toml": "📋",
    ".pdf": "📄", ".docx": "📝", ".doc": "📝", ".txt": "📃",
    ".xlsx": "📊", ".csv": "📊", ".xls": "📊",
    ".zip": "🗜", ".tar": "🗜", ".gz": "🗜", ".rar": "🗜",
    ".png": "🖼", ".jpg": "🖼", ".jpeg": "🖼", ".gif": "🖼", ".svg": "🖼",
    ".mp4": "🎬", ".mp3": "🎵", ".wav": "🎵",
    ".key": "🔑", ".pem": "🔑", ".enc": "🔑",
    ".db": "💾", ".sqlite": "💾",
    ".md": "📖", ".rst": "📖",
}


def _file_icon(ext: str) -> str:
    """Return emoji icon for file extension."""
    return _ICON_MAP.get(ext.lower(), "📄")


_CATEGORY_MAP = {
    ".py": "CODE", ".js": "CODE", ".ts": "CODE", ".html": "CODE", ".css": "CODE",
    ".json": "CONFIG", ".yaml": "CONFIG", ".yml": "CONFIG", ".toml": "CONFIG",
    ".pdf": "DOCUMENT", ".docx": "DOCUMENT", ".doc": "DOCUMENT", ".txt": "DOCUMENT",
    ".xlsx": "TRADING", ".csv": "TRADING", ".xls": "TRADING",
    ".zip": "BACKUP", ".tar": "BACKUP", ".gz": "BACKUP",
    ".key": "SECURITY", ".pem": "SECURITY", ".enc": "SECURITY",
    ".log": "LOG", ".md": "DOCUMENT",
}


def _guess_category(ext: str) -> str:
    """Guess file category from extension."""
    return _CATEGORY_MAP.get(ext.lower(), "PERSONAL")


# ═══════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════
def run_server():
    """Run the FastAPI server on localhost:8741."""
    uvicorn.run(
        "api_server:app",
        host="127.0.0.1",
        port=8741,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    run_server()
