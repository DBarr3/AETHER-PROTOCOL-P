"""
AetherCloud-L — Project Routes (Autonomous Project Execution)
POST /project/start    — decompose goal and begin execution
GET  /project/stream/{id} — SSE stream of live project events
GET  /project/status/{id} — current task-graph snapshot
GET  /project/context/{id} — shared project context

Aether Systems LLC — Patent Pending
"""

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

log = logging.getLogger("aethercloud.project_routes")

# ── Injected by api_server at startup ──────────────────────────────────────────
ctx_manager  = None   # ProjectContextManager
orchestrator = None   # ProjectOrchestrator

# ── Active graphs (in-memory, per process) ────────────────────────────────────
_active_graphs: dict = {}   # project_id → TaskGraph

project_router = APIRouter(prefix="/project", tags=["project"])


# ── Models ─────────────────────────────────────────────────────────────────────

class ProjectStartRequest(BaseModel):
    goal: str
    name: Optional[str] = None


# ── Auth helper (query-param token for EventSource) ────────────────────────────

async def _flexible_token(
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
) -> str:
    raw = token or (authorization or "").replace("Bearer ", "").strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Missing session token")
    return raw


def _resolve_user(token: str) -> str:
    """Validate token against the live session manager and return username."""
    try:
        from api_server import svc
        if not svc.session_mgr or not svc.session_mgr.is_valid(token):
            raise HTTPException(status_code=401, detail="Invalid or expired session token")
        username = svc.session_mgr.get_username(token)
        if not username:
            raise HTTPException(status_code=401, detail="Cannot resolve user from token")
        return username
    except ImportError:
        return "unknown"


# ── Routes ─────────────────────────────────────────────────────────────────────

@project_router.post("/start")
async def start_project(
    req: ProjectStartRequest,
    token: str = Depends(_flexible_token),
):
    """
    Decompose a broad goal into a task graph and begin autonomous execution.
    Returns immediately with the full task list; execution runs in background.
    """
    username = _resolve_user(token)

    if orchestrator is None or ctx_manager is None:
        raise HTTPException(status_code=503, detail="Project orchestrator not initialised")

    from task_decomposer import decomposer
    from mcp_router import mcp_router
    from config.key_manager import get_anthropic_key

    api_key    = get_anthropic_key()
    user_agents = mcp_router.get_all_agents(username)

    graph = await decomposer.decompose(req.goal, username, api_key, user_agents)
    _active_graphs[graph.project_id] = graph

    from mcp_agent_status import status_manager as _sm
    asyncio.create_task(orchestrator.run(graph, status_manager=_sm))

    task_lines = "\n".join(
        f"{i+1}. [{t.role.upper()}] {t.title}" for i, t in enumerate(graph.tasks)
    )
    return {
        "project_id": graph.project_id,
        "task_count": len(graph.tasks),
        "tasks": [
            {
                "task_id":            t.task_id,
                "title":              t.title,
                "role":               t.role,
                "agent_name":         t.agent_name,
                "depends_on":         t.depends_on,
                "acceptance_criteria": t.acceptance_criteria,
            }
            for t in graph.tasks
        ],
        "message": f"[PROJECT STARTED — {len(graph.tasks)} tasks]\n\n{task_lines}",
    }


