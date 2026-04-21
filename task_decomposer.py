"""
AetherCloud-L — Task Decomposer (Autonomous Project Execution)
Converts a broad user goal into a validated, dependency-resolved task graph.

Aether Systems LLC — Patent Pending
"""

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

log = logging.getLogger("aethercloud.task_decomposer")

# ── Role → keyword mapping for agent resolution ────────────────────────────────

AGENT_ROLES = {
    "backend":  ["api", "server", "database", "endpoint", "route", "auth", "backend",
                 "fastapi", "flask", "django", "express", "node", "python"],
    "frontend": ["ui", "component", "page", "dashboard", "css", "html", "react",
                 "vue", "svelte", "tailwind", "frontend", "interface", "design"],
    "database": ["schema", "model", "migration", "table", "index", "query",
                 "postgres", "sqlite", "mysql", "mongo"],
    "devops":   ["deploy", "docker", "nginx", "ci", "cd", "pipeline", "infra",
                 "vps", "server", "systemd"],
    "testing":  ["test", "spec", "coverage", "pytest", "jest", "unit", "integration", "e2e"],
    "docs":     ["document", "readme", "spec", "comment", "docstring", "swagger", "openapi"],
    "agent":    ["mcp", "tool", "agent", "llm", "ai", "automation"],
}


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class Task:
    """A single node in the task graph."""
    task_id: str
    title: str
    description: str
    role: str                                          # backend | frontend | database | devops | testing | docs | agent
    agent_id: str = ""                                 # resolved user agent ID (empty if none matched)
    agent_name: str = ""                               # display name
    depends_on: list = field(default_factory=list)     # list of task_ids
    acceptance_criteria: list = field(default_factory=list)
    status: str = "pending"                            # pending | running | done | failed | blocked
    output: str = ""
    error: str = ""
    retries: int = 0
    qopc_score: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


@dataclass
class TaskGraph:
    """The full project task graph."""
    project_id: str
    goal: str
    user_id: str
    tasks: list = field(default_factory=list)   # list of Task
    created_at: float = field(default_factory=time.time)
    status: str = "pending"                     # pending | running | done | failed

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "goal": self.goal,
            "user_id": self.user_id,
            "tasks": [asdict(t) for t in self.tasks],
            "created_at": self.created_at,
            "status": self.status,
        }


# ── Decomposer ─────────────────────────────────────────────────────────────────

