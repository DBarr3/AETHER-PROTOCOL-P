"""
aether_protocol/server.py

Hardened FastAPI REST wrapper for the AETHER-PROTOCOL quantum trade protocol.

Exposes the full protocol lifecycle (seed -> commit -> execute -> settle)
plus audit log querying and verification over HTTP.

Security:
    - API key authentication via X-Aether-Key header (all endpoints except /health)
    - Per-IP rate limiting (in-memory token bucket)
    - CORS with explicit allow-list (internal only)
    - Bind to 127.0.0.1 only — deploy behind nginx reverse proxy

Start the server::

    export AETHER_API_KEY="your-secret-key"
    pip install -e ".[server]"
    aether-server          # listens on 127.0.0.1:8765
"""

from __future__ import annotations

import collections
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

# Protocol variant: "C" = CSPRNG (default), "L" = quantum
PROTOCOL_VARIANT = os.getenv("AETHER_PROTOCOL_VARIANT", "C")

# ── Suppress qiskit_ibm_runtime INFO/WARNING spam ─────────────────────────
if PROTOCOL_VARIANT == "L":
    logging.getLogger('qiskit_ibm_runtime').setLevel(logging.ERROR)
    logging.getLogger('qiskit_ibm_provider').setLevel(logging.ERROR)

from .async_protocol import AsyncQuantumProtocol
from .audit import PHASE_COMMITMENT, PHASE_EXECUTION, PHASE_SETTLEMENT
from .commitment import ReasoningCapture
from .quantum_backend import QuantumSeedResult, get_pool_status
from .terminal_ui import get_console
from .timestamp_authority import (
    RFC3161TimestampAuthority,
    TimestampToken,
    TimestampError,
)

try:
    from fastapi import FastAPI, HTTPException, Query, Depends, Request
    from fastapi.responses import JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, field_validator
except ImportError as _exc:
    raise ImportError(
        "FastAPI is required for the REST server.  "
        "Install with:  pip install aether-protocol-l[server]"
    ) from _exc

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────

_API_KEY = os.environ.get("AETHER_API_KEY")

# Protocol-C/L server is internal only. Never add external domains here.
# Browsers do not call it directly — AetherCloud does, server-side.
_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "AETHER_ALLOWED_ORIGINS",
        "http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if o.strip() and "aethersecurity.net" not in o
]

if not _API_KEY:
    logger.warning(
        "WARNING: AETHER_API_KEY not set — server running without authentication"
    )


# ── Rate limiter (in-memory token bucket) ────────────────────────────

class _RateLimiter:
    """Simple in-memory per-IP rate limiter using sliding window."""

    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = collections.defaultdict(list)

    def _clean(self, ip: str, window: float) -> None:
        cutoff = time.monotonic() - window
        self._requests[ip] = [t for t in self._requests[ip] if t > cutoff]

    def check(self, ip: str, limit: int, window: float = 60.0) -> bool:
        """Return True if request is allowed, False if rate limited."""
        now = time.monotonic()
        self._clean(ip, window)
        if len(self._requests[ip]) >= limit:
            return False
        self._requests[ip].append(now)
        return True


_rate_limiter = _RateLimiter()

# Per-IP limits per 60-second window
_GENERAL_LIMIT = 60   # all endpoints
_COMMIT_LIMIT = 10    # /commit, /execute, /settle


# ── Auth dependency ──────────────────────────────────────────────────

async def _require_auth(request: Request):
    """Dependency that enforces API key authentication."""
    if not _API_KEY:
        return  # No key configured — running open (dev mode)

    provided = request.headers.get("X-Aether-Key", "")
    if provided != _API_KEY:
        client_ip = request.client.host if request.client else "unknown"
        logger.warning("AUTH DENIED: invalid key from %s on %s", client_ip, request.url.path)
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def _rate_limit_general(request: Request):
    """General rate limit: 60 req/min/IP."""
    client_ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.check(client_ip, _GENERAL_LIMIT):
        logger.warning("RATE LIMITED: %s exceeded %d req/min", client_ip, _GENERAL_LIMIT)
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


async def _rate_limit_commit(request: Request):
    """Commit rate limit: 10 req/min/IP on write endpoints."""
    client_ip = request.client.host if request.client else "unknown"
    if not _rate_limiter.check(client_ip + ":commit", _COMMIT_LIMIT):
        logger.warning("RATE LIMITED: %s exceeded %d commit req/min", client_ip, _COMMIT_LIMIT)
        raise HTTPException(status_code=429, detail="Commit rate limit exceeded")


