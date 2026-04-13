# Agent Profile System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the TEAM sub-tab in the Agents view with a full Agent Profile management system — icon picker, identity editor, system prompt, tasks, MCP agents, skills, with local JSON persistence.

**Architecture:** IIFE module pattern inline in `dashboard.html`, replacing the existing Agent Team Config IIFE (lines 10997-11753) and its HTML panel (lines 2783-2851). Four new IPC handlers in `main.js` for file-based persistence. Preload bridge methods added to `window.aether`.

**Tech Stack:** Vanilla JS, Electron IPC (ipcMain.handle / ipcRenderer.invoke), SVG pixel-art icons, CSS Grid, JSON file storage.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `desktop/main.js` | Modify (lines ~365) | Add 4 IPC handlers for agent profile CRUD + icon loading |
| `desktop/preload.js` | Modify (line ~54) | Add 4 bridge methods to `window.aether` object |
| `desktop/pages/dashboard.html` | Modify (4 regions) | CSS, HTML panel, sub-tab label, IIFE replacement |
| `agent/profiles/` | Create directory | JSON profile storage |
| `agent/skills/` | Create directory | Skill config storage |

### dashboard.html edit regions:
1. **CSS** (lines ~2482-2587): Replace `.team-*` styles with `.profile-*` styles
2. **HTML** (lines 2783-2851): Replace `agent-team-panel` contents with new profile panel markup
3. **Sub-tab label** (line 2647): Change "TEAM" to "PROFILES"
4. **IIFE** (lines 10997-11753): Replace team config IIFE with profile system IIFE
5. **switchAgentSubTab** (line 7102): Change `teamPanelInit` to `profilePanelInit`

---

## Task 1: Create directories + IPC handlers in main.js

**Files:**
- Create: `agent/profiles/` (directory)
- Create: `agent/skills/` (directory)
- Modify: `desktop/main.js:365` (after `fs:previewPlan` handler block)

- [ ] **Step 1: Create the directories**

```bash
mkdir -p agent/profiles agent/skills
```

- [ ] **Step 2: Add IPC handlers to main.js**

Insert after line 365 (after the `fs:previewPlan` handler closing `});`), before the `// Preview a plan` comment at line 367. Actually, insert after the `fs:previewPlan` handler block ends. Find the line `});` that closes `fs:previewPlan` (around line 390-400) and add after it:

```javascript
// ── IPC: Agent Profile System ───────────────────────
ipcMain.handle('agent:loadIcons', async () => {
  const iconsPath = path.join(__dirname, '..', 'agent', 'agents');
  try {
    const files = fs.readdirSync(iconsPath).filter(f => f.endsWith('.svg'));
    return files.map(file => ({
      name: path.basename(file, '.svg'),
      svgContent: fs.readFileSync(path.join(iconsPath, file), 'utf-8'),
    }));
  } catch (e) {
    console.error('[agent:loadIcons]', e.message);
    return [];
  }
});

ipcMain.handle('agent:loadProfiles', async () => {
  const profilesPath = path.join(__dirname, '..', 'agent', 'profiles');
  try {
    if (!fs.existsSync(profilesPath)) fs.mkdirSync(profilesPath, { recursive: true });
    const files = fs.readdirSync(profilesPath).filter(f => f.endsWith('.json'));
    return files.map(file => {
      try { return JSON.parse(fs.readFileSync(path.join(profilesPath, file), 'utf-8')); }
      catch { return null; }
    }).filter(Boolean);
  } catch (e) {
    console.error('[agent:loadProfiles]', e.message);
    return [];
  }
});

ipcMain.handle('agent:saveProfile', async (_e, profile) => {
  const profilesPath = path.join(__dirname, '..', 'agent', 'profiles');
  if (!fs.existsSync(profilesPath)) fs.mkdirSync(profilesPath, { recursive: true });
  const filePath = path.join(profilesPath, `${profile.id}.json`);
  fs.writeFileSync(filePath, JSON.stringify(profile, null, 2));
  return { success: true, path: filePath };
});

ipcMain.handle('agent:deleteProfile', async (_e, profileId) => {
  const filePath = path.join(__dirname, '..', 'agent', 'profiles', `${profileId}.json`);
  try {
    if (fs.existsSync(filePath)) fs.unlinkSync(filePath);
    return { success: true };
  } catch (e) {
    return { success: false, error: e.message };
  }
});
```

- [ ] **Step 3: Commit**

```bash
git add agent/profiles agent/skills desktop/main.js
git commit -m "feat: add agent profile IPC handlers and directories"
```

---

## Task 2: Add preload bridge methods

**Files:**
- Modify: `desktop/preload.js:53-54` (inside `window.aether` object, before closing `});`)

- [ ] **Step 1: Add agent profile methods to window.aether**

In `desktop/preload.js`, find line 54 where `previewPlan` is defined (the last entry before the closing `});` of the `window.aether` object). Add after `previewPlan`:

```javascript
  // Agent Profile System
  agentLoadIcons:    () => ipcRenderer.invoke('agent:loadIcons'),
  agentLoadProfiles: () => ipcRenderer.invoke('agent:loadProfiles'),
  agentSaveProfile:  (profile) => ipcRenderer.invoke('agent:saveProfile', profile),
  agentDeleteProfile:(id) => ipcRenderer.invoke('agent:deleteProfile', id),
```

The `window.aether` object should now end like:

```javascript
  execPlan:    (actions) => ipcRenderer.invoke('fs:execPlan', actions),
  previewPlan: (actions) => ipcRenderer.invoke('fs:previewPlan', actions),
  // Agent Profile System
  agentLoadIcons:    () => ipcRenderer.invoke('agent:loadIcons'),
  agentLoadProfiles: () => ipcRenderer.invoke('agent:loadProfiles'),
  agentSaveProfile:  (profile) => ipcRenderer.invoke('agent:saveProfile', profile),
  agentDeleteProfile:(id) => ipcRenderer.invoke('agent:deleteProfile', id),
});
```

- [ ] **Step 2: Commit**

```bash
git add desktop/preload.js
git commit -m "feat: add agent profile bridge methods to preload"
```

---

## Task 3: Replace CSS styles in dashboard.html

**Files:**
- Modify: `desktop/pages/dashboard.html:2482-2588` (replace `/* ── Agent Team Panel */` CSS block)

- [ ] **Step 1: Replace the team CSS block**

Find the CSS block starting at line 2482 (`/* ── Agent Team Panel ──`) through line 2587 (`.team-empty-sub` rule). Replace the entire block with the new profile system styles:

