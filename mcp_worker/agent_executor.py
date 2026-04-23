"""
Aether MCP Worker — Agent Executor
Handles MCP agent execution via Anthropic API + anomaly detection.

Aether Systems LLC — Patent Pending
"""

import logging
import os
import sys
import time
import threading
import uuid
from collections import defaultdict, deque
from typing import Optional

from lib import token_accountant

logger = logging.getLogger("aether.mcp.executor")

# Red Team #2 C1: TokenAccountant is the SOLE Anthropic caller. This file
# used to POST the Anthropic /v1/messages endpoint directly via httpx;
# that bypassed UVT accounting, usage_events, and DLQ. The assertion
# catches any future regression at import time.
assert "anthropic" not in sys.modules, (
    "mcp_worker/agent_executor.py imported the `anthropic` package "
    "directly. Route all Anthropic calls through lib.token_accountant. "
    "See Red Team #2 C1 in tests/security/redteam_modelrouter_report.md."
)

import os as _os

MCP_SERVERS = {
    "gmail":          {"name": "gmail-mcp",         "type": "url", "url": "https://gmail.mcp.claude.com/mcp"},
    "gcal":           {"name": "gcal-mcp",           "type": "url", "url": "https://gcal.mcp.claude.com/mcp"},
    "google_drive":   {"name": "gdrive-mcp",         "type": "url", "url": "https://drive.mcp.claude.com/mcp"},
    "github":         {"name": "github-mcp",         "type": "url", "url": _os.getenv("GITHUB_MCP_URL",  "https://api.githubcopilot.com/mcp/")},
    "slack":          {"name": "slack-mcp",          "type": "url", "url": _os.getenv("SLACK_MCP_URL",   "https://mcp.slack.com/sse")},
    "brave_search":   {"name": "brave-search-mcp",   "type": "url", "url": _os.getenv("BRAVE_MCP_URL",   "https://api.search.brave.com/mcp")},
    "linear":         {"name": "linear-mcp",         "type": "url", "url": _os.getenv("LINEAR_MCP_URL",  "https://mcp.linear.app/sse")},
    "notion":         {"name": "notion-mcp",         "type": "url", "url": _os.getenv("NOTION_MCP_URL",  "https://api.notion.com/v1/mcp")},
}

# Auth tokens injected per-request from env vars (not stored in the dict above)
MCP_AUTH_ENVS = {
    "github":       "GITHUB_MCP_TOKEN",
    "slack":        "SLACK_MCP_TOKEN",
    "brave_search": "BRAVE_SEARCH_API_KEY",
    "linear":       "LINEAR_API_KEY",
    "notion":       "NOTION_API_KEY",
}

RATE_LIMIT_PER_MIN = 20
EXECUTION_TIME_MULTIPLIER = 10
NORMAL_EXECUTION_MS = {
    "gmail":        5000,
    "gcal":         3000,
    "google_drive": 6000,
    "github":       8000,
    "slack":        4000,
    "brave_search": 5000,
    "linear":       6000,
    "notion":       6000,
    "mcp":          10000,
}