# ── Pydantic request / response models ──────────────────────────────

class SeedRequest(BaseModel):
    method: str = "OS_URANDOM"


class SeedResponse(BaseModel):
    seed_hash: str
    method: str
    backend_name: str
    timestamp: int
    n_qubits: int


class CommitRequest(BaseModel):
    seed_hash: str
    order_id: str
    trade_details: dict
    account_state: dict
    reasoning_text: Optional[str] = None
    reasoning_model: Optional[str] = None
    reasoning_token_count: Optional[int] = None

    @field_validator("order_id")
    @classmethod
    def order_id_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("order_id must be 1-255 characters")
        return v


class ReasoningVerifyRequest(BaseModel):
    reasoning_text: str
    reasoning_hash: str


class TimestampVerifyRequest(BaseModel):
    data_hex: str
    token: dict


class ExecuteRequest(BaseModel):
    seed_hash: str
    order_id: str
    commitment: dict
    commitment_sig: dict
    filled_qty: float
    fill_price: float
    new_account_state: dict
    execution_timestamp: Optional[int] = None
    broker_response: dict = {}

    @field_validator("order_id")
    @classmethod
    def order_id_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("order_id must be 1-255 characters")
        return v


class SettleRequest(BaseModel):
    seed_hash: str
    order_id: str
    commitment: dict
    commitment_sig: dict
    attestation: dict
    attestation_sig: dict
    broker_sig: str

    @field_validator("order_id")
    @classmethod
    def order_id_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 255:
            raise ValueError("order_id must be 1-255 characters")
        return v


# ── Application state ───────────────────────────────────────────────

_protocol: Optional[AsyncQuantumProtocol] = None
_seed_cache: dict[str, QuantumSeedResult] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise protocol on startup, clean up on shutdown."""
    global _protocol
    log_path = os.environ.get("AETHER_LOG_PATH", "audit.jsonl")
    # Default seed method depends on protocol variant
    default_seed = "CSPRNG" if PROTOCOL_VARIANT == "C" else "OS_URANDOM"
    seed_method = os.environ.get("AETHER_SEED_METHOD", default_seed)
    max_mb = int(os.environ.get("AETHER_MAX_LOG_MB", "100"))
    _protocol = AsyncQuantumProtocol(
        log_path=log_path,
        seed_method=seed_method,
        max_file_size_mb=max_mb,
    )
    yield
    _protocol = None
    _seed_cache.clear()


app = FastAPI(
    title="AETHER-PROTOCOL",
    version="0.6.0",
    description="Quantum-authenticated decision protocol REST API",
    lifespan=lifespan,
)

# CORS — internal only. Never add external domains here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["X-Aether-Key", "Content-Type"],
)


def _get_protocol() -> AsyncQuantumProtocol:
    """Return the active protocol instance (raises 503 if not ready)."""
    if _protocol is None:
        raise HTTPException(503, "Protocol not initialised")
    return _protocol


# ── Health endpoint (no auth) ────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check — no auth required so nginx can probe it."""
    return {
        "status": "healthy",
        "version": "0.6.0",
        "protocol_variant": PROTOCOL_VARIANT,
        "authenticated": _API_KEY is not None,
        "timestamp": int(time.time()),
    }


# ── Seed endpoint ────────────────────────────────────────────────────

@app.post("/seed", response_model=SeedResponse,
          dependencies=[Depends(_require_auth), Depends(_rate_limit_general)])
async def create_seed(req: SeedRequest):
    """Generate a quantum seed and cache it for subsequent operations."""
    proto = _get_protocol()
    seed = await proto.get_seed(method=req.method)
    _seed_cache[seed.seed_hash] = seed
    return SeedResponse(
        seed_hash=seed.seed_hash,
        method=seed.method,
        backend_name=seed.backend_name,
        timestamp=seed.timestamp,
        n_qubits=seed.n_qubits,
    )


def _pop_seed(seed_hash: str) -> QuantumSeedResult:
    """Consume a cached seed (one-time use)."""
    seed = _seed_cache.pop(seed_hash, None)
    if seed is None:
        raise HTTPException(404, "Seed not found or already consumed")
    return seed


# ── Commit endpoint ──────────────────────────────────────────────────