class TaskDecomposer:
    """
    Converts a broad goal string into a validated TaskGraph.
    Calls Anthropic to generate tasks, then validates for cycles
    and dangling dependencies before returning.
    """

    DECOMPOSE_SYSTEM = """\
You are an expert software project planner inside AetherCloud, an autonomous AI development system.

Given a user's goal, produce a JSON task graph. Each task must have:
- task_id: short snake_case identifier (e.g. "setup_db")
- title: short human-readable title (max 8 words)
- description: what the agent must do (1-2 sentences)
- role: one of backend | frontend | database | devops | testing | docs | agent
- depends_on: list of task_ids this task depends on (empty list for first tasks)
- acceptance_criteria: list of 2-3 specific, testable criteria strings

Rules:
- Minimum 3 tasks, maximum 12 tasks
- No cycles in depends_on
- All depends_on references must be valid task_ids in the same graph
- Order tasks logically: database before backend, backend before frontend, backend before testing
- Return ONLY valid JSON: {"tasks": [...]}
"""

    async def decompose(self, goal: str, user_id: str, api_key: str, user_agents: list) -> TaskGraph:
        """
        Decompose *goal* into a TaskGraph.
        *user_agents* is the raw list of agent dicts from team.json.
        """
        project_id = str(uuid.uuid4())[:8]
        t0 = time.time()

        raw_tasks = await self._call_anthropic(goal, api_key)
        log.info("Decomposed '%s...' into %d tasks in %.1fs",
                 goal[:60], len(raw_tasks), time.time() - t0)

        tasks = []
        for t in raw_tasks:
            task_id = t.get("task_id") or str(uuid.uuid4())[:8]
            role = t.get("role", "backend")
            agent_id, agent_name = self._resolve_agent(role, user_agents)
            tasks.append(Task(
                task_id=task_id,
                title=t.get("title", task_id),
                description=t.get("description", ""),
                role=role,
                agent_id=agent_id,
                agent_name=agent_name,
                depends_on=t.get("depends_on", []),
                acceptance_criteria=t.get("acceptance_criteria", []),
            ))

        graph = TaskGraph(
            project_id=project_id,
            goal=goal,
            user_id=user_id,
            tasks=tasks,
        )
        self._validate_graph(graph)
        return graph

    def _resolve_agent(self, role: str, user_agents: list) -> tuple:
        """Find the best matching user agent for a given role."""
        role_kws = AGENT_ROLES.get(role, [])
        best_id, best_name, best_score = "", role.title(), 0

        for agent in user_agents:
            agent_kws = [k.strip().lower() for k in (agent.get("keywords") or "").split(",") if k.strip()]
            name_lower = agent.get("name", "").lower()
            score = sum(1 for kw in role_kws if kw in agent_kws or kw in name_lower)
            if score > best_score:
                best_score = score
                best_id = agent.get("id", "")
                best_name = agent.get("name", role.title())

        return best_id, best_name

    def _validate_graph(self, graph: TaskGraph) -> None:
        """Repair the task graph: remove dangling refs and break cycles."""
        valid_ids = {t.task_id for t in graph.tasks}
        for task in graph.tasks:
            task.depends_on = [d for d in task.depends_on if d in valid_ids and d != task.task_id]
        self._break_cycles(graph)

    def _break_cycles(self, graph: TaskGraph) -> None:
        """Detect cycles with DFS and remove back-edges."""
        adj = {t.task_id: list(t.depends_on) for t in graph.tasks}
        task_map = {t.task_id: t for t in graph.tasks}
        visited: set = set()
        in_stack: set = set()

        def dfs(node: str):
            visited.add(node)
            in_stack.add(node)
            for dep in list(adj.get(node, [])):
                if dep not in visited:
                    dfs(dep)
                elif dep in in_stack:
                    task_map[node].depends_on.remove(dep)
                    adj[node].remove(dep)
                    log.warning("Cycle removed: %s → %s", node, dep)
            in_stack.discard(node)

        for t in graph.tasks:
            if t.task_id not in visited:
                dfs(t.task_id)

    async def _call_anthropic(self, goal: str, api_key: str) -> list:
        """Call Anthropic via TokenAccountant and return the parsed task list.

        api_key retained for signature compat; TokenAccountant reads env directly.
        Decomposer uses Sonnet today; will escalate to Opus for heavy QOPC loads
        in Stage D (Router).
        """
        from lib import token_accountant

        resp = await token_accountant.call(
            model="sonnet",
            messages=[{"role": "user", "content": f"Goal: {goal}"}],
            user_id=None,
            system=self.DECOMPOSE_SYSTEM,
            max_tokens=2000,
        )

        match = re.search(r'\{[\s\S]*\}', resp.text)
        if not match:
            log.warning("No JSON in decomposer response — using fallback tasks")
            return self._default_tasks(goal)
        try:
            return json.loads(match.group()).get("tasks", [])
        except Exception as e:
            log.warning("Failed to parse decomposer JSON: %s", e)
            return self._default_tasks(goal)

    @staticmethod
    def _default_tasks(goal: str) -> list:
        """Fallback task list if Anthropic call fails."""
        return [
            {
                "task_id": "setup",
                "title": "Project Setup",
                "description": f"Initialize project structure for: {goal[:100]}",
                "role": "backend",
                "depends_on": [],
                "acceptance_criteria": ["Project structure created", "Dependencies defined"],
            },
            {
                "task_id": "implement",
                "title": "Core Implementation",
                "description": "Implement the main functionality as described in the goal.",
                "role": "backend",
                "depends_on": ["setup"],
                "acceptance_criteria": ["Core logic implemented", "Basic tests pass"],
            },
            {
                "task_id": "verify",
                "title": "Deploy & Verify",
                "description": "Deploy and verify the implementation works end-to-end.",
                "role": "devops",
                "depends_on": ["implement"],
                "acceptance_criteria": ["Service running", "End-to-end flow verified"],
            },
        ]


# Module-level singleton
decomposer = TaskDecomposer()