class AgentExecutor:
    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.model = os.getenv("MCP_AGENT_MODEL", "claude-sonnet-4-20250514")
        self.max_tokens = int(os.getenv("MCP_MAX_TOKENS", "2000"))
        self.timeout = int(os.getenv("MCP_TIMEOUT", "30"))
        self.active_tasks = 0
        self.total_executions = 0
        self.task_history: deque = deque(maxlen=100)
        self._lock = threading.Lock()
        self._client_timestamps = defaultdict(lambda: deque(maxlen=200))
        self._client_operations = defaultdict(set)
        self._seen_task_ids = set()

    async def execute(self, task):
        task_id = task.get("task_id", "")
        agent_type = task.get("agent_type", "mcp")
        prompt = task.get("prompt", "")
        context = task.get("context", "")

        with self._lock:
            self.active_tasks += 1

        start = time.monotonic()
        try:
            mcp_servers = []
            server_url = task.get("mcp_server_url", "")
            if server_url:
                mcp_servers.append({"type": "url", "url": server_url})
            elif agent_type in MCP_SERVERS:
                cfg = dict(MCP_SERVERS[agent_type])
                auth_env = MCP_AUTH_ENVS.get(agent_type)
                if auth_env:
                    token = _os.getenv(auth_env, "")
                    if token:
                        cfg["authorization_token"] = token
                mcp_servers.append(cfg)

            system = "You are an autonomous MCP agent. Execute tasks using available tools."
            if context:
                system += f"\n\nUser context:\n{context}"

            # Red Team #2 C1: route through TokenAccountant instead of a
            # direct POST to the Anthropic messages endpoint. When
            # task["client_id"] is a valid UUID we treat it as a Supabase
            # user_id (attributed usage); otherwise the call is
            # unattributed (desktop MCP worker mode). Either way
            # TokenAccountant owns prompt caching and DLQ on any
            # rpc_record_usage failure.
            raw_client_id = task.get("client_id", "")
            attributed_user_id: Optional[str] = None
            try:
                attributed_user_id = str(uuid.UUID(str(raw_client_id)))
            except (ValueError, TypeError):
                attributed_user_id = None

            model_key = token_accountant.resolve_model_key(self.model)
            try:
                resp = await token_accountant.call(
                    model=model_key,
                    messages=[{"role": "user", "content": prompt}],
                    system=system,
                    mcp_servers=mcp_servers or None,
                    max_tokens=self.max_tokens,
                    user_id=attributed_user_id,
                    task_id=task_id or None,
                )
            except Exception as call_exc:  # noqa: BLE001 — preserve existing API shape
                elapsed_ms = int((time.monotonic() - start) * 1000)
                return {
                    "result": "", "tools_used": [], "execution_ms": elapsed_ms,
                    "error": f"Anthropic API error: {call_exc}",
                }

            elapsed_ms = int((time.monotonic() - start) * 1000)
            result_text = resp.text
            tools_used = [tu.get("name", "unknown") for tu in resp.tool_uses]

            with self._lock:
                self.total_executions += 1
                self.task_history.append({"task_id": task_id, "client_id": task.get("client_id", ""), "agent_type": agent_type, "execution_ms": elapsed_ms, "tools_used": tools_used, "timestamp": time.time()})

            return {"result": result_text, "tools_used": tools_used, "execution_ms": elapsed_ms, "error": None}
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {"result": "", "tools_used": [], "execution_ms": elapsed_ms, "error": str(e)}
        finally:
            with self._lock:
                self.active_tasks = max(0, self.active_tasks - 1)

    def detect_anomaly(self, task, result) -> Optional[dict]:
        client_id = task.get("client_id", "")
        task_id = task.get("task_id", "")
        agent_type = task.get("agent_type", "mcp")
        now = time.time()

        if task_id in self._seen_task_ids:
            return {"anomaly": True, "severity": "critical", "reason": f"Replay attack — task_id {task_id[:12]} seen before", "recommend_block": True}
        self._seen_task_ids.add(task_id)
        if len(self._seen_task_ids) > 50000:
            self._seen_task_ids.clear()

        self._client_timestamps[client_id].append(now)
        recent = sum(1 for t in self._client_timestamps[client_id] if t > now - 60)
        if recent > RATE_LIMIT_PER_MIN:
            return {"anomaly": True, "severity": "high", "reason": f"Rate limit exceeded: {recent} calls/min (limit {RATE_LIMIT_PER_MIN})", "recommend_block": True}

        normal_ms = NORMAL_EXECUTION_MS.get(agent_type, 10000)
        if result.get("execution_ms", 0) > normal_ms * EXECUTION_TIME_MULTIPLIER:
            return {"anomaly": True, "severity": "medium", "reason": f"Execution time {result['execution_ms']}ms > {EXECUTION_TIME_MULTIPLIER}x normal", "recommend_block": False}

        tools = set(result.get("tools_used", []))
        prev_tools = self._client_operations.get(client_id, set())
        high_risk = {
            # Gmail
            "gmail_send_message", "gmail_delete_message",
            # Calendar
            "calendar_delete_event",
            # GitHub — write/delete ops
            "create_issue", "delete_issue", "create_pull_request",
            "merge_pull_request", "delete_repository", "push_files",
            # Slack — send/delete
            "slack_post_message", "slack_delete_message",
            # Linear — create/delete
            "linear_create_issue", "linear_delete_issue",
            # Notion — create/delete
            "notion_create_page", "notion_delete_block",
            # Drive — delete/share
            "drive_delete_file", "drive_share_file",
        }
        if prev_tools and tools and not tools.intersection(prev_tools) and tools.intersection(high_risk) and not prev_tools.intersection(high_risk):
            return {"anomaly": True, "severity": "high", "reason": f"Unexpected high-risk operation change: {prev_tools} → {tools}", "recommend_block": True}
        if tools:
            self._client_operations[client_id].update(tools)
        return None

    def get_stats(self):
        configured = [k for k, v in MCP_AUTH_ENVS.items() if _os.getenv(v)]
        no_auth    = [k for k in MCP_SERVERS if k not in MCP_AUTH_ENVS]
        return {
            "active_tasks":      self.active_tasks,
            "total_executions":  self.total_executions,
            "agents":            list(MCP_SERVERS.keys()),
            "agents_configured": no_auth + configured,
            "agents_missing_token": [k for k in MCP_AUTH_ENVS if k not in configured],
            "recent_tasks":      len(self.task_history),
        }
