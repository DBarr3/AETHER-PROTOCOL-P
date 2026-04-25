# Bug Investigation: Agent Terminal Launch

**Date:** 2026-04-24  
**Branch:** `claude/agent-terminal-launch-investigation`  
**Investigator:** Claude (Session L — non-destructive audit)  
**Verdict:** Hypothesis B — Feature **partially implemented** (confidence: 97%)

---

## 1. USER-REPORTED SYMPTOM

> User flow:
> 1. User clicks on an agent in the desktop app to view context
> 2. A popup/modal appears showing the agent
> 3. Popup contains a "Launch Agent Terminal" button
> 4. **Expected:** clicking the button opens a live CLI terminal connected to the agent/subagent (Claude), shows progress in real-time, allows the user to manually assign tasks to subagents
> 5. **Actual:** the button either does nothing, opens a blank/transparent window, or otherwise fails to produce a working terminal

---

## 2. FILES IN THE SURFACE AREA

| File | Lines (approx) | Last Modified | Last Commit |
|------|---------------|---------------|-------------|
| `desktop/main.js` | 1365 | 2026-04-21 | `69a9934` — Summary |
| `desktop/preload.js` | 277 | 2026-04-21 | `69a9934` — Summary |
| `desktop/pages/dashboard.html` | ~16750 | 2026-04-21 | `69a9934` — Summary |
| `desktop/pages/terminal.html` | 401 | 2026-04-17 | `8f13e66` — security: apply 17-finding audit sweep |
| `desktop/package.json` | 109 | 2026-04-21 | `69a9934` — Summary |

**No PTY library installed.** `desktop/package.json` dependencies:
```json
"dependencies": {
  "dompurify": "^3.4.0",
  "electron-store": "^8.2.0",
  "node-machine-id": "^1.1.12"
}
```
No `node-pty`, no `xterm`, no `xterm-addon-fit`.

---

## 3. WIRING CHAIN — WHAT I FOUND

### 3a. The "Launch Agent Terminal" context menu item

**UI entry point:** `desktop/pages/dashboard.html:5168`
```html
<div class="ctx-menu-item" data-action="terminal">
  <span class="ctx-menu-icon">&#9654;</span>Launch Agent Terminal
</div>
```
This context menu (`#agent-ctx-menu`) appears on right-click of V3 agent cards.

**Click handler dispatch:** `dashboard.html:11153`
```javascript
function v3HandleCtxAction(action) {
  const agent = V3.ctxAgent;
  closeAgentContextMenu();
  if (!agent) return;
  switch (action) {
    case 'terminal':
      showToast('Agent Terminal for ' + agent.name + ' — coming soon', 'info'); // ← STUB
      console.log('agent terminal: TODO', agent);
      break;
```
**This is a stub.** It shows a "coming soon" toast and does nothing else.

### 3b. Agent Presence card click (animated agent icons)

**UI entry point:** `dashboard.html:11448`
```javascript
function onCardClick(agentIdStr) {
  const agent = activeAgents.find(a => String(a.id) === String(agentIdStr));
  if (!agent) return;
  // TODO: wire to V6 agent terminal bridge when available
  console.log('agent terminal: TODO', agent);
  showToast('Agent Terminal for ' + (agent.name || 'agent') + ' — coming soon', 'info'); // ← STUB
}
```
**Also a stub.** Both entry points a user would naturally click produce only a toast.

### 3c. The IPC chain (fully implemented — never reached from stubs)

The following layers ARE fully wired and working:

**Renderer → Preload:** `preload.js:62`
```javascript
terminalOpen: (config) => ipcRenderer.invoke('terminal:open', config),
```

**Main process handler:** `main.js:741–797`
```javascript
ipcMain.handle('terminal:open', async (_e, config) => {
  // key: 'agent-{id}' or 'team-{name}'
  const win = new BrowserWindow({ width: 680, height: 480, ... });
  win.loadFile(path.join(PAGES_DIR, 'terminal.html'));  // EXISTS ✓
  win.webContents.send('terminal:init', config);
  terminalWindows.set(key, win);
  return { opened: true };
});
```

**Terminal page:** `desktop/pages/terminal.html` — EXISTS and is fully implemented:
- Receives `terminal:init` config with agent profile
- Renders styled terminal UI (IBM Plex Mono, dark theme)
- Sends messages to VPS via `/agent/chat` or `/agent/mcp-chat`
- Conversation memory via `localStorage`
- Supports both single-agent and team modes
- Window controls (minimize, maximize, close) wired

### 3d. Working entry points (different surfaces)

Two entry points DO call `window.aether.terminalOpen` correctly:

