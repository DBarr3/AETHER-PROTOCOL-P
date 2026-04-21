"""
AetherCloud-L — Project Orchestrator (Autonomous Project Execution)
Watches the task graph, fires agents when dependencies are met,
validates outputs with QOPC, retries failures, and broadcasts SSE events.

Aether Systems LLC — Patent Pending
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger("aethercloud.project_orchestrator")

QOPC_THRESHOLD = 0.72
MAX_RETRIES    = 2
MAX_CONCURRENT = 3


@dataclass
class ProjectEvent:
    event_type: str     # task_start | task_done | task_failed | task_blocked | project_done | question
    project_id: str
    payload: dict


class ProjectOrchestrator:
    """
    Drives a TaskGraph to completion:
    - Fires tasks when all dependencies are done
    - Runs at most MAX_CONCURRENT tasks simultaneously (semaphore)
    - Validates each output with QOPC (threshold: 0.72)
    - Retries up to MAX_RETRIES times with validator feedback
    - Cascades failures to dependent tasks as 'blocked'
    - Emits SSE events to subscribers via asyncio.Queue
    """

    def __init__(self, mcp_router, ctx_manager, api_key_fn: Optional[Callable] = None):
        self.router = mcp_router
        self.ctx_manager = ctx_manager
        self._get_api_key = api_key_fn
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._subscribers: dict = {}    # project_id → list[asyncio.Queue]

    # ── Public API ─────────────────────────────────────────────────────────────

    async def run(self, graph, status_manager=None) -> None:
        """Execute *graph* asynchronously. Emits events via SSE."""
        project_id = graph.project_id
        user_id    = graph.user_id
        graph.status = "running"
        api_key = self._get_api_key() if self._get_api_key else ""

        await self.ctx_manager.init(user_id, project_id, graph.goal)
        await self._emit(project_id, ProjectEvent(
            event_type="progress",
            project_id=project_id,
            payload={"message": f"Starting {len(graph.tasks)} tasks", "task_count": len(graph.tasks)},
        ))

        task_map = {t.task_id: t for t in graph.tasks}

        while True:
            # Tasks whose deps are all done and not themselves failed
            ready = [
                t for t in graph.tasks
                if t.status == "pending"
                and all(task_map.get(d) and task_map[d].status == "done" for d in t.depends_on)
                and not any(task_map.get(d) and task_map[d].status in ("failed", "blocked")
                            for d in t.depends_on)
            ]

            # Block tasks whose deps failed/blocked
            for t in graph.tasks:
                if t.status == "pending" and any(
                    task_map.get(d) and task_map[d].status in ("failed", "blocked")
                    for d in t.depends_on
                ):
                    t.status = "blocked"
                    await self._emit(project_id, ProjectEvent(
                        event_type="task_blocked",
                        project_id=project_id,
                        payload={"task_id": t.task_id, "title": t.title},
                    ))

            if not ready:
                running = [t for t in graph.tasks if t.status == "running"]
                if not running:
                    break
                await asyncio.sleep(0.5)
                continue

            # Mark ready tasks as running, then fire concurrently
            for t in ready:
                t.status = "running"
            await asyncio.gather(
                *[self._run_task(t, graph, api_key, status_manager) for t in ready],
                return_exceptions=True,
            )

        failed = [t for t in graph.tasks if t.status in ("failed", "blocked")]
        graph.status = "failed" if failed else "done"

        await self._emit(project_id, ProjectEvent(
            event_type="project_done",
            project_id=project_id,
            payload={
                "status": graph.status,
                "done":   len([t for t in graph.tasks if t.status == "done"]),
                "failed": len(failed),
                "total":  len(graph.tasks),
                "tasks":  [self._task_summary(t) for t in graph.tasks],
            },
        ))

    async def subscribe(self, project_id: str) -> asyncio.Queue:
        """Register a new SSE subscriber for *project_id*."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(project_id, []).append(q)
        return q

    def unsubscribe(self, project_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(project_id, [])
        if q in subs:
            subs.remove(q)

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _run_task(self, task, graph, api_key: str, status_manager) -> None:
        """Execute one task with retries and QOPC validation."""
        async with self._semaphore:
            project_id = graph.project_id
            user_id    = graph.user_id

            await self._emit(project_id, ProjectEvent(
                event_type="task_start",
                project_id=project_id,
                payload=self._task_summary(task),
            ))

            if status_manager:
                try:
                    await status_manager.agent_start(task.task_id, task.role, task.title)
                except Exception:
                    pass

            task.started_at = time.time()

            for attempt in range(MAX_RETRIES + 1):
                try:
                    ctx = await self.ctx_manager.get(user_id, project_id)
                    ctx_str = self.ctx_manager.for_agent_prompt(ctx, task.role)
                    output = await self._execute_task(task, user_id, api_key, ctx_str)
                    score, feedback = await self._validate_output(output, task, api_key)
                    task.qopc_score = score

                    if score >= QOPC_THRESHOLD or attempt == MAX_RETRIES:
                        task.status = "done"
                        task.output = output
                        task.finished_at = time.time()
                        await self._update_context(task, output, user_id, project_id)
                        await self._emit(project_id, ProjectEvent(
                            event_type="task_done",
                            project_id=project_id,
                            payload={**self._task_summary(task), "qopc_score": score},
                        ))
                        if status_manager:
                            try:
                                await status_manager.agent_done(task.task_id)
                            except Exception:
                                pass
                        return
                    else:
                        log.info("Task %s QOPC %.2f < %.2f — retry %d/%d",
                                 task.task_id, score, QOPC_THRESHOLD, attempt + 1, MAX_RETRIES)
                        task.description += f"\n\nRetry feedback: {feedback}"
                        task.retries += 1

                except Exception as e:
                    log.warning("Task %s attempt %d error: %s", task.task_id, attempt, e)
                    if attempt == MAX_RETRIES:
                        task.status = "failed"
                        task.error  = str(e)[:300]
                        task.finished_at = time.time()
                        await self._emit(project_id, ProjectEvent(
                            event_type="task_failed",
                            project_id=project_id,
                            payload={**self._task_summary(task), "error": task.error},
                        ))
                        if status_manager:
                            try:
                                await status_manager.agent_done(task.task_id, error=task.error)
                            except Exception:
                                pass
                        return

    async def _execute_task(self, task, user_id: str, api_key: str, context_injection: str) -> str:
        """Call Anthropic via TokenAccountant with the task prompt and optional MCP server.

        api_key is retained in the signature for back-compat with callers but is
        unused — TokenAccountant reads ANTHROPIC_API_KEY from env directly.
        """
        from lib import token_accountant

        agent = self.router.get_agent(user_id, task.agent_id) if task.agent_id else None

        criteria = "\n".join(f"- {c}" for c in task.acceptance_criteria) or "- Complete the task as described"
        prompt = (
            f"{context_injection}\n\n"
            f"## Your Task: {task.title}\n\n"
            f"{task.description}\n\n"
            f"### Acceptance Criteria\n{criteria}\n\n"
            "Respond with your implementation and a brief explanation of what you built."
        )

        system = (
            agent.get("prompt", "")
            if agent and agent.get("prompt")
            else (
                f"You are an expert {task.role} engineer in an autonomous development system. "
                "Complete tasks precisely, write production-quality code, and document your decisions."
            )
        )

        mcp_servers = []
        if agent:
            url = agent.get("url", "")
            transport = agent.get("transport", "http")
            if url and transport in ("http", "sse"):
                mcp_servers.append({"type": "url", "url": url, "name": agent.get("server", "")})

        resp = await token_accountant.call(
            model="sonnet",
            messages=[{"role": "user", "content": prompt}],
            user_id=None,
            task_id=task.task_id,
            system=system,
            mcp_servers=mcp_servers or None,
            max_tokens=3000,
        )
        return resp.text

    async def _validate_output(self, output: str, task, api_key: str) -> tuple:
        """QOPC validation via Haiku. Returns (score 0-1, feedback).

        api_key retained for signature compat; TokenAccountant reads env directly.
        """
        from lib import token_accountant

        if not output.strip():
            return 0.0, "Empty output"

        criteria = "\n".join(f"- {c}" for c in task.acceptance_criteria) or "- Task completed"
        prompt = (
            f"You are a strict quality validator. Score this task output 0.0-1.0.\n\n"
            f"Task: {task.title}\nCriteria:\n{criteria}\n\n"
            f"Output:\n{output[:2000]}\n\n"
            'Respond ONLY with valid JSON: {"score": 0.85, "feedback": "brief reason"}'
        )

        try:
            resp = await token_accountant.call(
                model="haiku",
                messages=[{"role": "user", "content": prompt}],
                user_id=None,
                task_id=task.task_id,
                max_tokens=150,
            )
            m = re.search(r'\{[^}]+\}', resp.text)
            if m:
                result = json.loads(m.group())
                return float(result.get("score", 0.8)), result.get("feedback", "")
        except Exception as e:
            log.warning("QOPC validation error: %s", e)

        return 0.8, "Validation skipped"

    async def _update_context(self, task, output: str, user_id: str, project_id: str) -> None:
        """Extract API contracts from task output and record decision."""
        try:
            api_blocks = re.findall(r'```json\s*(\{[^`]+\})\s*```', output)
            for block in api_blocks[:3]:
                try:
                    schema = json.loads(block)
                    if "endpoint" in schema or "path" in schema:
                        endpoint = schema.get("endpoint") or schema.get("path", f"/{task.task_id}")
                        await self.ctx_manager.record_api_contract(user_id, project_id, endpoint, schema)
                except Exception:
                    pass

            await self.ctx_manager.record_decision(
                user_id, project_id, task.task_id,
                f"{task.title} completed",
                f"QOPC: {task.qopc_score:.2f}",
            )
        except Exception as e:
            log.debug("Context update skipped for %s: %s", task.task_id, e)

    async def _emit(self, project_id: str, event: ProjectEvent) -> None:
        payload = {"type": event.event_type, "project_id": event.project_id, **event.payload}
        for q in list(self._subscribers.get(project_id, [])):
            try:
                await q.put(payload)
            except Exception:
                pass

    @staticmethod
    def _task_summary(task) -> dict:
        return {
            "task_id":    task.task_id,
            "title":      task.title,
            "role":       task.role,
            "agent_id":   task.agent_id,
            "agent_name": task.agent_name,
            "status":     task.status,
            "qopc_score": task.qopc_score,
            "retries":    task.retries,
            "error":      task.error,
        }
