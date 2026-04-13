# Agent Profile System — Design Spec

**Date:** 2026-04-12  
**Scope:** Replace TEAM sub-tab with full Agent Profile management system  
**Target files:** `desktop/pages/dashboard.html`, `desktop/main.js`, `desktop/preload.js`

---

## 1. Architecture

**Approach:** IIFE module pattern inline in `dashboard.html`, replacing the existing Agent Team Config IIFE (lines 10997-11753) and its HTML panel (lines 2783-2851).

**Integration points:**
- Rename sub-tab button `asub-team` label from "TEAM" to "PROFILES"
- Replace `agent-team-panel` HTML with new profile system markup
- Replace team config IIFE with profile system IIFE
- Update `switchAgentSubTab('team')` to call `profilePanelInit()` instead of `teamPanelInit()`
- Add 4 IPC handlers in `main.js`
- Add 4 matching methods in `preload.js` under `window.aether`
- Create `agent/profiles/` and `agent/skills/` directories

**What stays unchanged:**
- ORBIT sub-tab, circuit visualization, spawned agents system
- `switchViewMode()` logic
- All other IPC handlers and preload methods

---

## 2. Panel Layout

The `agent-team-panel` div becomes a two-pane layout:

### Left pane (240px fixed) — Agent List Sidebar
- Header: "AGENTS" label + profile count badge
- Team dropdown pill (Default Team / Research / Automation / Security)
- Scrollable list of saved agent cards (48px icon + name + description snippet)
- `[+ NEW AGENT]` button at top of list
- Empty state: centered icon grid + "Create your first agent" CTA when zero profiles

### Right pane (flex:1) — Profile Editor
- Vertical scroll with collapsible sections
- Sticky save bar pinned to bottom

---

## 3. Profile Editor Sections

### 3A — Identity Section
- **Icon Picker:** Grid of all SVG icons from `agent/agents/` directory. Each icon in a 56x56 rounded tile. Hover: border glow. Selected: accent border + checkmark. Icons loaded via IPC `agent:loadIcons`.
- **Selected icon** renders large (72px) to the left of the name/description fields
- **Name input:** monospace, uppercase placeholder "ENTER DESIGNATION...", max 32 chars with counter
- **Description textarea:** 3 rows, placeholder "Describe this agent's role and purpose..."

### 3B — System Prompt Section (collapsible, default collapsed)
- Toggle header: "SYSTEM PROMPT [EXPAND/COLLAPSE]"
- Full-height monospace `<textarea>` (min-height 200px)
- Placeholder: "You are [AGENT NAME], an AI agent operating within AetherCloud... Define behavior, tone, restrictions, and context here."
- **Template loader** dropdown button with presets:
  - Analyst — data interpretation, structured output
  - Executor — task automation, action-oriented
  - Sentinel — security monitoring, threat detection
  - Researcher — open-ended investigation and synthesis
  - Custom — blank
- Token counter (char count / estimated tokens) bottom-right

### 3C — Tasks Section
- Header: "TASKS" with `[+ ADD TASK]` button
- Each task row:
  - Task name input (inline, ~200px)
  - Task description textarea (2 rows)
  - Priority: segmented control — LOW | MEDIUM | HIGH | CRITICAL
  - Trigger: dropdown — Manual | Scheduled | Event | Chained
  - Up/down reorder arrows
  - Delete `[x]` button
- Max 10 tasks per agent
- Empty state: "No tasks configured"

### 3D — MCP Agents Section
- Header: "MCP AGENTS" with subheader "Connect model context protocol tools to this agent."
- Active MCPs shown as accent-colored chip/tags at top
- Searchable list of available MCPs (reads from `mcp/` directory if present, plus hardcoded defaults from existing SERVER_COLOR_MAP)
- Each MCP entry: name, description snippet, status badge (ACTIVE/INACTIVE), toggle switch
- `[+ INSTALL MCP]` expands inline form: name, URL/path, transport selector (SSE/STDIO/HTTP), save button

### 3E — Skills Section
- Header: "SKILLS" with subheader "Attach skill modules to this agent."
- Active skills shown as colored chip/tags at top
- List of available skills from `agent/skills/` directory
- Each skill: name, description, version badge, toggle switch
- `[+ ADD SKILL]` expands inline form: name, description, config textarea, save button