1. **Agent Profile "TERMINAL" button** (`dashboard.html:15473,15483`) → `profileOpenTerminal()` (`dashboard.html:16145`) — **WORKS**
2. **"TEAM TERMINAL" button** (`dashboard.html:5361`) → `openTeamTerminal()` — early stub at 11251 is overridden by `window.openTeamTerminal = async function()` at line 16704 — **WORKS**

### 3e. ASCII: Intended vs. Actual Flow

```
INTENDED FLOW:
User right-clicks agent
    → context menu appears
    → clicks "Launch Agent Terminal"
    → v3HandleCtxAction('terminal')
    → window.aether.terminalOpen({ type:'agent', agentId, agentName, agentProfile, ... })
    → ipcRenderer.invoke('terminal:open', config)
    → main.js: new BrowserWindow → loads terminal.html
    → terminal.html: receives config, renders UI, connects to VPS /agent/chat
    → LIVE TERMINAL ✓

ACTUAL FLOW:
User right-clicks agent
    → context menu appears
    → clicks "Launch Agent Terminal"
    → v3HandleCtxAction('terminal')
    → showToast('...coming soon...') ← DEAD END
    → nothing else happens
```

---

## 4. ROOT CAUSE HYPOTHESES (ranked by likelihood)

### Hypothesis B — Feature partially implemented (**97% confidence — VERDICT**)

**Evidence:**
- `terminal:open` IPC handler: fully implemented (`main.js:741`)
- `terminal.html`: fully implemented (401 lines, complete UI + VPS chat)
- `preload.js` bridge: fully implemented (`preload.js:62`)
- `profileOpenTerminal()` and overriding `openTeamTerminal()`: both call `window.aether.terminalOpen` and work
- The two broken stubs are **specifically** `v3HandleCtxAction('terminal')` (`dashboard.html:11158`) and `AgentPresence.onCardClick()` (`dashboard.html:11451`)
- Both have explicit `// TODO` comments referencing a "V6 agent terminal bridge"
- git history shows `terminal.html` was created in commit `1731f6d` ("feat: create agent terminal window") but the V3 context menu stub was never updated to call it

### Hypothesis A — Feature never implemented (2% confidence)

Ruled out: `terminal.html`, the IPC handler, and the preload bridge all exist and are complete. Two entry points already work.

### Hypothesis C — Feature fully implemented but recently broken by a patch (1% confidence)

Ruled out: The stubs contain explicit `// TODO` markers and "coming soon" strings indicating they were never wired, not that they were broken.

### Hypothesis D — Environmental (0% confidence)

Ruled out: No PTY dependency is involved. The terminal uses a simple `<input>` + VPS HTTP fetch, not a real PTY. No OS permissions are required.

---

## 5. WHAT IS MISSING OR BROKEN

### Primary fix required (1 file, ~20 lines changed):

**File:** `desktop/pages/dashboard.html`

**Fix 1 — `v3HandleCtxAction` (`dashboard.html:11158`):**
Replace the stub with a call to `window.aether.terminalOpen`. The `V3.ctxAgent` object needs to be matched against stored profiles to get the full `agentProfile` payload (which includes `systemPrompt`, `mcpAgents`, etc.).

```javascript
// BEFORE (stub):
case 'terminal':
  showToast('Agent Terminal for ' + agent.name + ' — coming soon', 'info');
  console.log('agent terminal: TODO', agent);
  break;

// AFTER (wired):
case 'terminal':
  (async () => {
    const profiles = await window.aether.agentLoadProfiles();
    const profile = profiles.find(p => p.id === agent.id || p.name === agent.name) || agent;
    const icons = await window.aether.agentLoadIcons();
    const icon = icons.find(i => i.name === profile.icon);
    await window.aether.terminalOpen({
      type: 'agent',
      agentId: profile.id,
      agentName: profile.name,
      agentDescription: profile.description || '',
      agentIcon: icon ? icon.svgContent : '',
      agentProfile: profile,
      agentAnimData: null,
      apiBase: typeof API_BASE !== 'undefined' ? API_BASE : 'https://api.aethersystems.net/cloud',
    });
  })();
  break;
```

**Fix 2 — `AgentPresence.onCardClick` (`dashboard.html:11451`):**
Same pattern — load profile by agent id/name, then call `window.aether.terminalOpen`.

### Secondary bug (non-blocking):

**File:** `desktop/pages/terminal.html:281`
```javascript
// BUG: window.aether.authGet is undefined — should be window.aetherAPI.authGet
var authData = await window.aether.authGet();
```
This silently fails (caught by try/catch) so MCP agents get `token = null` and their HTTP requests return 401. Non-MCP agents are unaffected because they use `window.aetherAPI.chat()` which resolves the token internally via `apiFetch`.

