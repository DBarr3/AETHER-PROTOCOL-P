"""
Aether MCP Worker — Protocol-C Wrapper
Wraps every MCP call with cryptographic commitments (pre + post execution).

Aether Systems LLC — Patent Pending
"""

import hashlib
import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger("aether.mcp.protocolc")


class MCPProtocolC:
    def __init__(self, audit_path="/opt/aether-mcp/data/mcp_audit.jsonl"):
        self._audit_path = audit_path
        self._lock = threading.Lock()
        self._chain_hash = "0" * 64
        Path(audit_path).parent.mkdir(parents=True, exist_ok=True)

    def _compute_hash(self, data):
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _append_record(self, record):
        record["chain_prev"] = self._chain_hash
        record_hash = self._compute_hash(record)
        record["commitment_hash"] = record_hash
        self._chain_hash = record_hash
        with self._lock:
            with open(self._audit_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        return record_hash

    def commit_pre_execution(self, task):
        record = {
            "event": "MCP_PRE_EXECUTION",
            "task_id": task.get("task_id", ""),
            "client_id": task.get("client_id", ""),
            "agent_type": task.get("agent_type", ""),
            "mcp_server": task.get("mcp_server_url", ""),
            "prompt_hash": hashlib.sha256(task.get("prompt", "").encode()).hexdigest(),
            "timestamp": time.time(),
        }
        h = self._append_record(record)
        logger.info("Protocol-C PRE: task=%s hash=%s", task.get("task_id", "")[:8], h[:16])
        return h

    def commit_post_execution(self, task, result, pre_hash, execution_ms=0):
        record = {
            "event": "MCP_POST_EXECUTION",
            "task_id": task.get("task_id", ""),
            "client_id": task.get("client_id", ""),
            "pre_execution_hash": pre_hash,
            "result_hash": hashlib.sha256(result.encode()).hexdigest(),
            "execution_ms": execution_ms,
            "timestamp": time.time(),
        }
        h = self._append_record(record)
        logger.info("Protocol-C POST: task=%s pre=%s post=%s", task.get("task_id", "")[:8], pre_hash[:16], h[:16])
        return h

    def commit_anomaly(self, task, anomaly):
        record = {
            "event": "MCP_ANOMALY_DETECTED",
            "task_id": task.get("task_id", ""),
            "client_id": task.get("client_id", ""),
            "severity": anomaly.get("severity", "medium"),
            "reason": anomaly.get("reason", ""),
            "recommend_block": anomaly.get("recommend_block", False),
            "timestamp": time.time(),
        }
        h = self._append_record(record)
        logger.warning("Protocol-C ANOMALY: task=%s severity=%s hash=%s", task.get("task_id", "")[:8], anomaly.get("severity"), h[:16])
        return h

    def commit_breach(self, task, details):
        record = {
            "event": "MCP_BREACH_CONFIRMED",
            "task_id": task.get("task_id", ""),
            "client_id": task.get("client_id", ""),
            "breach_details": details,
            "severity": "critical",
            "timestamp": time.time(),
        }
        h = self._append_record(record)
        logger.critical("Protocol-C BREACH: task=%s hash=%s", task.get("task_id", "")[:8], h[:16])
        return h

    def get_recent_records(self, limit=100):
        try:
            if not Path(self._audit_path).exists():
                return []
            with open(self._audit_path, "r") as f:
                lines = f.readlines()
            records = []
            for line in lines[-limit:]:
                try:
                    records.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
            return records
        except Exception:
            return []