### 3F — Save Bar (sticky bottom)
- `[SAVE AGENT]` — primary filled button, cyan accent
- `[EXPORT CONFIG]` — outlined button, downloads JSON
- `[DUPLICATE]` — outlined button, copies profile with `_copy` suffix
- `[DELETE AGENT]` — red outlined button, confirmation dialog before delete

---

## 4. Data Model

Profiles stored as JSON at `agent/profiles/{id}.json`:

```json
{
  "id": "uuid-v4",
  "name": "WRAITH",
  "icon": "purple_ghost_agent",
  "description": "Stealth recon agent for passive network analysis.",
  "team": "Security",
  "systemPrompt": "You are WRAITH, a stealth-mode AI agent...",
  "tasks": [
    {
      "id": "task-uuid",
      "name": "Passive Scan",
      "description": "Run passive network reconnaissance.",
      "priority": "HIGH",
      "trigger": "Manual"
    }
  ],
  "mcpAgents": ["github", "slack"],
  "skills": ["osint-engine"],
  "createdAt": "2026-04-12T00:00:00.000Z",
  "updatedAt": "2026-04-12T00:00:00.000Z"
}
```

---

## 5. IPC Handlers

### main.js additions (4 handlers)

```
agent:loadIcons    — reads agent/agents/*.svg, returns [{name, svgContent}]
agent:loadProfiles — reads agent/profiles/*.json, returns profile[]
agent:saveProfile  — writes profile JSON to agent/profiles/{id}.json
agent:deleteProfile — removes agent/profiles/{id}.json
```

### preload.js additions (under window.aether)

```
agentLoadIcons:    () => ipcRenderer.invoke('agent:loadIcons')
agentLoadProfiles: () => ipcRenderer.invoke('agent:loadProfiles')
agentSaveProfile:  (profile) => ipcRenderer.invoke('agent:saveProfile', profile)
agentDeleteProfile:(id) => ipcRenderer.invoke('agent:deleteProfile', id)
```

---

## 6. Styling

Uses existing CSS variables:
- `--bg`, `--bg-2`, `--bg-3`, `--bg-4` for backgrounds
- `--accent` (#00d4ff) for primary actions and focus rings
- `--border`, `--border-2` for dividers
- `--font-mono` for all text
- `--green`, `--amber`, `--red` for status/priority colors

New CSS added inline in `<style>` block:
- `.profile-panel` — two-pane flex layout
- `.profile-sidebar` — 240px fixed left pane
- `.profile-editor` — scrollable right pane
- `.icon-picker-grid` — CSS grid, 7 columns, gap 8px
- `.icon-tile` — 56x56 rounded square with hover/active states
- `.section-collapsible` — animated expand/collapse (max-height transition 200ms)
- `.task-row` — flex row with inline controls
- `.priority-seg` — segmented control buttons
- `.mcp-chip` / `.skill-chip` — accent-colored tags
- `.save-bar` — sticky bottom with backdrop-filter blur

---

## 7. Directories to Create

```
agent/profiles/   — stores agent profile JSON files
agent/skills/     — stores skill config files
```

---

## 8. Removed Code

- Team config HTML panel (dashboard.html lines 2783-2851)
- Team config IIFE (dashboard.html lines 10997-11753)
- `teamPanelInit`, `teamLoadFromVault`, `teamSVG`, `teamRenderSidebar`, `teamShowEditor`, `teamSaveAgent` and all team-related functions within the IIFE
- `TEAM_PIXELS`, `TEAM_COLORS`, `SERVER_COLOR_MAP`, `SERVER_PERMS`, `PERM_CATALOG` constants

---

## 9. Implementation Order

1. Create directories (`agent/profiles/`, `agent/skills/`)
2. Add IPC handlers to `main.js`
3. Add preload methods to `preload.js`
4. Replace team panel HTML in dashboard.html with new profile panel markup
5. Add new CSS styles in dashboard.html `<style>` block
6. Replace team config IIFE with profile system IIFE
7. Update `switchAgentSubTab` to call `profilePanelInit()`
8. Rename sub-tab button label from "TEAM" to "PROFILES"
9. Test: create, save, reload, edit, delete cycle
10. Test: icon loading across all 20 agent SVGs
