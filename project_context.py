"""
AetherCloud-L — Project Context Manager (Autonomous Project Execution)
Shared brain that all agents read and write during project execution.
Stored locally with DO Spaces upload on each write.

Aether Systems LLC — Patent Pending
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger("aethercloud.project_context")


@dataclass
class ProjectContext:
    """The shared context object all agents read and write."""
    project_id: str
    goal: str
    user_id: str

    # Shared artifacts — merged on update, not overwritten
    api_contracts: dict = field(default_factory=dict)   # endpoint → schema
    env_vars: dict = field(default_factory=dict)         # name → description
    files_created: list = field(default_factory=list)    # file paths
    decisions: list = field(default_factory=list)        # {task_id, decision, reason, ts}
    tech_stack: dict = field(default_factory=dict)       # layer → tech choice

    updated_at: float = field(default_factory=time.time)


class ProjectContextManager:
    """
    Per-project context store. Reads/writes atomically.
    Frontend agents read backend's API contracts via for_agent_prompt().
    """

    def __init__(self, vault=None):
        self._vault = vault
        self._contexts: dict = {}   # project_id → ProjectContext
        self._locks: dict = {}      # project_id → asyncio.Lock

    # ── Public API ─────────────────────────────────────────────────────────────

    async def init(self, user_id: str, project_id: str, goal: str) -> ProjectContext:
        """Create a fresh context for a new project."""
        ctx = ProjectContext(project_id=project_id, goal=goal, user_id=user_id)
        self._contexts[project_id] = ctx
        await self._save(ctx)
        return ctx

    async def get(self, user_id: str, project_id: str) -> ProjectContext:
        """Load context from memory or disk."""
        if project_id in self._contexts:
            return self._contexts[project_id]

        path = self._local_path(user_id, project_id)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # Only pick fields that exist on the dataclass
                known = {k: v for k, v in data.items() if k in ProjectContext.__dataclass_fields__}
                ctx = ProjectContext(**known)
                self._contexts[project_id] = ctx
                return ctx
            except Exception as e:
                log.warning("Failed to load context %s: %s", project_id, e)

        ctx = ProjectContext(project_id=project_id, goal="", user_id=user_id)
        self._contexts[project_id] = ctx
        return ctx

    async def update(self, user_id: str, project_id: str, updates: dict) -> ProjectContext:
        """Atomically merge updates into the context."""
        lock = self._locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            ctx = await self.get(user_id, project_id)
            for key, value in updates.items():
                if not hasattr(ctx, key):
                    continue
                existing = getattr(ctx, key)
                if isinstance(existing, list) and isinstance(value, list):
                    existing.extend(value)
                elif isinstance(existing, dict) and isinstance(value, dict):
                    existing.update(value)
                else:
                    setattr(ctx, key, value)
            ctx.updated_at = time.time()
            await self._save(ctx)
            return ctx

    async def record_api_contract(self, user_id: str, project_id: str, endpoint: str, schema: dict):
        await self.update(user_id, project_id, {"api_contracts": {endpoint: schema}})

    async def record_file(self, user_id: str, project_id: str, file_path: str):
        await self.update(user_id, project_id, {"files_created": [file_path]})

    async def record_decision(self, user_id: str, project_id: str, task_id: str, decision: str, reason: str = ""):
        await self.update(user_id, project_id, {
            "decisions": [{"task_id": task_id, "decision": decision, "reason": reason, "ts": time.time()}]
        })

    def for_agent_prompt(self, ctx: ProjectContext, role: str) -> str:
        """Build a context injection string tailored to the agent's role."""
        lines = [f"## Project Context\nGoal: {ctx.goal}"]

        if ctx.tech_stack:
            lines.append("### Tech Stack\n" + "\n".join(f"- {k}: {v}" for k, v in ctx.tech_stack.items()))

        if ctx.decisions:
            lines.append("### Key Decisions\n" + "\n".join(
                f"- [{d['task_id']}] {d['decision']}" for d in ctx.decisions[-5:]
            ))

        if role in ("frontend", "testing", "docs") and ctx.api_contracts:
            lines.append("### API Contracts (from backend)\n" + json.dumps(ctx.api_contracts, indent=2))

        if role in ("backend", "devops") and ctx.env_vars:
            lines.append("### Environment Variables\n" +
                         "\n".join(f"- {k}: {v}" for k, v in ctx.env_vars.items()))

        if ctx.files_created:
            lines.append("### Files Created\n" + "\n".join(f"- {f}" for f in ctx.files_created[-10:]))

        return "\n\n".join(lines)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _local_path(self, user_id: str, project_id: str) -> Path:
        p = Path(__file__).parent / "data" / "projects" / user_id / f"{project_id}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    async def _save(self, ctx: ProjectContext) -> None:
        path = self._local_path(ctx.user_id, ctx.project_id)
        try:
            path.write_text(json.dumps(asdict(ctx), indent=2), encoding="utf-8")
        except Exception as e:
            log.error("Failed to save project context %s: %s", ctx.project_id, e)