**Fix:** `window.aether.authGet()` → `window.aetherAPI.authGet()` at `terminal.html:281`.

### No new dependencies needed:
The terminal does NOT use node-pty or xterm.js. It uses a custom `<input>` bar + HTTP fetch to the VPS `/agent/chat` endpoint. No native modules are required.

---

## 6. PROPOSED IMPLEMENTATION PLAN

**Hypothesis B path — targeted fix, ~1 session, ~30–45 minutes:**

### Session M — `fix(terminal): wire V3 context menu + presence card to terminal launch`

**Files to modify:**
1. `desktop/pages/dashboard.html`
   - `v3HandleCtxAction` case `'terminal'` (`line 11158`): replace stub with `window.aether.terminalOpen` call
   - `AgentPresence.onCardClick` (`line 11451`): replace stub with `window.aether.terminalOpen` call
2. `desktop/pages/terminal.html`
   - `line 281`: fix `window.aether.authGet()` → `window.aetherAPI.authGet()`

**Verification steps:**
1. `cd desktop && npm start`
2. Log in → navigate to dashboard
3. Right-click any agent card → click "Launch Agent Terminal" → 680×480 terminal window opens, agent name in titlebar, input bar active
4. Click an animated agent presence card → same result
5. Send a message in terminal → agent responds via VPS
6. Test with MCP agent → verify no 401 in DevTools Network tab

**Estimated effort:** 1 session, <1 hour. Extremely low risk — no architectural changes, no new dependencies, no IPC changes. Two line-level swaps and one namespace correction.

---

## 7. OPEN QUESTIONS FOR USER

1. **Terminal type:** The current `terminal.html` is NOT a real PTY — it is an `<input>` bar that sends to the VPS `/agent/chat` HTTP endpoint. Is this the intended UX long-term, or do you want a real PTY (`node-pty` + `xterm.js`) that spawns a local subprocess?

2. **V3 agent vs. agent profile mismatch:** V3 context menu agents come from `spawnedAgents` (runtime state), while `terminal.html` expects a full `agentProfile` object with `systemPrompt`, `mcpAgents`, etc. If a spawned agent has no matching saved profile, should the terminal open with a minimal fallback config, or should it prompt the user to save the agent first?

3. **MCP auth fix priority:** Fixing `window.aether.authGet()` → `window.aetherAPI.authGet()` is low-risk but will change behavior for MCP agent terminal sessions — they will start sending auth tokens where they previously sent none. Confirm this is desired before including in the fix PR.

4. **Claude Code integration:** The bug report mentions a "live CLI terminal connected to Claude." The current implementation connects to the VPS `/agent/chat` HTTP endpoint — not Claude Code CLI or the Anthropic API directly. Should a future version spawn a real `claude` subprocess in a PTY? This would require `node-pty` + `xterm.js` and is a separate, larger effort.

5. **Security scope for real PTY (if desired):** If a real PTY is wanted, what filesystem/network restrictions should apply to the spawned subprocess?

---

## 8. RECOMMENDED NEXT SESSION

**Branch:** `claude/fix-agent-terminal-launch`  
**Base:** `main`

**Files to modify:**
- `desktop/pages/dashboard.html` — 2 stub replacements (~20 lines total)
- `desktop/pages/terminal.html` — 1 line fix (`authGet` namespace)

**Tests to add:**
- Manual: right-click agent → Launch Agent Terminal → window opens with correct agent name
- Manual: presence card click → same result
- Manual: MCP agent terminal → no 401 in DevTools Network tab

**Disk budget:** Trivial — only editing existing files, no new assets.  
**Time budget:** ~45 minutes including test run.

---

## SESSION REPORT

| Item | Value |
|------|-------|
| Time spent | ~40 minutes |
| Disk at start | 568 GB free |
| Disk at end | 568 GB free |
| Hypothesis verdict | **B — Partially implemented** (97% confidence) |
| Files touched | 1 (this design doc only) |
| Code modified | None |
| Follow-up sessions dispatched | None |

**Dead-ends encountered:**
- Initial grep for "Launch Agent Terminal" across `*.ts/*.tsx/*.js/*.jsx` returned no results — the desktop app uses plain `.html` files with inline `<script>` blocks, not a compiled React/TypeScript build. Pivoted to `Select-String` on `.html` files directly.
- Root-level `.html` files (`aethercloud-desktop.html`, etc.) are UI design prototypes, not the live app. Live app pages are in `desktop/pages/`.