@app.post("/commit",
          dependencies=[Depends(_require_auth), Depends(_rate_limit_general), Depends(_rate_limit_commit)])
async def commit(req: CommitRequest):
    """Create a quantum decision commitment."""
    proto = _get_protocol()
    seed = _pop_seed(req.seed_hash)

    reasoning = None
    if req.reasoning_text is not None:
        reasoning = ReasoningCapture.from_text(
            text=req.reasoning_text,
            model=req.reasoning_model or "human",
            token_count=req.reasoning_token_count,
        )

    c_dict, c_sig = await proto.commit(
        seed,
        {
            "order_id": req.order_id,
            "trade_details": req.trade_details,
            "account_state": req.account_state,
        },
        reasoning=reasoning,
    )
    result: dict[str, Any] = {"commitment": c_dict, "signature": c_sig}
    if reasoning is not None:
        result["reasoning"] = reasoning.to_dict()
    return result


# ── Execute endpoint ─────────────────────────────────────────────────

@app.post("/execute",
          dependencies=[Depends(_require_auth), Depends(_rate_limit_general), Depends(_rate_limit_commit)])
async def execute(req: ExecuteRequest):
    """Create a quantum execution attestation."""
    proto = _get_protocol()
    seed = _pop_seed(req.seed_hash)
    att_dict, att_sig = await proto.execute(
        seed,
        req.commitment,
        req.commitment_sig,
        {
            "order_id": req.order_id,
            "filled_qty": req.filled_qty,
            "fill_price": req.fill_price,
            "new_account_state": req.new_account_state,
            "execution_timestamp": req.execution_timestamp,
            "broker_response": req.broker_response,
        },
    )
    return {"attestation": att_dict, "signature": att_sig}


# ── Settle endpoint ──────────────────────────────────────────────────

@app.post("/settle",
          dependencies=[Depends(_require_auth), Depends(_rate_limit_general), Depends(_rate_limit_commit)])
async def settle(req: SettleRequest):
    """Create a quantum settlement record."""
    proto = _get_protocol()
    seed = _pop_seed(req.seed_hash)
    s_dict, s_sig = await proto.settle(
        seed,
        req.commitment,
        req.commitment_sig,
        req.attestation,
        req.attestation_sig,
        {"order_id": req.order_id, "broker_sig": req.broker_sig},
    )
    return {"settlement": s_dict, "signature": s_sig}


# ── Reasoning verification endpoint ──────────────────────────────────

@app.post("/reasoning/verify",
          dependencies=[Depends(_require_auth), Depends(_rate_limit_general)])
async def verify_reasoning(req: ReasoningVerifyRequest):
    """Verify that a reasoning hash matches the reasoning text."""
    import hashlib
    expected = hashlib.sha256(req.reasoning_text.encode("utf-8")).hexdigest()
    valid = expected == req.reasoning_hash
    return {
        "valid": valid,
        "expected_hash": expected,
        "provided_hash": req.reasoning_hash,
    }


# ── Timestamp verification endpoint ─────────────────────────────────

@app.post("/timestamp/verify",
          dependencies=[Depends(_require_auth), Depends(_rate_limit_general)])
async def verify_timestamp(req: TimestampVerifyRequest):
    """Verify that a timestamp token matches the given data."""
    try:
        data = bytes.fromhex(req.data_hex)
    except ValueError:
        raise HTTPException(400, "data_hex must be valid hex")
    try:
        token = TimestampToken.from_dict(req.token)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, f"Invalid token: {exc}")
    tsa = RFC3161TimestampAuthority()
    valid = tsa.verify(data, token)
    return {"valid": valid, "message_imprint": token.message_imprint}


# ── Audit query endpoints ────────────────────────────────────────────

@app.get("/audit",
         dependencies=[Depends(_require_auth), Depends(_rate_limit_general)])
async def query_audit(
    record_type: Optional[str] = Query(None),
    since: Optional[float] = Query(None),
    until: Optional[float] = Query(None),
    seed_method: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=10000),
):
    """Query the audit log with optional filters."""
    proto = _get_protocol()
    records = await proto.query_log(
        record_type=record_type,
        since=since,
        until=until,
        seed_method=seed_method,
        limit=limit,
    )
    return {"records": records, "count": len(records)}


@app.get("/audit/chain-integrity",
         dependencies=[Depends(_require_auth), Depends(_rate_limit_general)])
