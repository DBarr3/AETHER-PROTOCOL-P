"""
aether_protocol/server.py

FastAPI REST wrapper for the AETHER-PROTOCOL-L quantum trade protocol.

Exposes the full protocol lifecycle (seed → commit → execute → settle)
plus audit log querying and verification over HTTP.

Start the server::

    pip install -e ".[server]"
    aether-server          # listens on 0.0.0.0:8765

Or programmatically::

    from aether_protocol.server import app
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

import logging

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
    from fastapi import FastAPI, HTTPException, Query
    from pydantic import BaseModel
except ImportError as _exc:
    raise ImportError(
        "FastAPI is required for the REST server.  "
        "Install with:  pip install aether-protocol-l[server]"
    ) from _exc


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


class SettleRequest(BaseModel):
    seed_hash: str
    order_id: str
    commitment: dict
    commitment_sig: dict
    attestation: dict
    attestation_sig: dict
    broker_sig: str


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
    title="AETHER-PROTOCOL-L",
    version="0.5.1",
    description="Quantum-authenticated decision protocol REST API",
    lifespan=lifespan,
)


def _get_protocol() -> AsyncQuantumProtocol:
    """Return the active protocol instance (raises 503 if not ready)."""
    if _protocol is None:
        raise HTTPException(503, "Protocol not initialised")
    return _protocol


# ── Seed endpoint ────────────────────────────────────────────────────

@app.post("/seed", response_model=SeedResponse)
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

@app.post("/commit")
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

@app.post("/execute")
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

@app.post("/settle")
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

@app.post("/reasoning/verify")
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

@app.post("/timestamp/verify")
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

@app.get("/audit")
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


@app.get("/audit/{record_id}")
async def get_record(record_id: str):
    """Retrieve a single audit record by ID."""
    proto = _get_protocol()
    record = await proto.get_record(record_id)
    if record is None:
        raise HTTPException(404, f"Record not found: {record_id}")
    return record


@app.get("/audit/{record_id}/verify")
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


@app.get("/audit/{record_id}/report")
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

@app.get("/status")
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
        "version": "0.5.1",
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
    """Start the AETHER-PROTOCOL-L server (called by ``aether-server``)."""
    import uvicorn

    host = os.environ.get("AETHER_HOST", "0.0.0.0")
    port = int(os.environ.get("AETHER_PORT", "8765"))
    default_seed = "CSPRNG" if PROTOCOL_VARIANT == "C" else "OS_URANDOM"
    seed_method = os.environ.get("AETHER_SEED_METHOD", default_seed)
    log_path = os.environ.get("AETHER_LOG_PATH", "audit.jsonl")

    # ── Retro terminal boot banner ──
    ui = get_console()
    ui.boot_banner(
        version="0.5.1",
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
