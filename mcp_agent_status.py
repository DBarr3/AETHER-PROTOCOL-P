"""
MCPAgentStatusManager — tracks which MCP agents are active,
assigns pixel-art icon colors by server name, and emits SSE
events so the dashboard can render live agent badges.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


# ── Color slots ───────────────────────────────────────────────────────────────
class AgentColor(str, Enum):
    BLUE   = "blue"    # #2196F3  — default / general purpose
    GREEN  = "green"   # #4CAF50  — read / fetch / search
    ORANGE = "orange"  # #E36C35  — write / mutation
    RED    = "red"     # #F44336  — error / auth / security
    YELLOW = "yellow"  # #FFEB3B  — pending / queued


SERVER_COLOR_MAP = {
    "gmail":             AgentColor.GREEN,
    "gcal":              AgentColor.BLUE,
    "google_calendar":   AgentColor.BLUE,
    "google_drive":      AgentColor.GREEN,
    "gdrive":            AgentColor.GREEN,
    "web_search":        AgentColor.GREEN,
    "brave_search":      AgentColor.GREEN,
    "fal_ai":            AgentColor.ORANGE,
    "excalidraw":        AgentColor.ORANGE,
    "figma":             AgentColor.BLUE,
    "github":            AgentColor.ORANGE,
    "slack":             AgentColor.GREEN,
    "notion":            AgentColor.YELLOW,
    "linear":            AgentColor.YELLOW,
    "desktop_commander": AgentColor.RED,
    "context7":          AgentColor.YELLOW,
    "stripe":            AgentColor.GREEN,
    "filesystem":        AgentColor.ORANGE,
}

def color_for_server(server_name: str) -> AgentColor:
    key = server_name.lower().replace("-", "_").replace(" ", "_")
    return SERVER_COLOR_MAP.get(key, AgentColor.BLUE)


# ── Agent state ────────────────────────────────────────────────────────────────
class AgentState(str, Enum):
    IDLE    = "idle"
    WORKING = "working"
    DONE    = "done"
    ERROR   = "error"


@dataclass
class MCPAgent:
    agent_id:    str
    server_name: str
    color:       AgentColor
    state:       AgentState = AgentState.IDLE
    task:        str        = ""
    started_at:  float      = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error:       Optional[str]   = None

    def to_dict(self):
        return asdict(self)


# ── Manager ────────────────────────────────────────────────────────────────────
class MCPAgentStatusManager:
    MAX_SLOTS = 5

    def __init__(self):
        self._agents: dict[str, MCPAgent] = {}
        self._subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def agent_start(self, agent_id: str, server_name: str, task: str = "") -> MCPAgent:
        async with self._lock:
            agent = MCPAgent(
                agent_id=agent_id,
                server_name=server_name,
                color=color_for_server(server_name),
                state=AgentState.WORKING,
                task=task,
                started_at=time.time(),
            )
            self._agents[agent_id] = agent
            await self._broadcast("agent_start", agent)
            return agent

    async def agent_done(self, agent_id: str, error: str | None = None):
        async with self._lock:
            if agent_id not in self._agents:
                return
            agent = self._agents[agent_id]
            agent.state = AgentState.ERROR if error else AgentState.DONE
            agent.finished_at = time.time()
            agent.error = error
            await self._broadcast("agent_done", agent)
            asyncio.create_task(self._remove_after(agent_id, delay=3.0))

    async def get_active(self) -> list[MCPAgent]:
        async with self._lock:
            return [a for a in self._agents.values() if a.state == AgentState.WORKING]

    async def get_all(self) -> list[MCPAgent]:
        async with self._lock:
            return list(self._agents.values())

    async def stream(self):
        """AsyncGenerator for SSE. Wire to FastAPI StreamingResponse."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            async with self._lock:
                snapshot = [a.to_dict() for a in self._agents.values()]
            yield f"data: {json.dumps({'type': 'snapshot', 'agents': snapshot})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    async def _broadcast(self, event_type: str, agent: MCPAgent):
        payload = {"type": event_type, "agent": agent.to_dict()}
        for q in self._subscribers:
            await q.put(payload)

    async def _remove_after(self, agent_id: str, delay: float):
        await asyncio.sleep(delay)
        async with self._lock:
            self._agents.pop(agent_id, None)
            payload = {"type": "agent_removed", "agent_id": agent_id}
            for q in self._subscribers:
                await q.put(payload)


# ── Singleton ──────────────────────────────────────────────────────────────────
status_manager = MCPAgentStatusManager()