async def audit_chain_integrity():
    """Verify audit log hash chain integrity."""
    proto = _get_protocol()
    result = proto._audit_log.verify_chain_integrity()
    return result


@app.get("/audit/{record_id}",
         dependencies=[Depends(_require_auth), Depends(_rate_limit_general)])
async def get_record(record_id: str):
    """Retrieve a single audit record by ID."""
    proto = _get_protocol()
    record = await proto.get_record(record_id)
    if record is None:
        raise HTTPException(404, f"Record not found: {record_id}")
    return record


@app.get("/audit/{record_id}/verify",
         dependencies=[Depends(_require_auth), Depends(_rate_limit_general)])
async def verify_record(record_id: str):
    """Verify the trade flow containing this record."""
    proto = _get_protocol()

    # Extract order_id from record_id by stripping known phase suffixes
    order_id: Optional[str] = None
    for phase in (PHASE_COMMITMENT, PHASE_EXECUTION, PHASE_SETTLEMENT):
        suffix = f"_{phase}"
        if record_id.endswith(suffix):
            order_id = record_id[: -len(suffix)]
            break

    if order_id is None:
        raise HTTPException(
            400,
            "Cannot extract order_id from record_id.  "
            "Expected format: <order_id>_<PHASE>",
        )

    result = await proto.verify(order_id)
    return {
        "record_id": record_id,
        "valid": result.get("chain_valid", False),
        "checked_at": time.time(),
        "details": result,
    }


@app.get("/audit/{record_id}/report",
         dependencies=[Depends(_require_auth), Depends(_rate_limit_general)])
async def get_report(record_id: str):
    """Generate a PDF dispute report for the trade flow containing this record."""
    from fastapi.responses import Response

    proto = _get_protocol()

    # Extract order_id from record_id
    order_id: Optional[str] = None
    for phase in (PHASE_COMMITMENT, PHASE_EXECUTION, PHASE_SETTLEMENT):
        suffix = f"_{phase}"
        if record_id.endswith(suffix):
            order_id = record_id[: -len(suffix)]
            break

    if order_id is None:
        raise HTTPException(
            400,
            "Cannot extract order_id from record_id.  "
            "Expected format: <order_id>_<PHASE>",
        )

    try:
        pdf_bytes = await proto.generate_dispute_report(order_id)
    except ImportError as exc:
        raise HTTPException(
            501,
            "PDF generation requires reportlab.  "
            "Install with:  pip install aether-protocol-l[compliance]",
        ) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{order_id}_dispute_report.pdf"'
            )
        },
    )


# ── Status endpoint ──────────────────────────────────────────────────

@app.get("/status",
         dependencies=[Depends(_require_auth), Depends(_rate_limit_general)])
async def status():
    """Return server and protocol status."""
    proto = _get_protocol()
    log_path = proto._audit_log.path

    log_size_mb = 0.0
    record_count = 0
    if log_path.exists():
        log_size_mb = round(log_path.stat().st_size / (1024 * 1024), 3)
        record_count = proto._audit_log._line_count

    return {
        "version": "0.6.0",
        "protocol_variant": PROTOCOL_VARIANT,
        "pool": get_pool_status(),
        "log": {
            "current_file": str(log_path.name),
            "size_mb": log_size_mb,
            "record_count": record_count,
            "archives": proto._audit_log.list_archives(),
        },
    }


# ── CLI entry point ──────────────────────────────────────────────────

def run():
    """Start the AETHER-PROTOCOL server (called by ``aether-server``)."""
    import uvicorn

    # Deploy behind nginx reverse proxy — do not expose directly
    host = os.environ.get("AETHER_HOST", "127.0.0.1")
    port = int(os.environ.get("AETHER_PORT", "8765"))
    default_seed = "CSPRNG" if PROTOCOL_VARIANT == "C" else "OS_URANDOM"
    seed_method = os.environ.get("AETHER_SEED_METHOD", default_seed)
    log_path = os.environ.get("AETHER_LOG_PATH", "audit.jsonl")

    # ── Retro terminal boot banner ──
    ui = get_console()
    ui.boot_banner(
        version="0.6.0",
        seed_method=seed_method,
        log_path=log_path,
        host=host,
        port=port,
    )

    uvicorn.run(
        "aether_protocol.server:app",
        host=host,
        port=port,
        reload=False,
    )