@project_router.get("/stream/{project_id}")
async def project_stream(
    project_id: str,
    token: str = Depends(_flexible_token),
):
    """SSE stream of live project events. Token accepted via ?token= for EventSource."""
    _resolve_user(token)

    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialised")

    async def generator():
        q = await orchestrator.subscribe(project_id)
        try:
            yield f"data: {json.dumps({'type': 'connected', 'project_id': project_id})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") == "project_done":
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            orchestrator.unsubscribe(project_id, q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@project_router.get("/status/{project_id}")
async def project_status(
    project_id: str,
    token: str = Depends(_flexible_token),
):
    """Return the current task-graph snapshot."""
    _resolve_user(token)
    graph = _active_graphs.get(project_id)
    if not graph:
        raise HTTPException(status_code=404, detail="Project not found")
    return graph.to_dict()


@project_router.get("/context/{project_id}")
async def get_project_context(
    project_id: str,
    token: str = Depends(_flexible_token),
):
    """Return the shared project context (API contracts, decisions, files, etc.)."""
    username = _resolve_user(token)
    if ctx_manager is None:
        raise HTTPException(status_code=503, detail="Context manager not initialised")
    ctx = await ctx_manager.get(username, project_id)
    return asdict(ctx)


# ── Dashboard JavaScript ───────────────────────────────────────────────────────
# Paste the contents of DASHBOARD_PROJECT_JS before window.activityLayer in dashboard.html

DASHBOARD_PROJECT_JS = r"""
// ════════════════════════════════════════════════════
// AUTONOMOUS PROJECT EXECUTION
// ════════════════════════════════════════════════════

const _PROJECT_PATTERNS = [
  /\bbuild\s+(me\s+)?(a|an|the)\b/i,
  /\bcreate\s+(me\s+)?(a|an|the)\b/i,
  /\bdesign\s+(me\s+)?(a|an|the)\b/i,
  /\bdevelop\s+(a|an|the)\b/i,
  /\bmake\s+(me\s+)?(a|an|the)\b/i,
  /\blaunch\s+(a|an|the)\b/i,
  /\bship\s+(a|an|the)\b/i,
  /\bimplement\s+(a|an|the)\b/i,
  /\bwrite\s+(me\s+)?(a|an|the)\s+(full|complete|entire)\b/i,
  /\b(fully|automatically)\b.{0,60}\b(build|create|develop|implement)\b/i,
];
const _PROJECT_MIN_WORDS = 6;

function detectProjectGoal(query) {
  if (!query || query.trim().split(/\s+/).length < _PROJECT_MIN_WORDS) return false;
  return _PROJECT_PATTERNS.some(p => p.test(query));
}

let _activeProject = null;
let _projectEventSource = null;

async function launchProject(goal) {
  const token = await getSessionToken();
  if (!token) { showToast('Not logged in', 'error'); return; }

  showToast('Decomposing goal…', 'info', 4000);
  switchViewMode('agents');

  try {
    const resp = await authFetch(`${API_BASE}/project/start`, {
      method: 'POST',
      body: JSON.stringify({ goal }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    _activeProject = data;
    appendMessage('assistant', data.message);
    renderProjectBoard(data.tasks);
    connectProjectStream(data.project_id, token);
  } catch (e) {
    showToast('Project launch failed: ' + e.message, 'error');
    console.error('[project] launch error:', e);
  }
}

function connectProjectStream(projectId, token) {
  if (_projectEventSource) _projectEventSource.close();
  const url = `${API_BASE}/project/stream/${projectId}?token=${encodeURIComponent(token)}`;
  _projectEventSource = new EventSource(url);
  _projectEventSource.onmessage = e => {
    try { handleProjectEvent(JSON.parse(e.data)); } catch (_) {}
  };
  _projectEventSource.onerror = () => {
    _projectEventSource.close();
    showToast('Project stream disconnected', 'warning', 3000);
  };
}

function handleProjectEvent(ev) {
  switch (ev.type) {
    case 'task_start':
      _setTaskStatus(ev.task_id, 'running', ev);
      showToast(`▶ ${ev.title}`, 'info', 1800);
      break;
    case 'task_done':
      _setTaskStatus(ev.task_id, 'done', ev);
      break;
    case 'task_failed':
      _setTaskStatus(ev.task_id, 'failed', ev);
      showToast(`✗ ${ev.title} failed`, 'error', 3000);
      break;
    case 'task_blocked':
      _setTaskStatus(ev.task_id, 'blocked', ev);
      break;
    case 'project_done': {
      if (_projectEventSource) _projectEventSource.close();
      const ok = ev.status === 'done';
      const msg = `${ok ? '✅' : '⚠️'} Project ${ev.status}: ${ev.done}/${ev.total} tasks completed`;
      appendMessage('assistant', msg);
      showToast(msg, ok ? 'success' : 'warning', 5000);
      break;
    }
  }
}

function renderProjectBoard(tasks) {
  const panel = document.querySelector('#agents-panel, .agents-panel');
  if (!panel) return;

  const old = document.getElementById('project-board');
  if (old) old.remove();

  const board = document.createElement('div');
  board.id = 'project-board';
  board.style.cssText = 'padding:12px;display:flex;flex-direction:column;gap:8px;';
  board.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
      <span style="font-size:11px;font-weight:700;letter-spacing:.08em;color:var(--accent,#4fc3f7);">
        PROJECT ${(_activeProject||{}).project_id||''}
      </span>
      <span style="font-size:10px;color:var(--text-secondary,#888);">${tasks.length} tasks</span>
    </div>
    <div id="project-task-grid" style="display:flex;flex-direction:column;gap:6px;">
      ${tasks.map(t => `
        <div id="ptask-${t.task_id}"
             style="background:var(--bg-secondary,#1a1a2e);border:1px solid var(--border,#333);border-radius:6px;padding:8px 10px;transition:border-color .2s;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="font-size:9px;font-weight:700;letter-spacing:.06em;
                         color:${_roleColor(t.role)};text-transform:uppercase;">${t.role}</span>
            <span class="ptask-status" style="font-size:9px;color:#666;">pending</span>
          </div>
          <div style="font-size:11px;font-weight:600;margin:3px 0 1px;color:var(--text,#eee);">${t.title}</div>
          <div style="font-size:10px;color:var(--text-secondary,#888);">${t.agent_name||t.role}</div>
          <div class="ptask-qopc" style="font-size:9px;color:#666;margin-top:2px;"></div>
        </div>
      `).join('')}
    </div>`;

  panel.prepend(board);
}

function _roleColor(role) {
  const map = {backend:'#7c3aed',frontend:'#0ea5e9',database:'#10b981',
               devops:'#f59e0b',testing:'#ef4444',docs:'#6b7280',agent:'#ec4899'};
  return map[role] || '#888';
}

function _setTaskStatus(taskId, status, ev) {
  const card = document.getElementById('ptask-' + taskId);
  if (!card) return;
  const label = card.querySelector('.ptask-status');
  if (label) label.textContent = status;
  const colors = {running:'#f59e0b',done:'#10b981',failed:'#ef4444',blocked:'#666'};
  card.style.borderColor = colors[status] || '#333';
  if (ev && ev.qopc_score > 0) {
    const q = card.querySelector('.ptask-qopc');
    if (q) q.textContent = `QOPC ${(ev.qopc_score*100).toFixed(0)}%`;
  }
  if (status === 'failed' && ev && ev.error) card.title = ev.error;
}

async function loadProjectContext(projectId) {
  try {
    const resp = await authFetch(`${API_BASE}/project/context/${projectId}`);
    return resp.ok ? await resp.json() : null;
  } catch(e) { return null; }
}
"""
