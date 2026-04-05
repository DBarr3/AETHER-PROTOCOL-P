"""
Aether MCP Worker — FastAPI Service (VPS5)
Standalone MCP agent execution service on port 8095.
Accepts signed requests from VPS2 only.

Aether Systems LLC — Patent Pending
"""

import json
import logging
import os
import time
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

from mcp_worker.node_auth import NodeAuth
from mcp_worker.agent_executor import AgentExecutor
from mcp_worker.protocol_c_wrapper import MCPProtocolC
from mcp_worker.breach_alerter import BreachAlerter

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("aether.mcp.server")

node_auth: Optional[NodeAuth] = None
executor: Optional[AgentExecutor] = None
protocol_c: Optional[MCPProtocolC] = None
alerter: Optional[BreachAlerter] = None


class ExecuteRequest(BaseModel):
    task_id: str
    client_id: str
    agent_type: str = "mcp"
    mcp_server_url: str = ""
    prompt: str = ""
    context: str = ""
    protocol_c_pre: str = ""


class ExecuteResponse(BaseModel):
    task_id: str
    result: str
    tools_used: list = []
    protocol_c_post: str = ""
    vps5_signature: str = ""
    executed_at: str = ""
    execution_ms: int = 0
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    node: str = "VPS5"
    agents: list = []
    active_tasks: int = 0
    total_executions: int = 0


@asynccontextmanager
async def lifespan(application: FastAPI):
    global node_auth, executor, protocol_c, alerter
    vps5_key = os.getenv("VPS5_NODE_KEY_PATH", "/opt/aether-mcp/certs/VPS5.key")
    vps2_pub = os.getenv("VPS2_PUB_KEY_PATH", "/opt/aether-mcp/certs/VPS2.pub")
    node_auth = NodeAuth(node_id="VPS5", private_key_path=vps5_key, trusted_peers={"VPS2": vps2_pub})
    executor = AgentExecutor()
    protocol_c = MCPProtocolC()
    alerter = BreachAlerter(node_auth=node_auth)
    logger.info("═══════════════════════════════════════════════════")
    logger.info("  MCP WORKER ONLINE — node=VPS5 trusted_peers=[VPS2]")
    logger.info("  Agents: %s", list(executor.get_stats()["agents"]))
    logger.info("═══════════════════════════════════════════════════")
    yield
    logger.info("MCP Worker shutting down")


app = FastAPI(title="Aether MCP Worker", version="1.0.0", lifespan=lifespan)


async def verify_vps2_request(request: Request):
    if not node_auth:
        raise HTTPException(503, detail="Node auth not initialized")
    body = await request.body()
    try:
        node_auth.verify_request(dict(request.headers), body)
    except ValueError as e:
        logger.warning("Auth rejected: %s", e)
        raise HTTPException(401, detail=str(e))


@app.get("/health", response_model=HealthResponse)
async def health():
    stats = executor.get_stats() if executor else {}
    return HealthResponse(status="ok", node="VPS5", agents=stats.get("agents", []), active_tasks=stats.get("active_tasks", 0), total_executions=stats.get("total_executions", 0))


# ── Audit Snapshot Receiver ──────────────────────────────────────────
# Accepts periodic audit log integrity snapshots from VPS2 over Tailscale.
# Stores them locally so VPS2's log can be verified against an external anchor.

_SNAPSHOT_STORE = Path(os.getenv("AETHER_SNAPSHOT_STORE", "/opt/aether-mcp/data/audit_snapshots.jsonl"))
_MCP_ALERT_KEY  = os.getenv("MCP_ALERT_KEY", "")