```css
  /* ── Agent Profile Panel ─────────────────────────── */
  .profile-sidebar {
    width:240px;flex-shrink:0;border-right:1px solid var(--border);
    display:flex;flex-direction:column;overflow:hidden;background:var(--bg-2);
  }
  .profile-sidebar-header {
    padding:12px 14px;border-bottom:1px solid var(--border);
    display:flex;align-items:center;gap:8px;flex-shrink:0;
  }
  .profile-sidebar-title {
    font-family:var(--font-mono);font-size:10px;font-weight:600;
    letter-spacing:0.12em;text-transform:uppercase;color:var(--accent);
  }
  .profile-count-badge {
    font-family:var(--font-mono);font-size:9px;padding:1px 6px;
    background:var(--accent-dim);color:var(--accent);
    border:1px solid var(--accent-border);
  }
  .profile-team-pill {
    font-family:var(--font-mono);font-size:9px;padding:4px 10px;
    background:var(--bg-3);border:1px solid var(--border-2);color:var(--text-muted);
    cursor:pointer;transition:all 0.15s;display:flex;align-items:center;gap:4px;
    position:relative;
  }
  .profile-team-pill:hover { border-color:var(--accent);color:var(--text-primary); }
  .profile-team-dropdown {
    position:absolute;top:100%;left:0;right:0;z-index:10;
    background:var(--bg-3);border:1px solid var(--border-2);display:none;
  }
  .profile-team-dropdown.open { display:block; }
  .profile-team-option {
    padding:6px 10px;font-family:var(--font-mono);font-size:9px;
    color:var(--text-muted);cursor:pointer;
  }
  .profile-team-option:hover { background:var(--bg-hover);color:var(--text-primary); }
  .profile-team-option.active { color:var(--accent); }
  .profile-new-btn {
    margin:10px 14px;padding:6px 0;text-align:center;
    font-family:var(--font-mono);font-size:10px;color:var(--accent);
    border:1px dashed var(--accent-border);cursor:pointer;
    transition:all 0.15s;background:transparent;
  }
  .profile-new-btn:hover { background:var(--accent-dim);border-color:var(--accent); }
  .profile-list { flex:1;overflow-y:auto; }
  .profile-card {
    display:flex;align-items:center;gap:8px;
    padding:8px 14px;cursor:pointer;
    border-left:2px solid transparent;transition:all 0.15s;
  }
  .profile-card:hover { background:rgba(0,212,255,0.06); }
  .profile-card.active {
    background:rgba(0,212,255,0.1);border-left-color:var(--accent);
  }
  .profile-card.active .profile-card-name { color:var(--accent); }
  .profile-card-icon { width:36px;height:36px;image-rendering:pixelated;flex-shrink:0; }
  .profile-card-name {
    font-family:var(--font-mono);font-size:10px;font-weight:500;
    color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  }
  .profile-card-desc { font-size:9px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap; }

  /* Editor pane */
  .profile-editor { flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:0; }
  .profile-section {
    border-bottom:1px solid var(--border);padding-bottom:20px;margin-bottom:20px;
  }
  .profile-section:last-child { border-bottom:none; }
  .profile-section-header {
    font-family:var(--font-mono);font-size:9px;letter-spacing:0.15em;
    text-transform:uppercase;color:var(--text-muted);margin-bottom:12px;
    display:flex;align-items:center;gap:8px;
  }
  .profile-section-toggle {
    font-family:var(--font-mono);font-size:9px;color:var(--accent);
    cursor:pointer;margin-left:auto;user-select:none;
  }
  .profile-section-toggle:hover { text-decoration:underline; }
  .profile-collapsible { overflow:hidden;transition:max-height 0.2s ease-in-out; }
  .profile-collapsible.collapsed { max-height:0 !important; }

  /* Identity section */
  .profile-identity-row { display:flex;gap:16px;align-items:flex-start; }
  .profile-icon-large {
    width:72px;height:72px;image-rendering:pixelated;flex-shrink:0;
    border:2px solid var(--border-2);display:flex;align-items:center;
    justify-content:center;background:var(--bg-3);
  }
  .profile-icon-large svg { width:100%;height:100%; }
  .profile-identity-fields { flex:1;display:flex;flex-direction:column;gap:8px; }

  /* Icon picker */
  .profile-icon-grid {
    display:grid;grid-template-columns:repeat(7,1fr);gap:6px;margin-top:10px;
  }
  .profile-icon-tile {
    width:56px;height:56px;display:flex;align-items:center;justify-content:center;
    background:var(--bg-3);border:2px solid var(--border);cursor:pointer;
    transition:all 0.15s;image-rendering:pixelated;
  }
  .profile-icon-tile:hover { border-color:var(--accent-border);background:var(--bg-4); }
  .profile-icon-tile.selected {
    border-color:var(--accent);box-shadow:0 0 8px rgba(0,212,255,0.3);
    background:rgba(0,212,255,0.08);
  }
  .profile-icon-tile svg { width:40px;height:40px; }

  /* Inputs */
  .profile-input, .profile-select, .profile-textarea {
    background:var(--bg-3);border:1px solid var(--border-2);
    color:var(--text-primary);font-family:var(--font-mono);
    font-size:11px;padding:7px 9px;outline:none;width:100%;
    transition:border-color 0.15s;
  }
  .profile-input:focus,.profile-select:focus,.profile-textarea:focus { border-color:var(--accent); }
  .profile-textarea { resize:vertical;min-height:60px; }
  .profile-select {
    appearance:none;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%2300d4ff' opacity='.5'/%3E%3C/svg%3E");
    background-repeat:no-repeat;background-position:right 8px center;padding-right:24px;
  }
  .profile-label {
    font-family:var(--font-mono);font-size:9px;color:var(--text-muted);
    text-transform:uppercase;letter-spacing:0.05em;
  }
  .profile-char-counter {
    font-family:var(--font-mono);font-size:9px;color:var(--text-muted);text-align:right;
  }
  .profile-token-counter {
    font-family:var(--font-mono);font-size:9px;color:var(--text-muted);
    text-align:right;margin-top:4px;
  }

  /* Task rows */
  .profile-task-row {
    display:flex;gap:8px;align-items:flex-start;padding:10px 12px;
    background:var(--bg-3);border:1px solid var(--border);margin-bottom:6px;
    transition:all 0.15s;
  }
  .profile-task-row:hover { border-color:var(--border-2); }
  .profile-task-fields { flex:1;display:flex;flex-direction:column;gap:6px; }
  .profile-task-meta { display:flex;gap:8px;align-items:center; }

  /* Priority segmented control */
  .profile-priority-seg { display:flex;gap:0; }
  .profile-priority-btn {
    font-family:var(--font-mono);font-size:8px;padding:3px 8px;
    border:1px solid var(--border-2);background:transparent;
    color:var(--text-muted);cursor:pointer;transition:all 0.15s;
    text-transform:uppercase;letter-spacing:0.05em;
  }
  .profile-priority-btn:first-child { border-right:none; }
  .profile-priority-btn:last-child { border-left:none; }
  .profile-priority-btn:not(:first-child):not(:last-child) { border-left:none;border-right:none; }
  .profile-priority-btn.active-low { background:rgba(34,197,94,0.15);color:var(--green);border-color:rgba(34,197,94,0.3); }
  .profile-priority-btn.active-medium { background:var(--accent-dim);color:var(--accent);border-color:var(--accent-border); }
  .profile-priority-btn.active-high { background:var(--amber-dim);color:var(--amber);border-color:var(--amber-border); }
  .profile-priority-btn.active-critical { background:var(--red-dim);color:var(--red);border-color:var(--red-border); }

  /* Task reorder + delete buttons */
  .profile-task-actions { display:flex;flex-direction:column;gap:2px;align-items:center; }
  .profile-task-action-btn {
    width:22px;height:18px;display:flex;align-items:center;justify-content:center;
    background:transparent;border:1px solid var(--border);color:var(--text-muted);
    cursor:pointer;font-size:10px;transition:all 0.15s;
  }
  .profile-task-action-btn:hover { border-color:var(--accent);color:var(--accent); }
  .profile-task-action-btn.delete:hover { border-color:var(--red);color:var(--red); }

  /* MCP / Skills chips */
  .profile-chip {
    display:inline-flex;align-items:center;gap:4px;
    font-family:var(--font-mono);font-size:9px;padding:3px 8px;
    background:var(--accent-dim);color:var(--accent);
    border:1px solid var(--accent-border);
  }
  .profile-chip .remove {
    cursor:pointer;opacity:0.6;font-size:11px;
  }
  .profile-chip .remove:hover { opacity:1;color:var(--red); }

  /* MCP / Skill list items */
  .profile-mcp-item, .profile-skill-item {
    display:flex;align-items:center;gap:10px;padding:8px 10px;
    border-bottom:1px solid rgba(255,255,255,0.04);
  }
  .profile-mcp-item:last-child, .profile-skill-item:last-child { border-bottom:none; }
  .profile-mcp-name, .profile-skill-name {
    font-family:var(--font-mono);font-size:10px;color:var(--text-primary);flex:1;
  }
  .profile-mcp-desc, .profile-skill-desc { font-size:9px;color:var(--text-muted);flex:2; }
  .profile-toggle {
    width:32px;height:18px;border-radius:9px;background:var(--bg-4);
    border:1px solid var(--border-2);cursor:pointer;position:relative;
    transition:all 0.15s;flex-shrink:0;
  }
  .profile-toggle::after {
    content:'';position:absolute;top:2px;left:2px;width:12px;height:12px;
    border-radius:50%;background:var(--text-muted);transition:all 0.15s;
  }
  .profile-toggle.on { background:rgba(0,212,255,0.2);border-color:var(--accent); }
  .profile-toggle.on::after { transform:translateX(14px);background:var(--accent); }

  /* Inline add form */
  .profile-add-form {
    padding:10px 12px;background:var(--bg-3);border:1px solid var(--border);
    margin-top:8px;display:none;flex-direction:column;gap:8px;
  }
  .profile-add-form.open { display:flex; }
  .profile-add-form-row { display:flex;gap:8px; }

  /* Status badges */
  .profile-badge {
    font-family:var(--font-mono);font-size:8px;padding:2px 5px;text-transform:uppercase;
  }
  .profile-badge.active { background:rgba(34,197,94,0.1);color:var(--green);border:1px solid rgba(34,197,94,0.3); }
  .profile-badge.inactive { background:var(--bg-4);color:var(--text-muted);border:1px solid var(--border); }

  /* Save bar */
  .profile-save-bar {
    display:flex;align-items:center;gap:8px;padding:10px 20px;
    background:rgba(10,10,10,0.9);backdrop-filter:blur(8px);
    border-top:1px solid var(--border);flex-shrink:0;
  }
  .profile-btn {
    font-family:var(--font-mono);font-size:10px;padding:7px 16px;
    cursor:pointer;transition:all 0.15s;text-transform:uppercase;
    letter-spacing:0.08em;
  }
  .profile-btn.primary {
    background:var(--accent);color:#000;border:1px solid var(--accent);font-weight:600;
  }
  .profile-btn.primary:hover { box-shadow:0 0 12px rgba(0,212,255,0.4); }
  .profile-btn.outlined {
    background:transparent;color:var(--text-muted);border:1px solid var(--border-2);
  }
  .profile-btn.outlined:hover { border-color:var(--accent);color:var(--text-primary); }
  .profile-btn.danger {
    background:transparent;color:var(--red);border:1px solid var(--red-border);
  }
  .profile-btn.danger:hover { background:var(--red-dim); }

  /* Empty state */
  .profile-empty-state {
    display:flex;flex-direction:column;align-items:center;
    justify-content:center;padding:60px 20px;text-align:center;gap:10px;flex:1;
  }
  .profile-empty-title { font-family:var(--font-mono);font-size:12px;color:var(--text-muted); }
  .profile-empty-sub { font-size:11px;color:rgba(255,255,255,0.25);max-width:260px;line-height:1.5; }

  /* Template dropdown */
  .profile-template-dropdown {
    position:relative;display:inline-block;
  }
  .profile-template-menu {
    position:absolute;top:100%;left:0;z-index:10;min-width:160px;
    background:var(--bg-3);border:1px solid var(--border-2);display:none;
  }
  .profile-template-menu.open { display:block; }
  .profile-template-option {
    padding:6px 10px;font-family:var(--font-mono);font-size:9px;
    color:var(--text-muted);cursor:pointer;
  }
  .profile-template-option:hover { background:var(--bg-hover);color:var(--text-primary); }

  /* Search input */
  .profile-search {
    background:var(--bg-3);border:1px solid var(--border-2);
    color:var(--text-primary);font-family:var(--font-mono);
    font-size:10px;padding:5px 8px;outline:none;width:100%;
    transition:border-color 0.15s;margin-bottom:8px;
  }
  .profile-search:focus { border-color:var(--accent); }
```

