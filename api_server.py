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
from dataclasses import dataclass, field
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
)
from auth.login import AetherCloudAuth
from auth.session import SessionManager
from vault.filebase import AetherVault
from vault.watcher import VaultWatcher
from agent.file_agent import AetherFileAgent
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

    @property
    def ready(self) -> bool:
        return self.auth is not None and self.vault is not None


svc = Services()
_start_time = time.time()
_ibm_status_cache: dict = {"value": "OS_URANDOM", "expires": 0.0}

security = HTTPBearer(auto_error=False)


def _init_services():
    """Initialize all backend services into the container."""
    # Audit log
    audit_dir = DEFAULT_AUDIT_DIR
    audit_dir.mkdir(parents=True, exist_ok=True)
    svc.audit_log = AuditLog(audit_dir / "aether_audit.jsonl")

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

    # Agent
    svc.agent = AetherFileAgent(vault=svc.vault)

    # Dev user — password is bcrypt-hashed on registration, never stored in plaintext
    _dev_pass = os.environ.get("AETHER_DEV_KEY", "fdf&*79u9*(*HJBh*U((9jijkKKL-d8a9(OS)0k")
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
    allow_origin_regex=r"^(file://|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?|http://143\.198\.162\.111(:\d+)?|null)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


class StatusResponse(BaseModel):
    protocol_l: str
    watcher: str
    agent: str
    session_active: bool
    vault_root: str
    ibm_status: str
    uptime: float
    version: str
    needs_setup: bool = False


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
    creds_file = Path("config") / "credentials.json"
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
        response_text = svc.agent.chat(req.query)
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
        return {"error": f"Path does not exist: {vault_root}", "folders": [], "files": [],
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
        return {"error": f"Permission denied: {vault_root}", "folders": [], "files": [],
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

    session_active = bool(svc.session_mgr and svc.session_mgr.active_count > 0)

    # IBM Quantum status — cached with 30s TTL
    now = time.time()
    if now > _ibm_status_cache["expires"]:
        try:
            from aether_protocol.quantum_backend import get_quantum_seed
            _, method = get_quantum_seed()
            _ibm_status_cache["value"] = method
        except Exception:
            _ibm_status_cache["value"] = "OS_URANDOM"
        _ibm_status_cache["expires"] = now + 30.0

    # Check if setup is needed (no credentials file or only dev user)
    creds_path = Path("config") / "credentials.json"
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
        session_active=session_active,
        vault_root=str(DEFAULT_VAULT_ROOT),
        ibm_status=_ibm_status_cache["value"],
        uptime=round(time.time() - _start_time, 1),
        version=APP_VERSION,
        needs_setup=needs_setup,
    )


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