@app.post("/audit/snapshot")
async def receive_audit_snapshot(request: Request):
    """Receive and store an audit log integrity snapshot from VPS2."""
    # Verify shared key
    incoming_key = request.headers.get("X-Aether-Alert-Key", "")
    if _MCP_ALERT_KEY and incoming_key != _MCP_ALERT_KEY:
        raise HTTPException(status_code=403, detail="Invalid alert key")

    try:
        snapshot = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Add receipt timestamp
    snapshot["received_at"] = time.time()
    snapshot["stored_by"] = "VPS5"

    # Append to local store
    _SNAPSHOT_STORE.parent.mkdir(parents=True, exist_ok=True)
    with open(_SNAPSHOT_STORE, "a") as f:
        f.write(json.dumps(snapshot) + "\n")

    logger.info(
        "Audit snapshot received from VPS2 — entries=%s chain_valid=%s sha256=%s...%s",
        snapshot.get("chain_integrity", {}).get("total_entries", "?"),
        snapshot.get("chain_integrity", {}).get("chain_valid", "?"),
        snapshot.get("file_sha256", "")[:8],
        snapshot.get("file_sha256", "")[-8:],
    )
    return {"status": "stored", "received_at": snapshot["received_at"]}


@app.get("/audit/snapshots")
async def list_audit_snapshots(request: Request):
    """Return stored audit snapshots. VPS2-only via alert key."""
    incoming_key = request.headers.get("X-Aether-Alert-Key", "")
    if _MCP_ALERT_KEY and incoming_key != _MCP_ALERT_KEY:
        raise HTTPException(status_code=403, detail="Invalid alert key")

    snapshots = []
    if _SNAPSHOT_STORE.exists():
        with open(_SNAPSHOT_STORE, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        snapshots.append(json.loads(line))
                    except Exception:
                        continue
    return {"count": len(snapshots), "snapshots": snapshots[-20:]}  # last 20


@app.post("/agent/execute", response_model=ExecuteResponse)
async def execute_agent(request: Request):
    await verify_vps2_request(request)
    body = await request.body()
    task = json.loads(body)
    task_id = task.get("task_id", str(uuid.uuid4()))
    task["task_id"] = task_id

    pre_hash = protocol_c.commit_pre_execution(task)
    result = await executor.execute(task)
    execution_ms = result.get("execution_ms", 0)
    result_text = result.get("result", "")
    error = result.get("error")

    post_hash = protocol_c.commit_post_execution(task, result_text or str(error), pre_hash, execution_ms)

    anomaly = executor.detect_anomaly(task, result)
    if anomaly and anomaly.get("anomaly"):
        anomaly_hash = protocol_c.commit_anomaly(task, anomaly)
        if alerter:
            await alerter.send_alert(anomaly["severity"], task.get("client_id", ""), task_id, anomaly["reason"], anomaly_hash)
        if anomaly.get("recommend_block"):
            breach_hash = protocol_c.commit_breach(task, anomaly["reason"])
            if alerter:
                await alerter.send_critical(task.get("client_id", ""), task_id, anomaly["reason"], breach_hash)

    response_body = json.dumps({"task_id": task_id, "result": result_text, "protocol_c_post": post_hash}).encode()
    vps5_sig = ""
    try:
        vps5_sig = node_auth.sign_response(response_body)
    except Exception:
        pass

    return ExecuteResponse(task_id=task_id, result=result_text, tools_used=result.get("tools_used", []), protocol_c_post=post_hash, vps5_signature=vps5_sig, executed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), execution_ms=execution_ms, error=error)


@app.post("/agent/breach-test")
async def breach_test(request: Request):
    await verify_vps2_request(request)
    test_task = {"task_id": f"breach-test-{int(time.time())}", "client_id": "breach-test", "agent_type": "gmail", "prompt": "list my emails", "context": ""}
    result = await executor.execute(test_task)
    return {"test": "breach_self_test", "mcp_rejected_unauthorized": bool(result.get("error")), "details": result.get("error", "No error"), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


if __name__ == "__main__":
    port = int(os.getenv("MCP_WORKER_PORT", "8095"))
    uvicorn.run("mcp_worker.server:app", host="0.0.0.0", port=port, log_level="info")