- [ ] **Step 2: Commit**

```bash
git add desktop/pages/dashboard.html
git commit -m "feat: add agent profile CSS styles, replacing team panel styles"
```

---

## Task 4: Replace HTML panel markup

**Files:**
- Modify: `desktop/pages/dashboard.html:2647` (sub-tab label)
- Modify: `desktop/pages/dashboard.html:2783-2851` (panel HTML)

- [ ] **Step 1: Rename sub-tab button**

At line 2647, change:
```html
    <button class="agent-sub-tab" id="asub-team" onclick="switchAgentSubTab('team')">TEAM</button>
```
to:
```html
    <button class="agent-sub-tab" id="asub-team" onclick="switchAgentSubTab('team')">PROFILES</button>
```

- [ ] **Step 2: Replace agent-team-panel HTML**

Replace lines 2783-2851 (from `<!-- AGENT TEAM CONFIG PANEL -->` through `<!-- END AGENT TEAM CONFIG PANEL -->`) with:

```html
    <!-- AGENT PROFILE PANEL -->
    <div class="agent-team-panel" id="agent-team-panel" style="
      position:absolute; inset:0; display:none; flex-direction:column;
      background:var(--bg); z-index:50; overflow:hidden;
      border-top:2px solid rgba(0,212,255,0.3);
    ">
      <!-- Panel header -->
      <div style="
        display:flex; align-items:center; gap:10px;
        padding:0 16px; height:44px;
        background:var(--bg-2); border-bottom:1px solid var(--border);
        flex-shrink:0;
      ">
        <div style="
          width:7px; height:7px; border-radius:50%;
          background:var(--accent); box-shadow:0 0 6px var(--accent);
          animation:pulse 2.4s ease-in-out infinite;
        "></div>
        <span style="font-family:var(--font-mono);font-size:11px;font-weight:600;
          letter-spacing:0.12em;text-transform:uppercase;color:var(--accent);">
          Agent Profiles
        </span>
        <span style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);">
          // manage agent configurations
        </span>
      </div>

      <!-- Body: sidebar + editor -->
      <div style="display:flex;flex:1;overflow:hidden;">

        <!-- Profile sidebar -->
        <div class="profile-sidebar" id="profile-sidebar">
          <div class="profile-sidebar-header">
            <span class="profile-sidebar-title">AGENTS</span>
            <span class="profile-count-badge" id="profile-count">0</span>
            <div style="margin-left:auto;">
              <div class="profile-team-pill" id="profile-team-pill" onclick="profileToggleTeamDropdown()">
                <span id="profile-team-label">All Teams</span>
                <span style="font-size:7px;">&#9660;</span>
                <div class="profile-team-dropdown" id="profile-team-dropdown">
                  <div class="profile-team-option active" onclick="profileSelectTeam('all',event)">All Teams</div>
                  <div class="profile-team-option" onclick="profileSelectTeam('Default Team',event)">Default Team</div>
                  <div class="profile-team-option" onclick="profileSelectTeam('Research',event)">Research</div>
                  <div class="profile-team-option" onclick="profileSelectTeam('Automation',event)">Automation</div>
                  <div class="profile-team-option" onclick="profileSelectTeam('Security',event)">Security</div>
                </div>
              </div>
            </div>
          </div>
          <button class="profile-new-btn" onclick="profileNew()">+ NEW AGENT</button>
          <div class="profile-list" id="profile-list"></div>
        </div>

        <!-- Main editor area -->
        <div id="profile-main" style="flex:1;display:flex;flex-direction:column;overflow:hidden;"></div>
      </div>
    </div>
    <!-- END AGENT PROFILE PANEL -->
```

