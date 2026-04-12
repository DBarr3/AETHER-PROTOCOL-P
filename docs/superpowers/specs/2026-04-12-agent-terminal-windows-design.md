# Agent & Team Terminal Windows — Design Spec

**Date:** 2026-04-12
**Scope:** Separate Electron BrowserWindows for agent/team terminal sessions with conversation memory and MCP tool execution

---

## 1. Architecture

Each terminal opens as a **real separate Electron BrowserWindow** — a frameless popup that loads `pages/terminal.html` with the same `preload.js` as the dashboard. This gives the terminal access to `window.aetherAPI.chat()` and `window.aether.*` methods without new IPC handlers for chat.

**Chat routing:**
- If agent has `mcpAgents` populated → use `/agent/mcp-chat` with `mcp_servers` field populated
- If agent has no MCPs → use `/agent/chat` (standard)
- Both paths inject the agent's `systemPrompt` into the query

**Conversation memory:** Stored in `localStorage` within the terminal window, keyed by `terminal:{agentId}`. On each exchange, the user message + agent response are appended. The last N turns (configurable, default 10) are passed as `conversation_history` to the API on each request. This provides multi-turn context within and across sessions (localStorage persists across window reopens).

**MCP tool visibility:** When the response from `/agent/mcp-chat` includes `tools_used`, the terminal prints `[TOOL] toolname` lines in amber before the agent's response text.

---

## 2. Files

| File | Action | Purpose |
|------|--------|---------|
| `desktop/pages/terminal.html` | Create | Terminal window — HTML, CSS, JS all inline |
| `desktop/main.js` | Modify | Add `terminalWindows` Map + `terminal:open` IPC + window controls |
| `desktop/preload.js` | Modify | Add `terminalOpen`, `terminalInit`, window control bridge methods |
| `desktop/pages/dashboard.html` | Modify | Add "Terminal" buttons to PROFILES panel |

---

## 3. Terminal Window Features

### 3A — Titlebar
- Custom frameless titlebar (matches dashboard pattern: `-webkit-app-region: drag`)
- macOS-style close/minimize/maximize dots
- Agent icon badge (inline SVG passed via config)
- Agent name + description sublabel
- Status dot: ready (green) / working (amber pulsing) / error (red)

### 3B — Output Area
- Scrollable terminal-style output
- Line types with distinct colors:
  - `system` — cyan prefix, muted text (welcome, status)
  - `user` — green prefix, white text
  - `agent` — orange prefix, light gray text, pre-wrap
  - `tool` — amber text, monospace (`[TOOL] gmail → search_emails`)
  - `error` — red text
  - `muted` — dark gray, italic (thinking indicators)
- Dividers between agent responses in team mode

### 3C — Input Bar
- Green `❯` prompt
- Text input with monospace font
- SEND button (cyan accent)
- Disabled state while agent is thinking
- Enter key triggers send

### 3D — Conversation Memory
- On init: load `localStorage.getItem('terminal:' + agentId)` → parse as JSON array of `{role, content}` turns
- On each exchange: append `{role:'user', content}` + `{role:'assistant', content}` to the array
- Save back to localStorage after each exchange
- Before API call: include last 10 turns as `conversation_history` parameter
- Team terminals: separate memory per team name (`terminal:team:{teamName}`)
- Print a "Loaded N previous exchanges" system line if history exists on open

### 3E — MCP Tool Execution
- On send: check if agent profile has `mcpAgents.length > 0`
- If yes: route to `/agent/mcp-chat` with `mcp_servers` populated from profile
- If no: route to `/agent/chat` (standard)
- When response includes `tools_used` array: print each as `[TOOL] toolname` in amber before the response text
- Team terminal: each agent uses its own MCP config independently

---

## 4. IPC Additions

### main.js
- `terminalWindows` Map (key: `agent-{id}` or `team-{teamName}`)
- `terminal:open` handler — creates BrowserWindow, sends config via `webContents.send('terminal:init', config)`
- `terminal:minimize`, `terminal:maximize`, `terminal:close` — frameless window controls

### preload.js (added to `window.aether`)
- `terminalOpen(config)` → `ipcRenderer.invoke('terminal:open', config)`
- `terminalInit(callback)` → `ipcRenderer.on('terminal:init', (e, config) => callback(config))`
- `terminalMinimize()` → `ipcRenderer.send('terminal:minimize')`
- `terminalMaximize()` → `ipcRenderer.send('terminal:maximize')`
- `terminalClose()` → `ipcRenderer.send('terminal:close')`

---

## 5. Config Object Shape

Passed from dashboard → main process → terminal window:

```json
{
  "type": "agent",
  "agentId": "uuid",
  "agentName": "WRAITH",
  "agentDescription": "Stealth recon agent",
  "agentIcon": "<svg>...</svg>",
  "agentProfile": { "id": "...", "systemPrompt": "...", "mcpAgents": ["gmail", "slack"], ... },
  "apiBase": "https://api.aethersystems.net/cloud"
}
```

Team variant:
```json
{
  "type": "team",
  "teamName": "Security",
  "agentProfiles": [ { ...profile1 }, { ...profile2 } ],
  "agentIcons": { "icon_name": "<svg>..." },
  "apiBase": "https://api.aethersystems.net/cloud"
}
```

---

## 6. Dashboard Integration

### PROFILES panel — per-agent terminal button
- In the profile editor save bar, add a "TERMINAL" button (outlined, between EXPORT and DELETE)
- Calls `window.aether.terminalOpen({ type: 'agent', ... })` with current profile data

### PROFILES panel — team terminal button
- In the profile panel header bar (next to RUN TEAM), add "TEAM TERMINAL" button
- Loads all profiles for current team filter, passes as `agentProfiles` array

---

## 7. Removed from Scope
- Streaming responses (single response per API call)
- File attachments / drag-drop
- Terminal-to-terminal communication
- Custom themes per agent
- Command history (up arrow) — could add later
