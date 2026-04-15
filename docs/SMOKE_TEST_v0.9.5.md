# v0.9.5 Smoke Test — Manual Verification Plan

**Target build:** `desktop/release/AetherCloud-L-Setup-0.9.5.exe`
**Focus:** Project orchestrator wiring fix (primary). AetherBrowser integration (secondary). Regression-check everything else.
**Estimated time:** 10 minutes.

---

## Prep (30 seconds)

1. Install the new build. Let the installer run to completion.
2. Launch **AetherCloud-L 0.9.5** from the Start menu.
3. Open DevTools immediately: **Ctrl+Shift+I**. Pin the **Console** and **Network** tabs side-by-side — this is where you'll catch every wiring bug if one slipped through.

---

## Phase 1 — Boot & auth (1 min)

| # | Action | Pass criteria |
|---|---|---|
| 1 | Installer opens | No signing warnings you didn't expect; app window appears |
| 2 | Login with your credentials | Redirects to dashboard, no red errors in Console |
| 3 | In Console: `await window.aetherAPI.authGet()` | Returns object with non-empty `sessionToken` string |
| 4 | In Console: `sessionToken` | Returns the same non-empty string (hydrated from electron-store) |

If step 3 or 4 returns empty string → **stop**, authentication is broken.

---

## Phase 2 — Project orchestrator (the fix) — 5 min

This is the path that was 100% broken in v0.9.4. Every check below is a regression gate.

### 2a. Launch a project

1. In the main chat input, type a goal-shaped query of **6+ words** that matches one of these patterns: `build a...`, `create an...`, `design the...`, `develop a...`, `implement a...`. Example:

   > `build a simple todo list web app`

2. Press Enter.

**Expected (all must happen):**

- [ ] Toast: "Decomposing goal…"
- [ ] View switches to `agents` mode
- [ ] In **Network tab**, a request fires to `https://api.aethersystems.net/cloud/project/start` with status **200** (NOT to `file:///project/start`, and NOT 401/403/404).
- [ ] Response JSON has `project_id`, `task_count`, `tasks[]`, `message` keys.
- [ ] A chat bubble appears with text starting `[PROJECT STARTED — N tasks]`.
- [ ] A project board appears in the agents panel with one card per task, each showing role + title + agent name.

**If any fail:**
- 404 → backend not deployed with `/project/start` route. `curl https://api.aethersystems.net/cloud/routing-check` to verify.
- `file:///project/start` → fix didn't ship. Re-check installed version.
- 401 → token hydration failed. Re-check Phase 1 step 3.

### 2b. SSE stream

Still in **Network tab**, with the request filter set to `project/stream`:

- [ ] A pending EventSource to `https://api.aethersystems.net/cloud/project/stream/{project_id}?token=...` opens and stays open.
- [ ] The `Response` tab of the EventSource shows at least one event: `{"type":"connected","project_id":"..."}`.
- [ ] Within ~30 seconds, more events stream in. Task cards in the UI progress from `pending` → `running` → `done`/`failed`/`blocked`. Border color changes (orange → green/red/grey).
- [ ] QOPC score appears on done cards (`QOPC 85%` or similar).
- [ ] When all tasks finish, a final chat bubble appears: `✅ Project done: N/N tasks completed` or `⚠️ Project failed: X/N tasks completed`.
- [ ] The EventSource closes cleanly after `project_done`.

**If no events arrive for 60s:** check Console for `Project stream disconnected` toast — that's the `onerror` path firing. Likely means backend orchestrator crashed or ANTHROPIC_API_KEY is unset on VPS2.

### 2c. Project context fetch

1. In Console, paste (replace `PROJECT_ID` with the real one from 2a):

   ```js
   await loadProjectContext('PROJECT_ID')
   ```

2. Expected: returns an object (goal, decisions, api_contracts, files, etc.). **Not** `null`, **not** an error.

If it returns `null` — check Network tab for the request to `/project/context/{id}`, inspect the status.

---

## Phase 3 — Regression sweep (3 min)

These paths weren't touched, but verify they still work end-to-end.

| # | Feature | Test |
|---|---|---|
| 1 | **Chat (non-project)** | Type a short query like `what's in my vault?` — response streams back, no 401 |
| 2 | **Vault browse** | Click a folder in the vault sidebar — files list populates |
| 3 | **File analysis** | Right-click a file → Analyze — AI categorization appears |
| 4 | **Scheduled tasks** | Open the Scheduled Tasks panel — existing tasks render, you can create a new one |
| 5 | **Audit trail** | Open LOGS tab — events scroll in live |
| 6 | **Agent profiles** | Open Agent Studio — your saved agents load with icons and voices |
| 7 | **MCP status** | In Console: `await window.aetherAPI.getStatus()` — returns `{authenticated: true, ...}` |

Any red errors in the DevTools Console during any of these = regression. Screenshot the error and the failing step.

---

## Phase 4 — Final sanity (30 sec)

1. Close the app.
2. Re-launch. You should be auto-logged-in (session token persisted in encrypted electron-store).
3. Run **2a** one more time with a different goal to confirm the fix is stable across restarts.

---

## What "100% passing" looks like

- Phase 1: all 4 steps green
- Phase 2a: all 6 checkboxes green
- Phase 2b: all 5 checkboxes green
- Phase 2c: returns an object, not null
- Phase 3: all 7 items work with no Console errors
- Phase 4: auto-login works, second project launch succeeds

**If all the above pass → v0.9.5 is shippable.**

---

## Rollback

If Phase 2 fails, the fix didn't make it into the build:

1. Uninstall v0.9.5 (Windows Settings → Apps)
2. Reinstall the v0.9.4 build from the previous release
3. Report exactly which checkbox failed and paste the DevTools Console + Network screenshots into the issue