- [ ] **Step 3: Update switchAgentSubTab reference**

At line 7102, change:
```javascript
    if (typeof teamPanelInit === 'function') teamPanelInit();
```
to:
```javascript
    if (typeof profilePanelInit === 'function') profilePanelInit();
```

- [ ] **Step 4: Commit**

```bash
git add desktop/pages/dashboard.html
git commit -m "feat: replace team panel HTML with agent profile panel markup"
```

---

## Task 5: Build the Profile System IIFE

**Files:**
- Modify: `desktop/pages/dashboard.html:10997-11753` (replace entire team config IIFE)

This is the largest task. Replace lines 10997-11753 (from `// AGENT TEAM CONFIG PANEL` section comment through `})(); // end AGENT TEAM CONFIG PANEL IIFE`) with the new profile system IIFE.

- [ ] **Step 1: Replace the IIFE**

Delete lines 10996-11753 (the section comment + entire IIFE) and insert:

```javascript
// ═══════════════════════════════════════════════════════════════
// AGENT PROFILE SYSTEM
// ═══════════════════════════════════════════════════════════════
(function() {

const TEAMS = ['Default Team', 'Research', 'Automation', 'Security'];
const PROMPT_TEMPLATES = {
  analyst:    'You are {NAME}, an AI analyst within AetherCloud.\n\nYour role is to interpret data, identify patterns, and produce structured analytical output.\n\nBehavior:\n- Always cite sources and evidence\n- Use tables and structured formats when presenting findings\n- Flag confidence levels for each conclusion\n- Ask clarifying questions before making assumptions',
  executor:   'You are {NAME}, an AI executor within AetherCloud.\n\nYour role is to carry out tasks efficiently and report results.\n\nBehavior:\n- Execute tasks in order of priority\n- Report completion status after each step\n- Escalate blockers immediately\n- Minimize unnecessary communication — focus on action',
  sentinel:   'You are {NAME}, a security sentinel within AetherCloud.\n\nYour role is to monitor, detect, and alert on security events.\n\nBehavior:\n- Continuously scan for anomalies and threats\n- Classify severity: INFO / WARN / CRITICAL\n- Never take destructive action without human approval\n- Log all observations with timestamps',
  researcher: 'You are {NAME}, an AI researcher within AetherCloud.\n\nYour role is to investigate topics, synthesize information, and present findings.\n\nBehavior:\n- Explore multiple angles before drawing conclusions\n- Distinguish between facts, inferences, and speculation\n- Provide sources and references when available\n- Summarize key findings at the end of each investigation',
};

const MCP_REGISTRY = [
  { id:'github',            name:'GitHub',           desc:'Repos, issues, PRs, CI/CD',    transport:'http' },
  { id:'slack',             name:'Slack',            desc:'Messages, channels, search',    transport:'http' },
  { id:'notion',            name:'Notion',           desc:'Pages, databases, knowledge',   transport:'http' },
  { id:'google_drive',      name:'Google Drive',     desc:'Docs, Sheets, file search',     transport:'http' },
  { id:'stripe',            name:'Stripe',           desc:'Payments, subscriptions',       transport:'http' },
  { id:'figma',             name:'Figma',            desc:'Design files, components',      transport:'http' },
  { id:'fal_ai',            name:'fal.ai',           desc:'1000+ image/video models',      transport:'http' },
  { id:'excalidraw',        name:'Excalidraw',       desc:'Diagrams from language',        transport:'stdio' },
  { id:'context7',          name:'Context7',         desc:'Live docs in prompt',           transport:'stdio' },
  { id:'desktop_commander', name:'Desktop Commander', desc:'Terminal, file ops',            transport:'stdio' },
  { id:'postgres',          name:'PostgreSQL',       desc:'Natural language SQL',          transport:'stdio' },
  { id:'supabase',          name:'Supabase',         desc:'Full backend access',           transport:'http' },
  { id:'playwright',        name:'Playwright',       desc:'Browser automation',            transport:'stdio' },
  { id:'firecrawl',         name:'Firecrawl',        desc:'Scrape + research agent',       transport:'http' },
];

let allIcons = [];
let allProfiles = [];
let currentProfileId = null;
let currentTeamFilter = 'all';
let mcpSearchQuery = '';

function esc(str) { return String(str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function genId() { return (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36); }

// ── Data loading ──────────────────────────────────────────────
async function loadIcons() {
  if (allIcons.length) return;
  try { allIcons = await window.aether.agentLoadIcons(); } catch(e) { console.error('[profiles] loadIcons', e); }
}

async function loadProfiles() {
  try { allProfiles = await window.aether.agentLoadProfiles(); } catch(e) { console.error('[profiles] loadProfiles', e); allProfiles = []; }
}

async function saveProfile(profile) {
  profile.updatedAt = new Date().toISOString();
  try {
    await window.aether.agentSaveProfile(profile);
    const idx = allProfiles.findIndex(p => p.id === profile.id);
    if (idx >= 0) allProfiles[idx] = profile; else allProfiles.push(profile);
    renderSidebar();
    if (typeof showToast === 'function') showToast('Agent saved', 'info');
  } catch(e) {
    if (typeof showToast === 'function') showToast('Save failed: ' + e.message, 'error');
  }
}

async function deleteProfile(id) {
  try {
    await window.aether.agentDeleteProfile(id);
    allProfiles = allProfiles.filter(p => p.id !== id);
    if (currentProfileId === id) { currentProfileId = null; showEmptyState(); }
    renderSidebar();
    if (typeof showToast === 'function') showToast('Agent deleted', 'info');
  } catch(e) {
    if (typeof showToast === 'function') showToast('Delete failed: ' + e.message, 'error');
  }
}

// ── Sidebar ───────────────────────────────────────────────────
function renderSidebar() {
  const list = document.getElementById('profile-list');
  const badge = document.getElementById('profile-count');
  if (!list) return;
  const filtered = currentTeamFilter === 'all' ? allProfiles : allProfiles.filter(p => p.team === currentTeamFilter);
  if (badge) badge.textContent = filtered.length;

  if (!filtered.length) {
    list.innerHTML = '<div style="padding:8px 14px;font-family:var(--font-mono);font-size:10px;color:var(--text-muted);font-style:italic;">No agents yet</div>';
    return;
  }
  list.innerHTML = filtered.map(function(p) {
    const icon = allIcons.find(i => i.name === p.icon);
    const thumb = icon ? '<div class="profile-card-icon">' + icon.svgContent + '</div>' : '<div class="profile-card-icon" style="background:var(--bg-4);"></div>';
    return '<div class="profile-card ' + (p.id === currentProfileId ? 'active' : '') + '" onclick="profileEdit(\'' + p.id + '\')">' +
      thumb +
      '<div style="flex:1;min-width:0;">' +
        '<div class="profile-card-name">' + esc(p.name || 'Unnamed') + '</div>' +
        '<div class="profile-card-desc">' + esc(p.description || '') + '</div>' +
      '</div>' +
    '</div>';
  }).join('');
}

// ── Empty state ───────────────────────────────────────────────
function showEmptyState() {
  const main = document.getElementById('profile-main');
  if (!main) return;
  // Build a small icon preview grid for the empty state
  const iconPreview = allIcons.slice(0, 8).map(function(ic) {
    return '<div style="width:40px;height:40px;image-rendering:pixelated;opacity:0.3;">' + ic.svgContent + '</div>';
  }).join('');
  main.innerHTML = '<div class="profile-empty-state">' +
    '<div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:center;margin-bottom:8px;">' + iconPreview + '</div>' +
    '<div class="profile-empty-title">Create your first agent</div>' +
    '<div class="profile-empty-sub">Configure an AI agent with a custom icon, system prompt, tasks, and MCP tools.</div>' +
    '<button class="profile-btn primary" onclick="profileNew()" style="margin-top:12px;">+ NEW AGENT</button>' +
  '</div>';
}

// ── Editor rendering ──────────────────────────────────────────
function renderEditor(profile) {
  const main = document.getElementById('profile-main');
  if (!main) return;

  const selectedIcon = allIcons.find(i => i.name === profile.icon);
  const largeIcon = selectedIcon ? selectedIcon.svgContent : '';

  // Icon picker grid
  const iconGrid = allIcons.map(function(ic) {
    return '<div class="profile-icon-tile ' + (ic.name === profile.icon ? 'selected' : '') + '" data-icon="' + esc(ic.name) + '" onclick="profileSelectIcon(\'' + esc(ic.name) + '\')">' + ic.svgContent + '</div>';
  }).join('');

  // Tasks HTML
  const tasksHtml = (profile.tasks || []).map(function(t, i) {
    return buildTaskRow(t, i, profile.tasks.length);
  }).join('');

  // MCP chips
  const mcpChips = (profile.mcpAgents || []).map(function(id) {
    const mcp = MCP_REGISTRY.find(m => m.id === id);
    return '<span class="profile-chip">' + esc(mcp ? mcp.name : id) +
      ' <span class="remove" onclick="profileRemoveMcp(\'' + esc(id) + '\')">&times;</span></span>';
  }).join('');

  // MCP list
  const mcpList = MCP_REGISTRY.map(function(m) {
    const isActive = (profile.mcpAgents || []).includes(m.id);
    return '<div class="profile-mcp-item">' +
      '<span class="profile-mcp-name">' + esc(m.name) + '</span>' +
      '<span class="profile-mcp-desc">' + esc(m.desc) + '</span>' +
      '<span class="profile-badge ' + (isActive ? 'active' : 'inactive') + '">' + (isActive ? 'ACTIVE' : 'OFF') + '</span>' +
      '<div class="profile-toggle ' + (isActive ? 'on' : '') + '" onclick="profileToggleMcp(\'' + esc(m.id) + '\')"></div>' +
    '</div>';
  }).join('');

  // Skills chips
  const skillChips = (profile.skills || []).map(function(s) {
    return '<span class="profile-chip">' + esc(s) +
      ' <span class="remove" onclick="profileRemoveSkill(\'' + esc(s) + '\')">&times;</span></span>';
  }).join('');

  main.innerHTML =
    '<div class="profile-editor" id="profile-editor">' +

    // ── IDENTITY SECTION ──
    '<div class="profile-section">' +
      '<div class="profile-section-header">IDENTITY</div>' +
      '<div class="profile-identity-row">' +
        '<div class="profile-icon-large" id="profile-icon-preview">' + largeIcon + '</div>' +
        '<div class="profile-identity-fields">' +
          '<div><label class="profile-label">AGENT NAME</label>' +
            '<input class="profile-input" id="profile-name" type="text" maxlength="32" placeholder="ENTER DESIGNATION..." value="' + esc(profile.name) + '" oninput="profileUpdateCharCount()">' +
            '<div class="profile-char-counter" id="profile-name-count">' + (profile.name||'').length + '/32</div>' +
          '</div>' +
          '<div><label class="profile-label">TEAM</label>' +
            '<select class="profile-select" id="profile-team-select">' +
              TEAMS.map(t => '<option value="' + esc(t) + '"' + (t === profile.team ? ' selected' : '') + '>' + esc(t) + '</option>').join('') +
            '</select>' +
          '</div>' +
          '<div><label class="profile-label">DESCRIPTION</label>' +
            '<textarea class="profile-textarea" id="profile-desc" rows="3" placeholder="Describe this agent\'s role and purpose...">' + esc(profile.description) + '</textarea>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="profile-section-header" style="margin-top:14px;">CHOOSE ICON</div>' +
      '<div class="profile-icon-grid" id="profile-icon-grid">' + iconGrid + '</div>' +
    '</div>' +

    // ── SYSTEM PROMPT SECTION ──
    '<div class="profile-section">' +
      '<div class="profile-section-header">SYSTEM PROMPT' +
        '<span class="profile-section-toggle" id="prompt-toggle" onclick="profileToggleSection(\'prompt\')">EXPAND</span>' +
      '</div>' +
      '<div class="profile-collapsible collapsed" id="prompt-body" style="max-height:400px;">' +
        '<div style="display:flex;gap:8px;margin-bottom:8px;">' +
          '<div class="profile-template-dropdown">' +
            '<button class="profile-btn outlined" onclick="profileToggleTemplateMenu()" style="font-size:9px;padding:4px 10px;">Load Template &#9660;</button>' +
            '<div class="profile-template-menu" id="profile-template-menu">' +
              '<div class="profile-template-option" onclick="profileLoadTemplate(\'analyst\')">Analyst</div>' +
              '<div class="profile-template-option" onclick="profileLoadTemplate(\'executor\')">Executor</div>' +
              '<div class="profile-template-option" onclick="profileLoadTemplate(\'sentinel\')">Sentinel</div>' +
              '<div class="profile-template-option" onclick="profileLoadTemplate(\'researcher\')">Researcher</div>' +
              '<div class="profile-template-option" onclick="profileLoadTemplate(\'custom\')">Custom (blank)</div>' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<textarea class="profile-textarea" id="profile-prompt" style="min-height:200px;" placeholder="You are [AGENT NAME], an AI agent operating within AetherCloud...\nDefine behavior, tone, restrictions, and context here." oninput="profileUpdateTokenCount()">' + esc(profile.systemPrompt) + '</textarea>' +
        '<div class="profile-token-counter" id="profile-token-count">' + (profile.systemPrompt||'').length + ' chars / ~' + Math.ceil((profile.systemPrompt||'').length / 4) + ' tokens</div>' +
      '</div>' +
    '</div>' +

    // ── TASKS SECTION ──
    '<div class="profile-section">' +
      '<div class="profile-section-header">TASKS <span style="font-size:9px;color:var(--text-muted);">(' + (profile.tasks||[]).length + '/10)</span>' +
        '<button class="profile-btn outlined" onclick="profileAddTask()" style="font-size:9px;padding:3px 10px;margin-left:auto;"' + ((profile.tasks||[]).length >= 10 ? ' disabled' : '') + '>+ ADD TASK</button>' +
      '</div>' +
      '<div id="profile-tasks">' + (tasksHtml || '<div style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);font-style:italic;padding:8px 0;">No tasks configured</div>') + '</div>' +
    '</div>' +

    // ── MCP AGENTS SECTION ──
    '<div class="profile-section">' +
      '<div class="profile-section-header">MCP AGENTS' +
        '<span class="profile-section-toggle" id="mcp-toggle" onclick="profileToggleSection(\'mcp\')">EXPAND</span>' +
      '</div>' +
      '<div class="profile-collapsible collapsed" id="mcp-body" style="max-height:600px;">' +
        '<div style="font-size:10px;color:var(--text-muted);margin-bottom:10px;">Connect model context protocol tools to this agent.</div>' +
        (mcpChips ? '<div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:10px;">' + mcpChips + '</div>' : '') +
        '<input class="profile-search" id="mcp-search" type="text" placeholder="Search MCPs..." oninput="profileFilterMcps()">' +
        '<div id="profile-mcp-list">' + mcpList + '</div>' +
      '</div>' +
    '</div>' +

    // ── SKILLS SECTION ──
    '<div class="profile-section">' +
      '<div class="profile-section-header">SKILLS' +
        '<span class="profile-section-toggle" id="skills-toggle" onclick="profileToggleSection(\'skills\')">EXPAND</span>' +
      '</div>' +
      '<div class="profile-collapsible collapsed" id="skills-body" style="max-height:400px;">' +
        '<div style="font-size:10px;color:var(--text-muted);margin-bottom:10px;">Attach skill modules to this agent.</div>' +
        (skillChips ? '<div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:10px;">' + skillChips + '</div>' : '') +
        '<div id="profile-skill-list"><div style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);font-style:italic;">No skills available. Add skills to agent/skills/ directory.</div></div>' +
        '<button class="profile-btn outlined" onclick="profileToggleAddSkill()" style="font-size:9px;padding:4px 10px;margin-top:8px;">+ ADD SKILL</button>' +
        '<div class="profile-add-form" id="profile-add-skill-form">' +
          '<div class="profile-add-form-row">' +
            '<input class="profile-input" id="new-skill-name" placeholder="Skill name" style="flex:1;">' +
            '<input class="profile-input" id="new-skill-desc" placeholder="Description" style="flex:2;">' +
          '</div>' +
          '<div style="display:flex;gap:8px;">' +
            '<button class="profile-btn primary" onclick="profileSaveNewSkill()" style="font-size:9px;padding:4px 12px;">Save</button>' +
            '<button class="profile-btn outlined" onclick="profileToggleAddSkill()" style="font-size:9px;padding:4px 12px;">Cancel</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>' +

    '</div>' + // end profile-editor

    // ── SAVE BAR ──
    '<div class="profile-save-bar">' +
      '<button class="profile-btn primary" onclick="profileSave()">SAVE AGENT</button>' +
      '<button class="profile-btn outlined" onclick="profileExport()">EXPORT CONFIG</button>' +
      '<button class="profile-btn outlined" onclick="profileDuplicate()">DUPLICATE</button>' +
      '<div style="flex:1;"></div>' +
      '<button class="profile-btn danger" onclick="profileDelete()">DELETE AGENT</button>' +
    '</div>';
}

// ── Task row builder ──────────────────────────────────────────
function buildTaskRow(task, index, total) {
  const priorities = ['LOW','MEDIUM','HIGH','CRITICAL'];
  const priorityBtns = priorities.map(function(p) {
    const cls = task.priority === p ? 'active-' + p.toLowerCase() : '';
    return '<button class="profile-priority-btn ' + cls + '" onclick="profileSetTaskPriority(' + index + ',\'' + p + '\')">' + p + '</button>';
  }).join('');

  const triggers = ['Manual','Scheduled','Event','Chained'];
  const triggerOpts = triggers.map(function(t) {
    return '<option value="' + t + '"' + (task.trigger === t ? ' selected' : '') + '>' + t + '</option>';
  }).join('');

  return '<div class="profile-task-row" data-task-index="' + index + '">' +
    '<div class="profile-task-fields">' +
      '<input class="profile-input" placeholder="Task name" value="' + esc(task.name) + '" onchange="profileUpdateTask(' + index + ',\'name\',this.value)" style="font-weight:500;">' +
      '<textarea class="profile-textarea" rows="2" placeholder="Task description..." onchange="profileUpdateTask(' + index + ',\'description\',this.value)" style="min-height:40px;">' + esc(task.description) + '</textarea>' +
      '<div class="profile-task-meta">' +
        '<div class="profile-priority-seg">' + priorityBtns + '</div>' +
        '<select class="profile-select" onchange="profileUpdateTask(' + index + ',\'trigger\',this.value)" style="width:120px;padding:3px 24px 3px 8px;font-size:9px;">' + triggerOpts + '</select>' +
      '</div>' +
    '</div>' +
    '<div class="profile-task-actions">' +
      '<button class="profile-task-action-btn" onclick="profileMoveTask(' + index + ',-1)"' + (index === 0 ? ' disabled style="opacity:0.3"' : '') + '>&#9650;</button>' +
      '<button class="profile-task-action-btn" onclick="profileMoveTask(' + index + ',1)"' + (index === total - 1 ? ' disabled style="opacity:0.3"' : '') + '>&#9660;</button>' +
      '<button class="profile-task-action-btn delete" onclick="profileRemoveTask(' + index + ')">&#10005;</button>' +
    '</div>' +
  '</div>';
}

// ── Collect current form state into profile object ────────────
function collectProfile() {
  const p = allProfiles.find(pr => pr.id === currentProfileId);
  if (!p) return null;
  p.name = (document.getElementById('profile-name')?.value || '').trim();
  p.description = (document.getElementById('profile-desc')?.value || '').trim();
  p.systemPrompt = (document.getElementById('profile-prompt')?.value || '');
  const teamSel = document.getElementById('profile-team-select');
  if (teamSel) p.team = teamSel.value;
  // Tasks, mcpAgents, skills, icon are updated in real-time via their own handlers
  return p;
}

// ── Window-level handlers (called from onclick) ───────────────

window.profilePanelInit = async function() {
  await loadIcons();
  await loadProfiles();
  renderSidebar();
  if (currentProfileId) {
    const p = allProfiles.find(pr => pr.id === currentProfileId);
    if (p) renderEditor(p); else showEmptyState();
  } else {
    showEmptyState();
  }
};

window.profileNew = function() {
  const profile = {
    id: genId(),
    name: '',
    icon: allIcons.length ? allIcons[0].name : '',
    description: '',
    team: 'Default Team',
    systemPrompt: '',
    tasks: [],
    mcpAgents: [],
    skills: [],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  allProfiles.push(profile);
  currentProfileId = profile.id;
  renderSidebar();
  renderEditor(profile);
};

window.profileEdit = function(id) {
  const p = allProfiles.find(pr => pr.id === id);
  if (!p) return;
  // Collect any unsaved state from current editor before switching
  if (currentProfileId && currentProfileId !== id) collectProfile();
  currentProfileId = id;
  renderSidebar();
  renderEditor(p);
};

window.profileSelectIcon = function(iconName) {
  const p = allProfiles.find(pr => pr.id === currentProfileId);
  if (!p) return;
  p.icon = iconName;
  // Update large preview
  const preview = document.getElementById('profile-icon-preview');
  const icon = allIcons.find(i => i.name === iconName);
  if (preview && icon) preview.innerHTML = icon.svgContent;
  // Update grid selection
  document.querySelectorAll('.profile-icon-tile').forEach(function(tile) {
    tile.classList.toggle('selected', tile.dataset.icon === iconName);
  });
  // Update sidebar card
  renderSidebar();
};

window.profileUpdateCharCount = function() {
  const input = document.getElementById('profile-name');
  const counter = document.getElementById('profile-name-count');
  if (input && counter) counter.textContent = input.value.length + '/32';
};

window.profileUpdateTokenCount = function() {
  const textarea = document.getElementById('profile-prompt');
  const counter = document.getElementById('profile-token-count');
  if (textarea && counter) {
    const len = textarea.value.length;
    counter.textContent = len + ' chars / ~' + Math.ceil(len / 4) + ' tokens';
  }
};

window.profileToggleSection = function(section) {
  const body = document.getElementById(section + '-body');
  const toggle = document.getElementById(section + '-toggle');
  if (!body || !toggle) return;
  const collapsed = body.classList.toggle('collapsed');
  toggle.textContent = collapsed ? 'EXPAND' : 'COLLAPSE';
};

window.profileToggleTemplateMenu = function() {
  const menu = document.getElementById('profile-template-menu');
  if (menu) menu.classList.toggle('open');
};

window.profileLoadTemplate = function(key) {
  const textarea = document.getElementById('profile-prompt');
  const nameInput = document.getElementById('profile-name');
  const menu = document.getElementById('profile-template-menu');
  if (menu) menu.classList.remove('open');
  if (!textarea) return;
  if (key === 'custom') { textarea.value = ''; }
  else {
    const name = nameInput ? nameInput.value.trim() || '[AGENT NAME]' : '[AGENT NAME]';
    textarea.value = (PROMPT_TEMPLATES[key] || '').replace(/\{NAME\}/g, name);
  }
  window.profileUpdateTokenCount();
};

// ── Task handlers ─────────────────────────────────────────────

window.profileAddTask = function() {
  const p = allProfiles.find(pr => pr.id === currentProfileId);
  if (!p || (p.tasks||[]).length >= 10) return;
  if (!p.tasks) p.tasks = [];
  p.tasks.push({ id: genId(), name: '', description: '', priority: 'MEDIUM', trigger: 'Manual' });
  collectProfile();
  renderEditor(p);
};

window.profileUpdateTask = function(index, field, value) {
  const p = allProfiles.find(pr => pr.id === currentProfileId);
  if (!p || !p.tasks || !p.tasks[index]) return;
  p.tasks[index][field] = value;
};

window.profileSetTaskPriority = function(index, priority) {
  const p = allProfiles.find(pr => pr.id === currentProfileId);
  if (!p || !p.tasks || !p.tasks[index]) return;
  p.tasks[index].priority = priority;
  collectProfile();
  renderEditor(p);
};

window.profileMoveTask = function(index, dir) {
  const p = allProfiles.find(pr => pr.id === currentProfileId);
  if (!p || !p.tasks) return;
  const newIdx = index + dir;
  if (newIdx < 0 || newIdx >= p.tasks.length) return;
  const tmp = p.tasks[index];
  p.tasks[index] = p.tasks[newIdx];
  p.tasks[newIdx] = tmp;
  collectProfile();
  renderEditor(p);
};

window.profileRemoveTask = function(index) {
  const p = allProfiles.find(pr => pr.id === currentProfileId);
  if (!p || !p.tasks) return;
  p.tasks.splice(index, 1);
  collectProfile();
  renderEditor(p);
};

// ── MCP handlers ──────────────────────────────────────────────

window.profileToggleMcp = function(mcpId) {
  const p = allProfiles.find(pr => pr.id === currentProfileId);
  if (!p) return;
  if (!p.mcpAgents) p.mcpAgents = [];
  const idx = p.mcpAgents.indexOf(mcpId);
  if (idx >= 0) p.mcpAgents.splice(idx, 1); else p.mcpAgents.push(mcpId);
  collectProfile();
  renderEditor(p);
};

window.profileRemoveMcp = function(mcpId) {
  const p = allProfiles.find(pr => pr.id === currentProfileId);
  if (!p || !p.mcpAgents) return;
  p.mcpAgents = p.mcpAgents.filter(id => id !== mcpId);
  collectProfile();
  renderEditor(p);
};

window.profileFilterMcps = function() {
  const search = (document.getElementById('mcp-search')?.value || '').toLowerCase();
  const items = document.querySelectorAll('.profile-mcp-item');
  items.forEach(function(item) {
    const name = item.querySelector('.profile-mcp-name')?.textContent?.toLowerCase() || '';
    const desc = item.querySelector('.profile-mcp-desc')?.textContent?.toLowerCase() || '';
    item.style.display = (name.includes(search) || desc.includes(search)) ? 'flex' : 'none';
  });
};

// ── Skill handlers ────────────────────────────────────────────

window.profileRemoveSkill = function(skillName) {
  const p = allProfiles.find(pr => pr.id === currentProfileId);
  if (!p || !p.skills) return;
  p.skills = p.skills.filter(s => s !== skillName);
  collectProfile();
  renderEditor(p);
};

window.profileToggleAddSkill = function() {
  const form = document.getElementById('profile-add-skill-form');
  if (form) form.classList.toggle('open');
};

window.profileSaveNewSkill = function() {
  const name = (document.getElementById('new-skill-name')?.value || '').trim();
  if (!name) return;
  const p = allProfiles.find(pr => pr.id === currentProfileId);
  if (!p) return;
  if (!p.skills) p.skills = [];
  if (!p.skills.includes(name)) p.skills.push(name);
  collectProfile();
  renderEditor(p);
};

// ── Save / Export / Duplicate / Delete ─────────────────────────

window.profileSave = function() {
  const p = collectProfile();
  if (!p) return;
  if (!p.name) {
    if (typeof showToast === 'function') showToast('Agent name is required', 'error');
    return;
  }
  saveProfile(p);
};

window.profileExport = function() {
  const p = collectProfile();
  if (!p) return;
  const blob = new Blob([JSON.stringify(p, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = (p.name || 'agent').toLowerCase().replace(/\s+/g, '_') + '_profile.json';
  a.click();
  URL.revokeObjectURL(url);
};

window.profileDuplicate = function() {
  const p = collectProfile();
  if (!p) return;
  const copy = JSON.parse(JSON.stringify(p));
  copy.id = genId();
  copy.name = (copy.name || 'Agent') + ' Copy';
  copy.createdAt = new Date().toISOString();
  copy.updatedAt = new Date().toISOString();
  allProfiles.push(copy);
  currentProfileId = copy.id;
  renderSidebar();
  renderEditor(copy);
  if (typeof showToast === 'function') showToast('Agent duplicated', 'info');
};

window.profileDelete = function() {
  if (!currentProfileId) return;
  const p = allProfiles.find(pr => pr.id === currentProfileId);
  const name = p ? p.name || 'this agent' : 'this agent';
  if (!confirm('Delete ' + name + '? This cannot be undone.')) return;
  deleteProfile(currentProfileId);
};

// ── Team filter ───────────────────────────────────────────────

window.profileToggleTeamDropdown = function() {
  const dd = document.getElementById('profile-team-dropdown');
  if (dd) dd.classList.toggle('open');
};

window.profileSelectTeam = function(team, event) {
  if (event) event.stopPropagation();
  currentTeamFilter = team;
  const label = document.getElementById('profile-team-label');
  if (label) label.textContent = team === 'all' ? 'All Teams' : team;
  // Update active state
  document.querySelectorAll('.profile-team-option').forEach(function(opt) {
    opt.classList.toggle('active', opt.textContent.trim() === (team === 'all' ? 'All Teams' : team));
  });
  const dd = document.getElementById('profile-team-dropdown');
  if (dd) dd.classList.remove('open');
  renderSidebar();
};

})(); // end AGENT PROFILE SYSTEM IIFE
```

