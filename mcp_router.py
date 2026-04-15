"""
AetherCloud-L — MCP Router (Priority 1)
Routes user queries to their configured team agents by keyword scoring.
Falls back to builtin detection if no agent matches.

Aether Systems LLC — Patent Pending
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("aethercloud.mcp_router")

# ── Resolved agent ─────────────────────────────────────────────
@dataclass
class ResolvedAgent:
    """A user-configured MCP agent that was selected for a query."""
    agent_id: str
    name: str
    server_name: str        # e.g. "github", "slack", "fal_ai"
    url: str                # MCP server URL (empty for stdio)
    transport: str          # "http" | "stdio" | "sse"
    cmd: str = ""           # stdio command (e.g. "npx -y @org/server")
    auth_type: str = "bearer"
    keywords: list = field(default_factory=list)
    system_prompt: str = ""
    perms: dict = field(default_factory=dict)
    score: float = 0.0
    requires_browser_sandbox: bool = False


# ── Known server → MCP URL fallbacks ──────────────────────────
_SERVER_URLS = {
    "github":           "https://api.githubcopilot.com/mcp",
    "notion":           "https://api.notion.com/mcp",
    "stripe":           "https://mcp.stripe.com",
    "figma":            "https://mcp.figma.com/mcp",
    "fal_ai":           "https://mcp.fal.ai/mcp",
    "firecrawl":        "https://mcp.firecrawl.dev/mcp",
}

_STDIO_SERVERS = {
    "excalidraw", "context7", "desktop_commander", "custom_stdio",
}


class MCPRouter:
    """
    Routes a natural-language query to the best matching user-configured
    MCP agent.  Results are cached per user for _CACHE_TTL seconds to
    avoid re-reading disk on every message.
    """

    _CACHE_TTL = 300  # seconds

    def __init__(self):
        self._cache: dict[str, tuple[list, float]] = {}   # user_id -> (agents, ts)

    # ── Public API ─────────────────────────────────────────────

    async def route(self, user_id: str, query: str) -> Optional[ResolvedAgent]:
        """
        Score every configured agent against *query* and return the best
        match (score > 0). Returns None if no agent has any keyword match.
        """
        agents = self._load_agents(user_id)
        if not agents:
            return None

        best: Optional[ResolvedAgent] = None
        for a in agents:
            kws = [k.strip().lower() for k in (a.get("keywords") or "").split(",") if k.strip()]
            if not kws:
                continue
            q_lower = query.lower()
            score = sum(1 for kw in kws if kw in q_lower)
            if score > 0 and (best is None or score > best.score):
                server = a.get("server", "")
                best = ResolvedAgent(
                    agent_id=a.get("id", ""),
                    name=a.get("name", "Agent"),
                    server_name=server,
                    url=a.get("url") or _SERVER_URLS.get(server, ""),
                    transport=a.get("transport", "http"),
                    cmd=a.get("cmd", ""),
                    auth_type=a.get("authType", "bearer"),
                    keywords=kws,
                    system_prompt=a.get("prompt", ""),
                    perms=a.get("perms", {}),
                    score=float(score),
                    requires_browser_sandbox=bool(a.get("requires_browser_sandbox", False)),
                )

        if best:
            log.info(
                "MCPRouter: routed query to agent '%s' (server=%s, score=%.0f)",
                best.name, best.server_name, best.score,
            )
        return best

    def invalidate_cache(self, user_id: str) -> None:
        """Call after saving a new team config so the next query re-reads disk."""
        self._cache.pop(user_id, None)
        log.debug("MCPRouter: cache invalidated for user %s", user_id)

    def get_all_agents(self, user_id: str) -> list:
        """Return raw agent dicts for a user (for tool discovery etc.)."""
        return self._load_agents(user_id)

    def get_agent(self, user_id: str, agent_id: str) -> Optional[dict]:
        """Return a single raw agent dict by ID."""
        for a in self._load_agents(user_id):
            if a.get("id") == agent_id:
                return a
        return None

    # ── Internal ───────────────────────────────────────────────

    def _load_agents(self, user_id: str) -> list:
        """Load team config from disk, with in-process TTL caching."""
        cached, ts = self._cache.get(user_id, (None, 0))
        if cached is not None and (time.time() - ts) < self._CACHE_TTL:
            return cached

        team_file = self._team_file(user_id)
        agents: list = []
        if team_file.exists():
            try:
                agents = json.loads(team_file.read_text(encoding="utf-8"))
                if not isinstance(agents, list):
                    agents = []
            except Exception as e:
                log.warning("MCPRouter: failed to read team config for %s: %s", user_id, e)

        self._cache[user_id] = (agents, time.time())
        return agents

    @staticmethod
    def _team_file(user_id: str) -> Path:
        root = Path(__file__).parent
        return root / "data" / "users" / user_id / "agents" / "team.json"


# Module-level singleton — imported by api_server
mcp_router = MCPRouter()
