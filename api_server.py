#!/usr/bin/env python3
"""
AetherCloud-L — FastAPI Server
REST API on localhost:8741 for the Electron desktop app.

Aether Systems LLC — Patent Pending
"""

import json
import os
import re
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
from mcp_agent_status import status_manager
from mcp_router import mcp_router, ResolvedAgent
import agent_activity as _activity_mod
import agent_pipeline as _pipeline_mod
from project_context import ProjectContextManager
from project_orchestrator import ProjectOrchestrator
from project_routes import project_router
import project_routes as _proj_routes
from security.prompt_guard import get_prompt_guard, ThreatLevel
from agent.persistence import AgentPersistence
from lib.license_validation import (
    validate_license,
    MalformedKeyError,
    UpstreamError,
)
load_all_keys()

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Query, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn

# Rate limiter — keyed by session token (or IP as fallback)
def _get_session_key(request: Request) -> str:
    """Use Bearer token as rate limit key so limits are per-user not per-IP."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:][:16]  # first 16 chars of token as key
    return get_remote_address(request)

limiter = Limiter(key_func=_get_session_key)

from config.settings import (
    APP_NAME, APP_VERSION, DEFAULT_VAULT_ROOT, DEFAULT_AUDIT_DIR,
    MCP_WORKER_URL,
)
from config.storage import (
    ensure_system_dirs, ensure_user_dirs,
    CREDENTIALS_FILE as STORAGE_CREDENTIALS_FILE,
    AUDIT_LOG as STORAGE_AUDIT_LOG,
    DATA_ROOT,
    user_tasks_file, user_task_history, user_task_qopc,
    user_agent_team_file, user_agent_keys_file,
)
from auth.login import AetherCloudAuth
from auth.session import SessionManager
from vault.filebase import AetherVault
from vault_spaces import VaultSpacesClient
from vault.watcher import VaultWatcher
from vault.read_detector import ReadDetector
from agent.file_agent import AetherFileAgent
from agent.task_scheduler import (
    TaskScheduler, execute_task, load_task_store, save_task_store,
    get_task_history, parse_schedule,
)
from agent.task_qopc import TaskQOPC, TaskSignal
from agent.qopc_interaction_style import InteractionStyleProfile, analyze_query_signals, analyze_response_signals
from agent.qopc_agent import QOPCRegistry
from agent.voice_profiles import VOICE_STYLES, VoiceProfile, build_full_system_prompt, get_default_voice_for_icon, DEFAULT_VOICE_BY_ICON
from aether_protocol.audit import AuditLog

log = logging.getLogger("aethercloud.api")

# Per-user data directory for interaction style profiles etc.
_USER_DATA_DIR = str(DATA_ROOT / "users")

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
    vault_spaces: Optional[VaultSpacesClient] = None

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
_protocol_c_cache: dict = {
    "value": "CSPRNG" if _PROTOCOL_VARIANT == "C" else "OS_URANDOM",
    "expires": 0.0,
}

security = HTTPBearer(auto_error=False)

# ── VPS5 MCP Worker Dispatcher ────────────────────
# Lazily initialized — only loads keys if they exist on disk.
# VPS2 signs outbound requests with its Ed25519 private key;
# VPS5 verifies using VPS2's public key (mutual auth).
_vps2_node_auth = None

def _get_vps2_node_auth():
    global _vps2_node_auth
    if _vps2_node_auth is None:
        try:
            from mcp_worker.node_auth import NodeAuth
            _vps2_node_auth = NodeAuth(
                node_id="VPS2",
                private_key_path=os.environ.get("VPS2_NODE_KEY_PATH", "/opt/aether-mcp/certs/VPS2.key"),
                trusted_peers={},
            )
        except Exception as e:
            log.warning("VPS2 NodeAuth init failed — MCP tasks will call Anthropic directly: %s", e)
    return _vps2_node_auth


async def _dispatch_to_vps5(task: dict) -> dict:
    """Sign and POST an MCP task to VPS5. Falls back to None on failure."""
    import httpx
    import json as _json
    body = _json.dumps(task).encode()
    auth = _get_vps2_node_auth()
    headers = {"content-type": "application/json"}
    if auth and auth._private_key:
        try:
            headers.update(auth.sign_request(body))
        except Exception as e:
            log.warning("VPS5 request signing failed: %s", e)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{MCP_WORKER_URL}/agent/execute",
                headers=headers,
                content=body,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        log.warning("VPS5 dispatch failed: %s", e)
        return None


# ═══════════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialize services on startup, cleanup on shutdown."""
    _init_services()

    # Validate AetherCloud license (non-blocking — log only)
    try:
        from license_client import CloudLicenseClient, _license_info
        import license_client
        _lc = CloudLicenseClient()
        if _lc.key:
            _result = _lc.validate()
            license_client._license_info = _result
            if _result.get("valid"):
                if _result.get("grace_mode"):
                    log.warning("CLOUD LICENSE — grace mode (server unreachable)")
                else:
                    log.info(
                        "CLOUD LICENSE VALID — plan=%s expires=%s",
                        _result.get("plan"), _result.get("expires_at"),
                    )
            else:
                log.warning("CLOUD LICENSE INVALID — %s", _result.get("reason"))
        else:
            log.info("No AETHERCLOUD_LICENSE_KEY set — running unlicensed")
    except Exception as e:
        log.warning("License validation error: %s", e)

    # Wire vault_spaces into activity logger and init pipeline executor
    _activity_mod.vault_spaces = svc.vault_spaces
    _pipeline_mod.pipeline_executor = _pipeline_mod.PipelineExecutor(mcp_router)

    # Init autonomous project execution system
    _ctx_manager  = ProjectContextManager(svc.vault)
    _orchestrator = ProjectOrchestrator(mcp_router, _ctx_manager, api_key_fn=get_anthropic_key)
    _proj_routes.ctx_manager  = _ctx_manager
    _proj_routes.orchestrator = _orchestrator

    # ── UVT stack wiring (Stage F) ──────────────────────────────
    # PricingGuard + Router + /agent/run + /account/usage + /account/overage.
    # All billing flows read from public.plans / uvt_balances / usage_events
    # via the service-role supabase client (RLS bypass). If either env var is
    # unset we leave the routes disabled rather than crash boot — lets local
    # dev run without Supabase provisioned.
    try:
        from lib import uvt_routes as _uvt_routes
        from lib import health_routes as _health_routes
        from lib.router import Router as _Router
        from lib.license_validation import get_supabase_client
        _sb = get_supabase_client()
        _uvt_routes.supabase_client = _sb
        _uvt_routes.router_instance = _Router(_sb)
        _health_routes.supabase_client = _sb   # Stage J deep healthcheck
        log.info("UVT stack initialized (PricingGuard + Router + /agent/run)")
    except Exception as _uvt_exc:  # noqa: BLE001 — any failure here should NOT block boot
        log.warning("UVT stack init failed — /agent/run will return 503: %s", _uvt_exc)

    yield

# Introspection endpoints (/docs, /redoc, /openapi.json) are a route map
# for attackers on an internet-bound VPS. Audit finding M2 required they
# be hidden in production. They're enabled only when AETHER_ENV is dev.
_expose_docs = os.environ.get("AETHER_ENV", "").lower() in ("dev", "development", "local")

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Quantum-Secured AI File Intelligence API",
    lifespan=lifespan,
    docs_url="/docs" if _expose_docs else None,
    redoc_url="/redoc" if _expose_docs else None,
    openapi_url="/openapi.json" if _expose_docs else None,
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ═════════════════════════════════════════════════════════════════════
# CORS — non-credentialed only
# ═════════════════════════════════════════════════════════════════════
# This API authenticates via Bearer tokens (see get_session_token), NOT
# cookies. Prior config set `allow_credentials=True` with a regex that
# also matched `file://`, which the security audit flagged as Critical:
# any local HTML file or any allowlisted origin could trigger credentialed
# cross-site flows against the API.
#
# Fix: drop allow_credentials entirely (the Bearer-token flow needs no
# browser-managed credentials) and require HTTPS for every remote origin.
# The Electron renderer (file:// pages) still works — it sets the
# Authorization header manually, and the Authorization header is in
# allow_headers so preflight passes without needing Allow-Credentials.
#
# Allowed origins (exact, anchored):
#   * file://                     — Electron renderer pages
#   * null                        — modern Chromium file:// Origin
#   * http://localhost[:PORT]     — local dev
#   * http://127.0.0.1[:PORT]     — local dev
#   * https://<host>[:PORT]       — any AETHER_ALLOWED_ORIGINS entry, HTTPS only
# Anything else is rejected by the regex.
_CORS_LOCAL = r"file://|null|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?"
_extra_hosts = [h.strip() for h in os.environ.get("AETHER_ALLOWED_ORIGINS", "").split() if h.strip()]
_https_alts: list[str] = []
for host in _extra_hosts:
    stripped = host.replace("https://", "").replace("http://", "")
    if "/" in stripped:
        stripped = stripped.split("/", 1)[0]
    if stripped:
        _https_alts.append(rf"https://{re.escape(stripped)}(:\d+)?")