- [ ] **Step 2: Verify the IIFE closes correctly**

Search for the closing pattern to confirm the old IIFE was fully replaced:

```bash
grep -n "AGENT PROFILE SYSTEM" desktop/pages/dashboard.html
```

Expected: Two matches — the opening section comment and the closing comment.

- [ ] **Step 3: Commit**

```bash
git add desktop/pages/dashboard.html
git commit -m "feat: implement agent profile system IIFE with full editor"
```

---

## Task 6: Manual integration test

- [ ] **Step 1: Launch the app and test**

```bash
cd desktop && npm start
```

Test the following flow:
1. Click AGENTS in the top nav
2. Click PROFILES sub-tab (was "TEAM")
3. Verify empty state with icon preview shows
4. Click "+ NEW AGENT"
5. Verify icon picker grid loads all 20 icons
6. Select an icon — verify large preview updates
7. Enter name "WRAITH", select team "Security", enter description
8. Expand System Prompt — load Sentinel template — verify token counter
9. Add a task — set priority HIGH, trigger Manual
10. Expand MCP section — toggle GitHub and Slack ON — verify chips appear
11. Click SAVE AGENT — verify toast and sidebar updates
12. Click DUPLICATE — verify copy appears
13. Switch between agents in sidebar — verify editor loads correct data
14. Click DELETE AGENT on the copy — confirm — verify removed
15. Switch to ORBIT tab and back to PROFILES — verify data persists
16. Close and reopen the app — navigate to PROFILES — verify saved agents load from disk

- [ ] **Step 2: Verify JSON on disk**

```bash
ls agent/profiles/
cat agent/profiles/*.json | head -30
```

Expected: One or more `.json` files with the correct schema.

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: integration test fixes for agent profile system"
```

---

## Summary

| Task | Description | Files | Commit |
|------|-------------|-------|--------|
| 1 | IPC handlers + directories | `main.js`, `agent/profiles/`, `agent/skills/` | `feat: add agent profile IPC handlers` |
| 2 | Preload bridge methods | `preload.js` | `feat: add agent profile bridge methods` |
| 3 | CSS styles | `dashboard.html` (CSS block) | `feat: add agent profile CSS styles` |
| 4 | HTML panel + sub-tab label + switchAgentSubTab | `dashboard.html` (HTML + JS ref) | `feat: replace team panel HTML` |
| 5 | Profile system IIFE (full logic) | `dashboard.html` (IIFE block) | `feat: implement agent profile system IIFE` |
| 6 | Manual integration test | All files | `fix: integration test fixes` (if needed) |