_cors_parts = [_CORS_LOCAL] + _https_alts
_cors_regex = r"^(" + "|".join(_cors_parts) + r")$"
logging.getLogger("aethercloud.cors").info("CORS origin regex: %s (credentialed=False)", _cors_regex)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_cors_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Project execution router
app.include_router(project_router)

# UVT billable entrypoint + account endpoints (Stage F)
from lib.uvt_routes import uvt_router  # noqa: E402 — must come after app init
app.include_router(uvt_router)

# Health endpoints (Stage J) — liveness, deep, flag-snapshot
from lib.health_routes import health_router  # noqa: E402
app.include_router(health_router)


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


@app.get("/agent/mcp-status")
async def mcp_status_stream(current_user: str = Depends(get_session_token)):
    """SSE stream of live MCP agent activity for the dashboard."""
    return StreamingResponse(
        status_manager.stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


# ── Agent Team Config ─────────────────────────────
class AgentTeamRequest(BaseModel):
    """Pydantic placeholder so FastAPI resolves body for POST /agent/team."""
    pass  # payload is a raw list — we'll read via Request.json()


@app.get("/agent/team")
async def get_agent_team(token: str = Depends(get_session_token)):
    """Load the user's MCP agent team config from vault storage."""
    username = get_username_from_token(token)
    ensure_user_dirs(username)
    team_file = user_agent_team_file(username)
    if not team_file.exists():
        return []
    try:
        return json.loads(team_file.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Failed to read team config for %s: %s", username, e)
        return []


@app.post("/agent/team")
async def save_agent_team(request: Request, token: str = Depends(get_session_token)):
    """Persist the user's MCP agent team config to vault storage.

    Body: JSON array of agent config objects.
    Strips any 'keyHint' fields before writing — raw keys live in agent_keys.json.
    """
    username = get_username_from_token(token)
    ensure_user_dirs(username)
    try:
        agents = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be a JSON array")
    if not isinstance(agents, list):
        raise HTTPException(status_code=400, detail="Expected a JSON array of agent objects")

    # Scan custom system prompts for embedded injection attempts
    guard = get_prompt_guard(svc.audit_log)
    for a in agents:
        if isinstance(a, dict) and a.get("prompt"):
            scan = guard.scan_system_prompt(a["prompt"])
            if scan.is_blocked:
                log.warning("Blocked agent team save — injected system prompt detected: agent=%s", a.get("name"))
                raise HTTPException(
                    status_code=403,
                    detail=f"Agent '{a.get('name', '?')}' has a blocked system prompt — "
                           "injection patterns detected.",
                )

    # Never persist the key hint (masked display) — keys are stored separately
    safe_agents = []
    for a in agents:
        if isinstance(a, dict):
            safe = {k: v for k, v in a.items() if k != "keyHint"}
            safe_agents.append(safe)

    team_file = user_agent_team_file(username)
    team_file.parent.mkdir(parents=True, exist_ok=True)
    team_file.write_text(json.dumps(safe_agents, indent=2), encoding="utf-8")
    # Priority 7: invalidate router cache so next query sees new config
    mcp_router.invalidate_cache(username)
    log.info("Team config saved for %s (%d agents)", username, len(safe_agents))
    return {"ok": True, "count": len(safe_agents)}


class AgentKeyRequest(BaseModel):
    key: str


@app.post("/agent/key/{agent_id}")
async def store_agent_key(
    agent_id: str,
    req: AgentKeyRequest,
    token: str = Depends(get_session_token),
):
    """Store an MCP agent's API key in the user's per-user key store.

    Keys are stored separately from team config and never sent back to the client.
    """
    username = get_username_from_token(token)
    ensure_user_dirs(username)
    keys_file = user_agent_keys_file(username)
    keys_file.parent.mkdir(parents=True, exist_ok=True)

    # Load existing keys
    keys: dict = {}
    if keys_file.exists():
        try:
            keys = json.loads(keys_file.read_text(encoding="utf-8"))
        except Exception:
            keys = {}

    keys[agent_id] = req.key.strip()
    keys_file.write_text(json.dumps(keys, indent=2), encoding="utf-8")

    # Protect the file: chmod 600 on POSIX systems
    try:
        import stat
        keys_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass  # Windows — no chmod, file ACLs handle it

    log.info("API key stored for agent %s (user: %s)", agent_id, username)
    return {"ok": True}


class AgentTestRequest(BaseModel):
    server: str
    url: str = ""
    transport: str = "http"
    agentId: str = "test"


@app.post("/agent/test")
@limiter.limit("10/minute")
async def test_agent_connection(
    request: Request,
    req: AgentTestRequest,
    token: str = Depends(get_session_token),
):
    """Test connectivity to an MCP server.

    For HTTP transport: sends a GET request to the server URL and checks response.
    For stdio transport: reports stdio servers as always reachable (local process).
    Returns: { ok: bool, tools: list, error: str }
    """
    username = get_username_from_token(token)

    # stdio servers run locally — always reachable
    stdio_servers = {"excalidraw", "context7", "desktop_commander", "custom_stdio"}
    if req.transport == "stdio" or req.server in stdio_servers:
        return {"ok": True, "tools": [], "message": "stdio server (local process)"}

    if not req.url:
        raise HTTPException(status_code=400, detail="URL required for HTTP transport")

    # Load stored API key for this agent if it exists
    keys_file = user_agent_keys_file(username)
    api_key = None
    if keys_file.exists():
        try:
            keys = json.loads(keys_file.read_text(encoding="utf-8"))
            api_key = keys.get(req.agentId)
        except Exception:
            pass

    import httpx
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # Standard MCP health/capabilities probe
            resp = await client.get(req.url, headers=headers)
            if resp.status_code in (200, 404, 405):
                # 404/405 just means no GET endpoint — server is up
                return {"ok": True, "tools": [], "status_code": resp.status_code}
            return {
                "ok": False,
                "error": f"HTTP {resp.status_code}",
                "status_code": resp.status_code,
            }
    except httpx.TimeoutException:
        return {"ok": False, "error": "Connection timed out (>8s)"}
    except httpx.ConnectError as e:
        return {"ok": False, "error": f"Connection refused: {e}"}
    except Exception as e:
        log.warning("MCP connection test failed for %s: %s", req.url, e)
        return {"ok": False, "error": str(e)}


# ── Tool Discovery (Priority 4) ───────────────────

@app.get("/agent/tools/{agent_id}")
@limiter.limit("20/minute")
async def get_agent_tools(
    request: Request,
    agent_id: str,
    token: str = Depends(get_session_token),
):
    """
    Discover tools exposed by the MCP server configured for a given agent.
    Sends an MCP initialize + tools/list request to the server URL.
    Returns a list of {name, description} objects.
    """
    import httpx

    username = get_username_from_token(token)
    agent = mcp_router.get_agent(username, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found in team config")

    url = agent.get("url", "")
    transport = agent.get("transport", "http")
    server = agent.get("server", "")

    # stdio servers — return static info from known registry
    _KNOWN_TOOLS: dict = {
        "excalidraw":        [{"name": "create_diagram", "description": "Create an Excalidraw diagram from a description"}],
        "context7":          [{"name": "resolve-library-id", "description": "Resolve library docs ID"}, {"name": "get-library-docs", "description": "Fetch up-to-date library documentation"}],
        "desktop_commander": [{"name": "execute_command", "description": "Run shell commands"}, {"name": "read_file", "description": "Read local files"}, {"name": "write_file", "description": "Write local files"}],
    }
    if transport == "stdio" or server in _KNOWN_TOOLS:
        tools = _KNOWN_TOOLS.get(server, [{"name": server, "description": "stdio MCP server (local)"}])
        return {"ok": True, "tools": tools, "source": "static"}

    if not url:
        return {"ok": False, "tools": [], "error": "No server URL configured"}

    # Load vault key for auth
    vault_key = await _load_agent_key(username, agent_id)
    headers = {"Content-Type": "application/json"}
    if vault_key:
        headers["Authorization"] = f"Bearer {vault_key}"

    # MCP tools/list over HTTP
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try standard MCP tools list endpoint
            resp = await client.post(
                url,
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_tools = data.get("result", {}).get("tools", [])
                tools = [
                    {"name": t.get("name", "?"), "description": t.get("description", "")}
                    for t in raw_tools
                ]
                return {"ok": True, "tools": tools, "source": "live"}
            return {"ok": False, "tools": [], "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "tools": [], "error": str(e)}


# ── Activity Endpoints (Priority 5) ──────────────

@app.get("/agent/activity/{agent_id}")
async def get_agent_activity(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    token: str = Depends(get_session_token),
):
    """Return per-agent activity log (most recent first)."""
    username = get_username_from_token(token)
    entries = await _activity_mod.get_activity(username, agent_id, limit=limit)
    return {"agent_id": agent_id, "entries": entries, "count": len(entries)}


@app.get("/agent/activity")
async def get_all_agent_activity(
    limit: int = Query(default=100, ge=1, le=500),
    token: str = Depends(get_session_token),
):
    """Return activity log for all user agents, most recent first."""
    username = get_username_from_token(token)
    entries = await _activity_mod.get_all_activity(username, limit=limit)
    return {"entries": entries, "count": len(entries)}


# ── Pipeline Endpoints (Priority 6) ──────────────

class PipelineRunRequest(BaseModel):
    steps: list           # [{agent_id, prompt_template, label}]
    initial_input: str
    name: str = "Pipeline"


@app.post("/agent/pipeline/run")
@limiter.limit("5/minute")
async def run_pipeline(
    request: Request,
    req: PipelineRunRequest,
    token: str = Depends(get_session_token),
):
    """Execute a pipeline — run each step sequentially with output chaining."""
    # ── Prompt injection guard on pipeline input ────
    guard = get_prompt_guard(svc.audit_log)
    scan = guard.scan(req.initial_input, context="pipeline")
    if scan.is_blocked:
        log.warning("Pipeline input blocked: rules=%s", scan.matched_rules)
        raise HTTPException(status_code=403, detail="Pipeline input blocked by security guard")

    username = get_username_from_token(token)
    api_key = get_anthropic_key()

    executor = getattr(_pipeline_mod, "pipeline_executor", None)
    if executor is None:
        executor = _pipeline_mod.PipelineExecutor(mcp_router)

    results = await executor.run(
        user_id=username,
        steps=req.steps,
        initial_input=req.initial_input,
        api_key=api_key,
    )
    return {
        "name": req.name,
        "step_count": len(req.steps),
        "results": results,
        "ok": all(r.get("status") == "ok" for r in results),
    }


@app.get("/agent/pipeline/templates")
async def get_pipeline_templates(token: str = Depends(get_session_token)):
    """Return the built-in pipeline templates."""
    return {"templates": _pipeline_mod.PIPELINE_TEMPLATES}


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

    # DO Spaces vault client
    svc.vault_spaces = VaultSpacesClient()
    if svc.vault_spaces.available:
        log.info("DO Spaces vault client ready")
    else:
        log.warning("DO Spaces not configured — vault uploads disabled")

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

    # Dev user — gated behind AETHER_ENV=dev per audit L2. The bcrypt hash
    # of the dev password otherwise ends up on disk on every production
    # server. The user is only created when explicitly opted-in.
    if os.environ.get("AETHER_ENV", "").lower() in ("dev", "development", "local"):
        _dev_pass = get_dev_key()
        if svc.auth.register_user("ZO", _dev_pass):
            log.info("Registered dev user: ZO (AETHER_ENV=dev)")
        del _dev_pass  # scrub from memory immediately
    else:
        log.info("Skipped dev user registration — set AETHER_ENV=dev to enable")


# ═══════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ═══════════════════════════════════════════════════
class SetupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str
    license_key: Optional[str] = None  # Required on first-time setup; persisted to env


class VerifyRequest(BaseModel):
    session_token: str


class LoginResponse(BaseModel):
    authenticated: bool
    session_token: Optional[str] = None
    commitment_hash: Optional[str] = None
    timestamp: str
    reason: Optional[str] = None
    plan: Optional[str] = None


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


class LicenseStatus(BaseModel):
    valid: bool = False
    plan: Optional[str] = None
    expires_at: Optional[str] = None
    grace_mode: bool = False


class StatusResponse(BaseModel):
    protocol_c: str
    watcher: str
    agent: str
    read_detector: str = "INACTIVE"
    session_active: bool
    vault_root: str
    uptime: float
    version: str
    needs_setup: bool = False
    license: Optional[LicenseStatus] = None


# ── Scheduled Task Models ────────────────────────
class TaskCreateRequest(BaseModel):
    name: str
    natural_language: str
    schedule_cron: Optional[str] = None
    schedule_label: Optional[str] = None
    agent_type: str = "custom"
    mcp_servers: Optional[list] = []
    requires_browser_sandbox: bool = False
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

    # ── License key validation (first-time setup or re-supply) ──────────────
    # Validate the license key WITHOUT touching global process state. Audit
    # finding H8 flagged the prior implementation as writing `os.environ[...]`
    # before the caller authenticated, which let any unauthenticated network
    # caller bump the server-wide license binding. The env var is now only
    # mutated AFTER svc.auth.login() succeeds (see _commit_license below).
    _pending_license: Optional[str] = None  # populated only after full validation
    _pending_license_info: Optional[dict] = None
    if req.license_key:
        _lk = req.license_key.strip()
        try:
            from license_client import CloudLicenseClient, KEY_PATTERN
            if not KEY_PATTERN.match(_lk):
                return LoginResponse(
                    authenticated=False,
                    timestamp=datetime.now().isoformat(),
                    reason="LICENSE_INVALID",
                )
            # Validate against license server using a local override (does NOT
            # touch process env). CloudLicenseClient accepts an explicit key.
            _lc = CloudLicenseClient(license_key=_lk)
            _result = _lc.validate()
            if not _result.get("valid"):
                _reason = _result.get("reason", "")
                if "expired" in _reason.lower():
                    return LoginResponse(
                        authenticated=False,
                        timestamp=datetime.now().isoformat(),
                        reason="LICENSE_EXPIRED",
                    )
                return LoginResponse(
                    authenticated=False,
                    timestamp=datetime.now().isoformat(),
                    reason="LICENSE_INVALID",
                )
            _pending_license = _lk
            _pending_license_info = _result
            log.info("License validated via login for key=****%s plan=%s", _lk[-4:], _result.get("plan"))
        except TypeError:
            # CloudLicenseClient doesn't accept license_key kwarg on older
            # builds — fall back to the old behavior but still keep the
            # commit gated on auth success below.
            os.environ.setdefault("AETHERCLOUD_LICENSE_KEY_PENDING", _lk)
            _pending_license = _lk
        except Exception as _le:
            log.warning("License validation error during login: %s", _le)
            # Non-blocking: allow login to continue if license server is unreachable
            # but a cached valid license exists (grace mode handled inside CloudLicenseClient)

    result = svc.auth.login(req.username, req.password)

    # Commit the validated license key to the process env ONLY after auth
    # succeeded. An unauthenticated caller can no longer mutate server state.
    if result.get("authenticated") and _pending_license:
        os.environ["AETHERCLOUD_LICENSE_KEY"] = _pending_license
        os.environ.pop("AETHERCLOUD_LICENSE_KEY_PENDING", None)
        if _pending_license_info:
            try:
                import license_client as _lc_mod
                _lc_mod._license_info = _pending_license_info
            except Exception:
                pass

    # Attach plan from license info if available
    _plan = None
    try:
        from license_client import get_license_info
        _li = get_license_info()
        if _li and _li.get("valid"):
            _plan = _li.get("plan")
    except Exception:
        pass

    return LoginResponse(
        authenticated=result.get("authenticated", False),
        session_token=result.get("session_token"),
        commitment_hash=result.get("commitment_hash") or result.get("audit_id"),
        timestamp=result.get("timestamp", datetime.now().isoformat()),
        reason=result.get("reason"),
        plan=_plan,
    )


@app.post("/auth/verify")
async def verify_session(req: VerifyRequest):
    """
    Verify a session token is still valid without re-authenticating.
    Called by the Electron login screen on startup to restore a remembered session.
    Returns { valid: true, username: str } or { valid: false }.
    """
    if not svc.session_mgr:
        return {"valid": False, "reason": "session_mgr not initialized"}

    token = req.session_token
    if not token or not svc.session_mgr.is_valid(token):
        return {"valid": False}

    username = svc.session_mgr.get_username(token)
    return {"valid": True, "username": username}


@app.post("/auth/refresh")
async def refresh_session(token: str = Depends(get_session_token)):
    """
    Exchange a valid session token for a fresh one, resetting the timeout.
    Called by the Electron app when the session is within 30 minutes of expiry.
    Returns { session_token: str } or 401 if the token is expired.
    """
    if not svc.session_mgr:
        raise HTTPException(status_code=503, detail="Session manager not initialized")

    new_token = svc.session_mgr.refresh_token(token)
    if not new_token:
        raise HTTPException(status_code=401, detail="Session expired — please log in again")

    return {"session_token": new_token, "timestamp": datetime.now().isoformat()}


@app.post("/auth/logout", response_model=LogoutResponse)
async def logout(req: LogoutRequest):
    """Terminate session. Accepts token in request body. Idempotent — always returns 200."""
    token = req.session_token
    audit_id = None
    if svc.session_mgr:
        svc.session_mgr.invalidate(token)
    if svc.auth:
        try:
            result = svc.auth.logout(token)
            audit_id = result.get("audit_id")
        except Exception:
            pass
    # Free the per-token context dict entry — audit M6 flagged that this
    # would otherwise accumulate across the process lifetime as a slow leak.
    session_context.pop(token, None)
    return LogoutResponse(success=True, audit_id=audit_id)


@app.post("/auth/setup")
async def setup_first_user(request: SetupRequest):
    """Create initial admin user. Only works once. Requires a valid license."""
    if not svc.auth:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    # Require a valid (or grace-mode) license before allowing account creation
    try:
        from license_client import get_license_info
        _li = get_license_info()
        if _li and not _li.get("valid") and not _li.get("grace_mode"):
            raise HTTPException(
                status_code=403,
                detail="LICENSE_INVALID — a valid AetherCloud license is required to set up this system",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # license check failure is non-blocking if module unavailable

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


# ── Vault Spaces (DO Spaces cloud storage) ────────
@app.post("/vault/spaces/upload")
async def vault_spaces_upload(
    file: UploadFile = File(...),
    token: str = Depends(get_session_token),
):
    """Upload a file to the user's cloud vault (DO Spaces)."""
    if not svc.vault_spaces or not svc.vault_spaces.available:
        raise HTTPException(status_code=503, detail="Cloud vault not configured")

    username = get_username_from_token(token)
    data = await file.read()
    try:
        meta = svc.vault_spaces.upload(
            username=username,
            filename=file.filename or "unnamed",
            data=data,
            content_type=file.content_type,
        )
        return {"success": True, **meta}
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    except Exception as exc:
        log.error("Vault upload failed: %s", exc)
        raise HTTPException(status_code=500, detail="Upload failed — check server logs for details")


@app.get("/vault/spaces/list")
async def vault_spaces_list(token: str = Depends(get_session_token)):
    """List all files in the user's cloud vault."""
    if not svc.vault_spaces or not svc.vault_spaces.available:
        raise HTTPException(status_code=503, detail="Cloud vault not configured")

    username = get_username_from_token(token)
    files = svc.vault_spaces.list_files(username)
    return {"success": True, "files": files, "count": len(files)}


@app.get("/vault/spaces/download/{filename:path}")
async def vault_spaces_download(
    filename: str,
    token: str = Depends(get_session_token),
):
    """Download a file from the user's cloud vault."""
    if not svc.vault_spaces or not svc.vault_spaces.available:
        raise HTTPException(status_code=503, detail="Cloud vault not configured")

    username = get_username_from_token(token)

    # Strip CR/LF and double-quote from the filename before placing it in
    # the Content-Disposition header — prevents HTTP response splitting
    # via attacker-controlled upload names (audit finding M5).
    safe_disp = filename.replace("\r", "").replace("\n", "").replace('"', "'")

    try:
        stream, content_type, size = svc.vault_spaces.download(username, filename)
        return StreamingResponse(
            stream,
            media_type=content_type,
            headers={
                # Always serve as an attachment — never inline-render in
                # the browser even if the stored Content-Type is text/html.
                "Content-Disposition": f'attachment; filename="{safe_disp}"',
                "Content-Length": str(size),
                # Block MIME sniffing — browser must honor the declared
                # Content-Type, which upload() forces to octet-stream for
                # any risky uploaded file.
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception as exc:
        log.error("Vault download failed: %s", exc)
        raise HTTPException(status_code=404, detail="File not found or unavailable")


@app.get("/vault/spaces/content/{filename:path}")
async def vault_spaces_content(
    filename: str,
    token: str = Depends(get_session_token),
):
    """Get text content of a vault file (for agent context injection)."""
    if not svc.vault_spaces or not svc.vault_spaces.available:
        raise HTTPException(status_code=503, detail="Cloud vault not configured")

    username = get_username_from_token(token)
    text = svc.vault_spaces.download_text(username, filename)
    if text is None:
        return {"success": True, "binary": True, "content": None, "filename": filename}
    return {"success": True, "binary": False, "content": text, "filename": filename}


@app.delete("/vault/spaces/delete/{filename:path}")
async def vault_spaces_delete(
    filename: str,
    token: str = Depends(get_session_token),
):
    """Delete a file from the user's cloud vault."""
    if not svc.vault_spaces or not svc.vault_spaces.available:
        raise HTTPException(status_code=503, detail="Cloud vault not configured")

    username = get_username_from_token(token)
    ok = svc.vault_spaces.delete(username, filename)
    if not ok:
        raise HTTPException(status_code=500, detail="Delete failed")
    return {"success": True, "deleted": filename}


# ── Daily Planner — completely isolated from file-agent identity ───────────────
@app.post("/agent/plan-day", response_model=ChatResponse)
@limiter.limit("20/minute;100/hour")
async def agent_plan_day(request: Request, req: ChatRequest, token: str = Depends(get_session_token)):
    """Build a structured daily plan. Uses pure planner system prompt — no file-agent identity."""
    if not svc.agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    try:
        response_text = svc.agent.plan_day(req.query)
    except Exception as e:
        log.warning("plan_day failed: %s", e)
        response_text = "Planner unavailable — please try again."
    return ChatResponse(
        response=response_text,
        commitment_hash=_commitment_hash(response_text),
        verified=False,
        threat_level="NONE",
    )


# ── Agent ─────────────────────────────────────────
@app.post("/agent/chat", response_model=ChatResponse)
@limiter.limit("20/minute;100/hour")
async def agent_chat(request: Request, req: ChatRequest, token: str = Depends(get_session_token)):
    """Chat with the AI agent. Response is Protocol-L committed."""
    if not svc.agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    # ── Prompt injection guard ──────────────────────
    guard = get_prompt_guard(svc.audit_log)
    scan = guard.scan(req.query, context="chat")
    if scan.is_blocked:
        log.warning("Chat prompt blocked: rules=%s hash=%s", scan.matched_rules, scan.query_hash)
        return ChatResponse(
            response="Your request was blocked by AetherCloud security. "
                     "The system detected potentially harmful or unauthorized content. "
                     "This event has been logged to the audit trail.",
            commitment_hash=scan.query_hash,
            verified=False,
            threat_level=scan.threat_level.value,
        )

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

        # Analyze query for interaction style signals (passive learning)
        try:
            username = get_username_from_token(token)
            style_profile = InteractionStyleProfile(username, _USER_DATA_DIR)
            query_signals = analyze_query_signals(req.query)
            for sig in query_signals:
                style_profile.record_signal(sig)
        except Exception:
            pass  # Style tracking is non-critical

        # Route planning queries to the dedicated planner (no file-agent identity)
        if svc.agent._is_planning_query(req.query):
            response_text = svc.agent.plan_day(req.query)
        else:
            response_text = svc.agent.chat(query)
    except Exception as e:
        log.warning("agent.chat failed: %s", e, exc_info=True)
        response_text = f"Agent error: {type(e).__name__}: {str(e)[:200]}"

    verified = hasattr(svc.agent, 'is_hardened') and svc.agent.is_hardened

    return ChatResponse(
        response=response_text,
        commitment_hash=_commitment_hash(response_text),
        verified=verified,
        threat_level="NONE",  # Threat assessment via /agent/scan, not text parsing
    )


@app.post("/agent/analyze", response_model=AnalyzeResponse)
@limiter.limit("30/minute")
async def agent_analyze(request: Request, req: AnalyzeRequest, token: str = Depends(get_session_token)):
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
@limiter.limit("10/minute")
async def agent_scan(request: Request, token: str = Depends(get_session_token)):
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

    # Update the agent's context scorer + interaction style
    if svc.agent and svc.agent._claude_available and svc.agent._claude_agent:
        try:
            username = get_username_from_token(token)
            svc.agent._claude_agent._user_id = username
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


# ── MCP Chat helpers ──────────────────────────────

async def _load_agent_key(user_id: str, agent_id: str) -> Optional[str]:
    """Read per-user API key for a configured agent."""
    keys_file = user_agent_keys_file(user_id)
    if not keys_file.exists():
        return None
    try:
        keys = json.loads(keys_file.read_text(encoding="utf-8"))
        return keys.get(agent_id)
    except Exception:
        return None


def _build_mcp_servers(agent: Optional[ResolvedAgent], fallback: list) -> list:
    """Convert a ResolvedAgent into the mcp_servers list for the Anthropic API."""
    if not agent or not agent.url:
        return fallback
    srv: dict = {
        "type": "url",
        "url": agent.url,
        "name": agent.server_name or agent.name,
    }
    return [srv]


def _build_system_prompt(agent: Optional[ResolvedAgent], vault_context: Optional[dict], username: str) -> str:
    """Build the system prompt — prefer agent's custom prompt, fall back to generic."""
    if agent and agent.system_prompt:
        base = agent.system_prompt + "\n\n"
    else:
        base = (
            f"You are AetherCloud's autonomous agent for {username}.\n\n"
            "You have access to external tools via MCP servers. Use them proactively.\n\n"
            "RULES:\n"
            "1. When asked about emails — USE the Gmail tool to actually read them.\n"
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


def _build_messages(history: list, query: str) -> list:
    messages = list(history or [])
    messages.append({"role": "user", "content": query})
    return messages


def _summarize_query(query: str, max_len: int = 120) -> str:
    q = query.strip().replace("\n", " ")
    return q[:max_len] + "…" if len(q) > max_len else q


BROWSER_TOOL_NAMES = {"browser_navigate", "browser_interact", "browser_snapshot", "browser_end"}


async def _process_browser_tool_loop(
    data: dict,
    messages: list,
    system: str | None,
    tools: list | None,
    mcp_servers: list | None,
    max_tokens: int,
    browser_session_id: str | None,
    credential_token: str | None,
    response_text_parts: list,
    tools_used: list,
) -> dict:
    """
    Handle browser tool_use blocks in the Claude response.

    If Claude's response contains browser tool calls, execute them via
    aetherbrowser_client and feed the results back in a tool-use loop.
    Returns the final API response (which may be the original if no
    browser tools were used).

    Every continuation call in the loop routes through TokenAccountant so
    prompt caching + usage accounting apply uniformly.
    """
    from agent import aetherbrowser_client as _browser
    from lib import token_accountant

    max_iterations = 25  # safety cap on tool-use loops

    for _iteration in range(max_iterations):
        # Check if any content block is a browser tool_use
        browser_calls = [
            b for b in data.get("content", [])
            if b.get("type") == "tool_use" and b.get("name") in BROWSER_TOOL_NAMES
        ]
        if not browser_calls:
            return data  # No browser tools — pass through

        # Collect text blocks from this turn
        for block in data.get("content", []):
            if block.get("type") == "text":
                response_text_parts.append(block.get("text", ""))

        # Process each browser tool call
        tool_results = []
        for call in browser_calls:
            tool_name = call["name"]
            tool_input = call.get("input", {})
            tool_id = call.get("id", "")
            tools_used.append(tool_name)

            try:
                if tool_name == "browser_navigate":
                    if not browser_session_id:
                        browser_session_id = await _browser.create_session()
                    result = await _browser.navigate(
                        browser_session_id,
                        tool_input.get("url", ""),
                        credential_token=credential_token,
                    )
                    credential_token = None  # only pass on first navigate

                elif tool_name == "browser_snapshot":
                    if not browser_session_id:
                        result = {"error": "No active browser session"}
                    else:
                        result = await _browser.snapshot(browser_session_id)

                elif tool_name == "browser_interact":
                    if not browser_session_id:
                        result = {"error": "No active browser session"}
                    else:
                        result = await _browser.interact(
                            browser_session_id,
                            action=tool_input.get("action", "click"),
                            target=tool_input.get("target", {}),
                            text=tool_input.get("text"),
                        )

                elif tool_name == "browser_end":
                    if browser_session_id:
                        await _browser.end_session(browser_session_id)
                        browser_session_id = None
                    result = {"status": "ok", "message": "Browser session ended."}

                else:
                    result = {"error": f"Unknown browser tool: {tool_name}"}

            except _browser.BrowserCapacityError as exc:
                result = {
                    "status": "capacity_exceeded",
                    "retry_after_seconds": exc.retry_after,
                    "message": str(exc),
                }
            except Exception as exc:
                log.warning("Browser tool %s failed: %s", tool_name, exc)
                result = {"error": str(exc)}

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": json.dumps(result) if isinstance(result, dict) else str(result),
            })

        # Feed tool results back to Claude for the next turn
        loop_messages = list(messages)
        loop_messages.append({"role": "assistant", "content": data["content"]})
        loop_messages.append({"role": "user", "content": tool_results})

        try:
            ta_resp = await token_accountant.call(
                model="sonnet",
                messages=loop_messages,
                user_id=None,
                system=system,
                tools=tools,
                mcp_servers=mcp_servers,
                max_tokens=max_tokens,
            )
            data = ta_resp.raw
            messages = loop_messages  # carry forward for next iteration
        except Exception as e:
            log.warning("Browser tool loop API call failed: %s", e)
            return data

        # If Claude stopped without another tool call, we're done
        if data.get("stop_reason") != "tool_use":
            return data

    return data


@app.post("/agent/mcp-chat", response_model=MCPAgentResponse)
@limiter.limit("20/minute;100/hour")
async def agent_mcp_chat(
    request: Request,
    req: MCPAgentRequest,
    token: str = Depends(get_session_token),
):
    """
    MCP-enabled agent endpoint.
    Priority 1: Routes to user's configured team agents by keyword match.
    Priority 2: Status bar events (agent_start / agent_done).
    Priority 3: Per-user vault key injection.
    Falls back to VPS5 worker → direct Anthropic if no team agent matches.
    """
    import httpx
    from agent.mcp_registry import detect_required_servers
    from agent.browser_tool_injector import inject_browser_tools
    import asyncio

    # ── Prompt injection guard ──────────────────────
    guard = get_prompt_guard(svc.audit_log)
    scan = guard.scan(req.query, context="mcp_agent")
    if scan.is_blocked:
        log.warning("MCP chat prompt blocked: rules=%s hash=%s", scan.matched_rules, scan.query_hash)
        return MCPAgentResponse(
            response="Your request was blocked by AetherCloud security. "
                     "The system detected potentially harmful or unauthorized content. "
                     "This event has been logged.",
            tools_used=[],
            commitment_hash=scan.query_hash,
            verified=False,
        )

    # Scan conversation history for embedded injection
    if req.conversation_history:
        history_scan = guard.scan_conversation_history(req.conversation_history)
        if history_scan and history_scan.is_blocked:
            log.warning("MCP chat history injection detected: rules=%s", history_scan.matched_rules)
            return MCPAgentResponse(
                response="Injection detected in conversation history. Session terminated for security.",
                tools_used=[],
                commitment_hash=history_scan.query_hash,
                verified=False,
            )

    username = get_username_from_token(token)

    # ── Priority 1: Route to user's configured team agent ─────
    routed_agent: Optional[ResolvedAgent] = await mcp_router.route(username, req.query)

    if routed_agent:
        # Priority 3: inject vault key into mcp_servers
        vault_key = await _load_agent_key(username, routed_agent.agent_id)
        mcp_servers = _build_mcp_servers(routed_agent, [])
        if vault_key and mcp_servers:
            mcp_servers[0]["authorization_token"] = vault_key
        system = _build_system_prompt(routed_agent, req.vault_context, username)
        server_name = routed_agent.server_name or routed_agent.name
        status_agent_id = f"{username}_{routed_agent.agent_id}"
        log.info("MCP chat routed to team agent '%s' (server=%s)", routed_agent.name, server_name)
    else:
        # Builtin auto-detection fallback
        mcp_servers = req.mcp_servers or detect_required_servers(req.query)
        system = _build_system_prompt(None, req.vault_context, username)
        server_name = mcp_servers[0].get("name", "mcp") if mcp_servers else "mcp"
        status_agent_id = f"{username}_{server_name}_{str(uuid.uuid4())[:8]}"

    # ── Browser tool injection (if agent requires sandbox) ────
    browser_tools: list = []
    if routed_agent:
        browser_tools, system = inject_browser_tools(routed_agent, browser_tools, system)

    # ── Priority 2: Fire status bar event ─────────────────────
    await status_manager.agent_start(
        agent_id=status_agent_id,
        server_name=server_name,
        task=req.query[:60],
    )

    response_text = ""
    tools_used: list = []
    commitment_hash = ""
    routed_via = "direct"
    error_str = ""

    try:
        # ── Try VPS5 worker first (only for builtin/fallback path) ────
        vps5_result = None
        if not routed_agent:
            task_id = str(uuid.uuid4())
            task = {
                "task_id": task_id,
                "client_id": username,
                "agent_type": "mcp",
                "prompt": req.query,
                "context": system,
                "mcp_server_url": mcp_servers[0]["url"] if mcp_servers else "",
            }
            vps5_result = await _dispatch_to_vps5(task)

        if vps5_result and not vps5_result.get("error"):
            response_text = vps5_result.get("result", "")
            tools_used = vps5_result.get("tools_used", [])
            commitment_hash = vps5_result.get("protocol_c_post", _commitment_hash(response_text))
            routed_via = "VPS5"
            log.info("MCP task completed via VPS5 — tools=%s", tools_used)
        else:
            # ── Direct Anthropic call (team agent OR VPS5 fallback) ───
            if vps5_result and vps5_result.get("error"):
                log.warning("VPS5 error — falling back to direct: %s", vps5_result["error"])

            # UVT routing: every Anthropic call flows through TokenAccountant.
            # Stage B: user_id=None (unattributed); PricingGuard in Stage E
            # will thread the real UUID. Model key resolves to Sonnet by default
            # until the QOPC router lands in Stage D.
            from lib import token_accountant
            messages = _build_messages(req.conversation_history, req.query)
            combined_tools = list(browser_tools) if browser_tools else None

            try:
                ta_resp = await token_accountant.call(
                    model="sonnet",
                    messages=messages,
                    user_id=None,
                    system=system,
                    tools=combined_tools,
                    mcp_servers=mcp_servers or None,
                    max_tokens=req.max_tokens,
                )
                data = ta_resp.raw
            except Exception as e:
                log.warning("MCP agent direct call failed: %s", e)
                raise HTTPException(status_code=502, detail="Agent worker unavailable")

            # Process response and handle browser tool calls
            browser_session_id = None
            browser_credential_token = None  # set externally if auth needed
            try:
                data = await _process_browser_tool_loop(
                    data, messages, system, combined_tools, mcp_servers or None,
                    req.max_tokens,
                    browser_session_id, browser_credential_token,
                    response_text_parts := [],
                    tools_used,
                )
                for block in data.get("content", []):
                    btype = block.get("type", "")
                    if btype == "text":
                        response_text += block.get("text", "")
                    elif btype in ("tool_use", "mcp_tool_use"):
                        name = block.get("name", "unknown")
                        if name not in tools_used:
                            tools_used.append(name)
                # Include text collected during tool loop
                response_text = "".join(response_text_parts) + response_text
            finally:
                # Always clean up browser session if one was created
                if browser_session_id:
                    from agent.aetherbrowser_client import end_session as _end_browser
                    await _end_browser(browser_session_id)

            commitment_hash = _commitment_hash(response_text)

        await status_manager.agent_done(status_agent_id)

    except HTTPException:
        await status_manager.agent_done(status_agent_id, error="request failed")
        # Fire activity log (error) then re-raise
        asyncio.create_task(_activity_mod.log_activity(
            user_id=username,
            agent_id=routed_agent.agent_id if routed_agent else "direct",
            server_name=server_name,
            tool_name="chat",
            query_summary=_summarize_query(req.query),
            result_summary="",
            status="error",
            error="request failed",
        ))
        raise
    except Exception as exc:
        error_str = str(exc)
        await status_manager.agent_done(status_agent_id, error=error_str)
        asyncio.create_task(_activity_mod.log_activity(
            user_id=username,
            agent_id=routed_agent.agent_id if routed_agent else "direct",
            server_name=server_name,
            tool_name="chat",
            query_summary=_summarize_query(req.query),
            result_summary="",
            status="error",
            error=error_str,
        ))
        raise

    # ── Activity log (success) ─────────────────────────────────
    asyncio.create_task(_activity_mod.log_activity(
        user_id=username,
        agent_id=routed_agent.agent_id if routed_agent else "direct",
        server_name=server_name,
        tool_name=", ".join(tools_used) or "chat",
        query_summary=_summarize_query(req.query),
        result_summary=response_text[:240],
        status="ok",
    ))

    # ── Audit log ─────────────────────────────────────────────
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
                    "routed_via": routed_via,
                    "team_agent": routed_agent.agent_id if routed_agent else None,
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


@app.get("/audit/integrity")
async def audit_integrity(token: str = Depends(get_session_token)):
    """
    Verify audit log hash chain integrity and return current file hash.
    Used to detect tampering. Compare file_sha256 against VPS5 external snapshots.
    """
    if not svc.audit_log:
        raise HTTPException(status_code=503, detail="Audit log not initialized")

    import hashlib as _hl
    log_path = svc.audit_log.path

    # File hash
    h = _hl.sha256()
    try:
        with open(log_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        file_hash = h.hexdigest()
        file_size = log_path.stat().st_size
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot read audit log")

    # Chain integrity
    chain = svc.audit_log.verify_chain_integrity()

    # Last snapshot from local ledger
    last_snapshot = None
    try:
        ledger = log_path.parent / "audit_snapshots.jsonl"
        if ledger.exists():
            with open(ledger, "rb") as f:
                lines = [l for l in f.readlines() if l.strip()]
                if lines:
                    last_snapshot = json.loads(lines[-1])
    except Exception:
        pass

    return {
        "file_sha256": file_hash,
        "file_size_bytes": file_size,
        "chain_integrity": chain,
        "last_snapshot": last_snapshot,
        "timestamp": datetime.now().isoformat(),
    }


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


# ── Scan (POST — structured vault scan, session-auth + path-jail) ──
@app.post("/vault/scan")
async def scan_vault(
    request: VaultScanRequest,
    token: str = Depends(get_session_token),
):
    """
    Scan a real filesystem path and return structured vault data.

    Requires a valid session token. The supplied vault_path is forced
    through _safe_browse_path(), which rejects traversal, UNC, null-byte,
    and symlink-based escapes and confines the scan to the vault root or
    the user's home directory.
    """
    path = _safe_browse_path(request.vault_path)

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


# ── Browse (scan directory — session-authenticated, path-jailed) ──
def _safe_browse_path(raw_path: str) -> Path:
    """
    Resolve and validate a path for browse/scan endpoints.

    Restrictions (all must pass):
      * non-empty string, no null bytes
      * no UNC/SMB paths on Windows (\\\\host\\share, //host/share)
      * resolved canonical path must be inside an allowed root
      * leaf must not be a symlink (blocks symlink-escape from vault import)

    Allowed roots: DEFAULT_VAULT_ROOT (env-configurable), AETHER_VAULT_ROOT
    from env if set, and the current user's home directory.

    Raises HTTPException 400 on any violation.
    """
    import os as _os
    if not isinstance(raw_path, str) or not raw_path:
        raise HTTPException(status_code=400, detail="Invalid path")
    if "\x00" in raw_path:
        raise HTTPException(status_code=400, detail="Null byte in path")
    if _os.name == "nt" and (raw_path.startswith("\\\\") or raw_path.startswith("//")):
        raise HTTPException(status_code=400, detail="UNC / network paths are blocked")

    resolved = Path(raw_path).resolve()
    # Reject again after resolve — a crafted junction could normalize to a UNC.
    if _os.name == "nt" and str(resolved).startswith("\\\\"):
        raise HTTPException(status_code=400, detail="UNC / network paths are blocked")

    allowed_roots = [DEFAULT_VAULT_ROOT.resolve(), Path.home().resolve()]
    env_root = _os.getenv("AETHER_VAULT_ROOT")
    if env_root:
        try:
            allowed_roots.append(Path(env_root).resolve())
        except Exception:
            pass

    try:
        contained = any(
            resolved == root or resolved.is_relative_to(root)
            for root in allowed_roots
        )
    except AttributeError:
        # Python < 3.9 fallback
        contained = any(
            str(resolved).lower().startswith(str(root).lower() + _os.sep)
            or str(resolved).lower() == str(root).lower()
            for root in allowed_roots
        )
    if not contained:
        raise HTTPException(
            status_code=400,
            detail="Access denied: path must be within vault root or home directory",
        )

    # Symlink rejection at leaf (defense against vault-imported symlinks
    # that point to /etc or C:\Windows). lstat does not follow.
    try:
        if resolved.is_symlink():
            raise HTTPException(status_code=400, detail="Symbolic links are not allowed")
    except OSError:
        pass

    return resolved


@app.get("/vault/browse")
async def vault_browse(
    path: str = Query(default=None, description="Directory path to scan"),
    token: str = Depends(get_session_token),
):
    """
    Scan a directory and return its structure for the vault graph.
    Only names, sizes, extensions, modified dates — no file contents.

    Requires a valid session token. Candidate path is forced through
    _safe_browse_path() which rejects traversal, UNC, null-byte, and
    symlink-escape attempts.
    """
    raw_root = path or os.getenv("AETHER_VAULT_ROOT", str(DEFAULT_VAULT_ROOT))
    vault_path = _safe_browse_path(raw_root)

    if not vault_path.exists():
        return {"error": "Path does not exist", "folders": [], "files": [],
                "stats": {"total_files": 0, "total_folders": 0}}
    vault_root = str(vault_path)
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

    result = await execute_task(task)

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


# ── Interaction Style ─────────────────────────────


@app.post("/interaction/signal")
async def record_interaction_signal(request: Request, token: str = Depends(get_session_token)):
    """Record a user interaction style signal."""
    username = get_username_from_token(token)
    body = await request.json()
    signal_type = body.get("signal_type", "")
    metadata = body.get("metadata", {})

    profile = InteractionStyleProfile(username, _USER_DATA_DIR)
    profile.record_signal(signal_type, metadata)

    return {"recorded": True, "signal_type": signal_type, "dimensions": profile.dimensions}


@app.get("/interaction/style")
async def get_interaction_style(token: str = Depends(get_session_token)):
    """Get the user's current interaction style profile."""
    username = get_username_from_token(token)
    profile = InteractionStyleProfile(username, _USER_DATA_DIR)
    return profile.get_dimensions_dict()


# ── Per-Agent QOPC Learning ──────────────────────


@app.post("/agent/qopc/record")
async def qopc_agent_record(request: Request, token: str = Depends(get_session_token)):
    """Record a task outcome for per-agent QOPC learning."""
    username = get_username_from_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    body = await request.json()
    QOPCRegistry.record(
        agent_id=body.get("agent_id", ""),
        task_type=body.get("task_type", "analyze"),
        outcome=body.get("outcome", "success"),
        tokens=body.get("tokens", 0),
        tools_used=body.get("tools_used", []),
        duration_ms=body.get("duration_ms", 0),
        corrected=body.get("corrected", False),
    )
    return {"status": "recorded", "agent_id": body.get("agent_id")}


@app.get("/agent/qopc/weights/{agent_id}")
async def qopc_agent_weights(agent_id: str, token: str = Depends(get_session_token)):
    """Get QOPC weight summary for a specific agent."""
    username = get_username_from_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    return QOPCRegistry.get(agent_id).get_summary()


@app.get("/agent/qopc/all")
async def qopc_agent_all(token: str = Depends(get_session_token)):
    """Get QOPC weight summaries for all agents."""
    username = get_username_from_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"agents": QOPCRegistry.get_all_summaries()}


@app.post("/agent/qopc/rank")
async def qopc_agent_rank(request: Request, token: str = Depends(get_session_token)):
    """Rank agents by affinity for a task type. Used by orchestrator."""
    username = get_username_from_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    body = await request.json()
    ranked = QOPCRegistry.rank_agents_for_task(
        agent_ids=body.get("agent_ids", []),
        task_type=body.get("task_type", "analyze"),
    )
    return {"ranked": [{"agent_id": aid, "score": round(s, 3)} for aid, s in ranked]}


# ── Voice Styles ──────────────────────────────────


@app.get("/agent/voice/styles")
async def get_voice_styles(request: Request, token: str = Depends(get_session_token)):
    """Return all available voice styles for the frontend picker."""
    username = get_username_from_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {
        "styles": {
            k: {
                "label": v["label"],
                "description": v["description"],
                "traits": v["traits"],
                "example": v["example"],
            }
            for k, v in VOICE_STYLES.items()
        },
        "defaultsByIcon": DEFAULT_VOICE_BY_ICON,
    }


@app.post("/agent/voice/feedback")
async def voice_feedback(request: Request, token: str = Depends(get_session_token)):
    """Record style satisfaction signal from user interaction."""
    username = get_username_from_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    body = await request.json()
    agent_id = body.get("agent_id", "")
    satisfaction = body.get("satisfaction", "neutral")
    if agent_id:
        QOPCRegistry.get(agent_id).record_style_feedback(satisfaction)
    return {"status": "ok"}


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

    # Protocol-C status — cached with 30s TTL
    now = time.time()
    if now > _protocol_c_cache["expires"]:
        if _PROTOCOL_VARIANT == "C":
            _protocol_c_cache["value"] = "CSPRNG"
        else:
            try:
                from aether_protocol.quantum_crypto import get_quantum_seed
                _, method = get_quantum_seed()
                _protocol_c_cache["value"] = method
            except Exception:
                _protocol_c_cache["value"] = "OS_URANDOM"
        _protocol_c_cache["expires"] = now + 30.0

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

    # License info
    _lic_status = None
    try:
        from license_client import get_license_info
        _li = get_license_info()
        if _li:
            _lic_status = LicenseStatus(
                valid=_li.get("valid", False),
                plan=_li.get("plan"),
                expires_at=_li.get("expires_at"),
                grace_mode=_li.get("grace_mode", False),
            )
    except Exception:
        pass

    return StatusResponse(
        protocol_c="ACTIVE",
        watcher=watcher_status,
        agent=agent_status,
        read_detector=read_detector_status,
        session_active=session_active,
        vault_root=str(DEFAULT_VAULT_ROOT),
        uptime=round(time.time() - _start_time, 1),
        version=APP_VERSION,
        needs_setup=needs_setup,
        license=_lic_status,
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
        "ip": os.environ.get("AETHER_VPS2_IP", "unknown"),
        "port": int(os.environ.get("AETHER_BIND_PORT", 8080)),
        "protocol_c": "ACTIVE",
        "anthropic_key_set": bool(get_anthropic_key()),
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
# AGENT PERSISTENCE ENDPOINTS
# ═══════════════════════════════════════════════════

class CustomAgentRequest(BaseModel):
    id: Optional[str] = None
    name: str
    icon: str = "robot"
    system_prompt: str = ""
    description: str = ""
    voice: str = "warm"
    tasks: Optional[list] = []
    mcp_servers: Optional[list] = []
    requires_browser_sandbox: bool = False


@app.get("/agent/custom")
async def list_custom_agents(token: str = Depends(get_session_token)):
    """List all custom agents for the current user (persistent across launches)."""
    username = get_username_from_token(token)
    persistence = AgentPersistence(username)
    agents = persistence.list_custom_agents()
    return {"agents": agents, "count": len(agents)}


@app.post("/agent/custom")
async def save_custom_agent(
    req: CustomAgentRequest,
    token: str = Depends(get_session_token),
):
    """Create or update a custom agent. Persists across app launches."""
    username = get_username_from_token(token)

    # Guard: scan custom system prompt for injection
    if req.system_prompt:
        guard = get_prompt_guard(svc.audit_log)
        scan = guard.scan_system_prompt(req.system_prompt)
        if scan.is_blocked:
            raise HTTPException(
                status_code=403,
                detail="Custom agent system prompt blocked — injection patterns detected.",
            )

    persistence = AgentPersistence(username)
    agent = persistence.save_custom_agent({
        "id": req.id,
        "name": req.name,
        "icon": req.icon,
        "system_prompt": req.system_prompt,
        "description": req.description,
        "voice": req.voice,
        "tasks": req.tasks or [],
        "mcp_servers": req.mcp_servers or [],
        "requires_browser_sandbox": req.requires_browser_sandbox,
    })
    return {"ok": True, "agent": agent}


@app.delete("/agent/custom/{agent_id}")
async def delete_custom_agent(
    agent_id: str,
    token: str = Depends(get_session_token),
):
    """Delete a custom agent and its persistent memory."""
    username = get_username_from_token(token)
    persistence = AgentPersistence(username)
    deleted = persistence.delete_custom_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"ok": True, "deleted": agent_id}


@app.post("/agent/custom/{agent_id}/tool")
async def record_agent_tool_selection(
    agent_id: str,
    request: Request,
    token: str = Depends(get_session_token),
):
    """Record that a user selected an MCP tool for a specific agent.
    Persists so the agent remembers its tools across launches."""
    username = get_username_from_token(token)
    body = await request.json()
    tool_name = body.get("tool", "")
    mcp_server = body.get("mcp_server", "")
    if not tool_name:
        raise HTTPException(status_code=400, detail="tool name required")
    persistence = AgentPersistence(username)
    persistence.record_tool_selection(agent_id, tool_name, mcp_server)
    return {"ok": True, "agent_id": agent_id, "tool": tool_name}


@app.delete("/agent/custom/{agent_id}/tool")
async def remove_agent_tool_selection(
    agent_id: str,
    request: Request,
    token: str = Depends(get_session_token),
):
    """Remove a tool selection from an agent's persistent memory."""
    username = get_username_from_token(token)
    body = await request.json()
    tool_name = body.get("tool", "")
    mcp_server = body.get("mcp_server", "")
    persistence = AgentPersistence(username)
    persistence.remove_tool_selection(agent_id, tool_name, mcp_server)
    return {"ok": True}


@app.get("/agent/custom/{agent_id}/memory")
async def get_agent_memory(
    agent_id: str,
    token: str = Depends(get_session_token),
):
    """Get all persistent memory for a specific agent."""
    username = get_username_from_token(token)
    persistence = AgentPersistence(username)
    memory = persistence.get_agent_memory(agent_id)
    return {"agent_id": agent_id, "memory": memory}


@app.post("/agent/custom/{agent_id}/memory")
async def set_agent_memory_entry(
    agent_id: str,
    request: Request,
    token: str = Depends(get_session_token),
):
    """Set a key-value pair in an agent's persistent memory."""
    username = get_username_from_token(token)
    body = await request.json()
    key = body.get("key", "")
    value = body.get("value")
    if not key:
        raise HTTPException(status_code=400, detail="key required")
    persistence = AgentPersistence(username)
    persistence.set_agent_memory(agent_id, key, value)
    return {"ok": True}


@app.get("/agent/persistence/export")
async def export_agent_data(token: str = Depends(get_session_token)):
    """Export all agent data (custom agents, teams, memory) for backup."""
    username = get_username_from_token(token)
    persistence = AgentPersistence(username)
    data = persistence.export_all()
    return data


@app.post("/agent/persistence/import")
async def import_agent_data(
    request: Request,
    token: str = Depends(get_session_token),
):
    """Import agent data from a backup."""
    username = get_username_from_token(token)
    body = await request.json()
    persistence = AgentPersistence(username)
    result = persistence.import_all(body)
    return {"ok": True, "imported": result}


# ── Prompt Guard Stats ───────────────────────────
@app.get("/security/prompt-guard/stats")
async def prompt_guard_stats(token: str = Depends(get_session_token)):
    """Return prompt guard statistics (scans, blocks, block rate)."""
    guard = get_prompt_guard(svc.audit_log)
    return guard.stats


# ═══════════════════════════════════════════════════
# LICENSE VALIDATION (backend for license.aethersystems.net)
# ═══════════════════════════════════════════════════
# Desktop clients POST here at startup to verify their AETH-CLD-* key.
# Cloudflare Tunnel for license.aethersystems.net forwards to this host
# with NO path rewriting — FastAPI sees the full path as the client
# constructs it. See: license_client.py, desktop/main.js, Sequence 1 brief.


class LicenseValidateRequest(BaseModel):
    key: str
    # Reserved for future client-version gating. Accepted but currently unused.
    version: Optional[str] = None


async def _handle_license_validate(req: LicenseValidateRequest):
    """Shared handler for the legacy and v2 license-validate paths.

    Both routes delegate here. The legacy path is retained indefinitely as
    a shim for existing desktop installs; v2 is the path new desktop
    releases will migrate to.
    """
    from fastapi.responses import JSONResponse
    try:
        return validate_license(req.key)
    except MalformedKeyError:
        return JSONResponse(status_code=400, content={"error": "malformed_key"})
    except UpstreamError:
        return JSONResponse(status_code=500, content={"error": "upstream_error"})


# Legacy path. Matches the URL license_client.py:81 constructs today
# (double /license/ is intentional — a quirk in the client's URL assembly
# that we match on the server instead of changing the client).
@app.post("/api/license/license/cloud/validate")
@limiter.limit("10/hour")
async def license_validate_legacy(
    request: Request,
    req: LicenseValidateRequest,
):
    """License validation — legacy path. Kept for existing desktop installs."""
    return await _handle_license_validate(req)


# Clean path for future desktop releases. Same handler, same contract —
# exists so new desktop versions don't have to carry the legacy URL
# quirk. Both paths must coexist until telemetry confirms no traffic on
# the legacy path, then the legacy handler can be removed.
@app.post("/api/license/v2/validate")
@limiter.limit("10/hour")
async def license_validate_v2(
    request: Request,
    req: LicenseValidateRequest,
):
    """License validation — clean v2 path. Identical contract to legacy."""
    return await _handle_license_validate(req)


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
