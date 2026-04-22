# AetherCloud-L — Release Notes

*Aether Systems LLC · Patent Pending (Application #64/010,131)*

---

## v0.9.8 — UVT Stack + UVT Meter v3 + BYOK Removal (2026-04-21)

The release that pairs with backend Stages A-J. Desktop app no longer manages its own Anthropic key, ships the new UVT meter in the chatbar, and is forward-compatible with the metered-billing pipeline that's now live (and dormant) on VPS2.

### Removed — BYOK (Bring Your Own Key)
- **`desktop/key-manager.js` deleted entirely.** Previously, every install carried an AES-encrypted `electron-store` named `aethercloud-keys` that stored a per-user `ANTHROPIC_API_KEY` in `%APPDATA%/AetherCloud-L/`. It was wired but never used by any UI surface (no form ever asked for it) — pure attack surface for no benefit.
- Removed 4 IPC handlers (`keys:set`, `keys:has`, `keys:delete`, `keys:validate`) from `desktop/main.js`.
- Removed `keyManager.hydrate()` call from `app.whenReady()`.
- Removed `window.aether.keys.{set,has,delete,validate}` bridge from `desktop/preload.js`.
- Removed `key-manager.js` from `desktop/package.json` files manifest — it won't ship in any future binary.
- **Net:** -150 lines, smaller binary, single source of truth (Anthropic key lives only on VPS2 in `/etc/aethercloud/.env`).

### Added — UVT Meter v3 (chatbar droplet + 152px popover tile)
- **`desktop/pages/uvt-meter/{uvt-meter.css, uvt-meter.js, uvt-meter-tap.js}`** installed per spec — the v3 droplet trigger between Plan/Bypass toggles and the input, expanding into a 152px tile with tube fill, three mini bars (Monthly / Daily / Concurrent), and an action button (Upgrade tier OR Manage overage).
- Reads `/account/usage` every 30s, ingests `/agent/run` round-trips for the "last call" detail row.
- Status colors: green (healthy), amber (≥70%), red (≥90%).
- Storage keys: `uvtmeter.snapshot.v1`, `uvtmeter.lastcall.v1` (versioned, future-safe).

### Added — Stage J flag-aware mount
- **`desktop/pages/dashboard.html`**: added `<span id="uvt-host" class="uvt-host"></span>` between the chatbar toggles and the input field.
- New mount IIFE in the `<head>` that, on `DOMContentLoaded`, hits `/healthz/flags` BEFORE rendering the meter. When `AETHER_UVT_ENABLED=false` AND `AETHER_UVT_ROLLOUT_PCT=0` AND `override_count=0`, the meter does NOT mount — keeps the chatbar clean for users not yet in the rollout, prevents 404 spam in the console.
- Mount uses `window.aether.apiBase` (the VPS1 ghost proxy) and reads the session token via the `aetherAPI.authGet()` bridge.

### Verification
- `node --check desktop/main.js` ✅
- `node --check desktop/preload.js` ✅
- `JSON.parse(desktop/package.json)` ✅
- `grep -rn "keyManager\|key-manager.js\|aethercloud-keys\|aether.keys"` returns **zero matches** repo-wide.
- `grep -rn "api.anthropic.com" desktop/` returns **zero matches** (everything routes through the VPS now).

### Backend dependency (Stage A-J already deployed)
This v0.9.8 desktop binary is forward-compatible with the metered-billing pipeline. With `AETHER_UVT_ENABLED=false` on VPS2 (current production state), the desktop app's behavior is **identical to v0.9.7** from the user's perspective:
- Chat hits `/agent/chat` (legacy) and works normally.
- The UVT meter detects flag-off via `/healthz/flags` and stays hidden.

When the operator flips `AETHER_UVT_ENABLED=true` (or `AETHER_UVT_ROLLOUT_PCT>0`), the meter automatically appears for users in the rollout bucket. **Same binary, no re-install needed.**

### Files Modified / Removed
| File | Change |
|------|--------|
| `desktop/key-manager.js` | **Deleted** (-142 lines) |
| `desktop/main.js` | Removed `require('./key-manager')`, `keyManager.hydrate()`, 4 `keys:*` IPC handlers (-9 lines) |
| `desktop/preload.js` | Removed `keys:` bridge (-8 lines, +1 line comment update) |
| `desktop/package.json` | Removed `key-manager.js` from `files`; version bump 0.9.7 → 0.9.8 |
| `desktop/pages/dashboard.html` | Added meter link/script + flag-aware mount IIFE + `#uvt-host` span (+71 lines) |
| `desktop/pages/uvt-meter/` | **3 new files** (css, js, tap.js) — v3 spec install |
| `README.md` | architecture tree updated — `key-manager.js` line removed |

### Test counts
- Backend: **186 UVT-stack tests** added today (Stages A-J), plus existing suite (~640 tests, 2 pre-existing failures unrelated to this release).
- Desktop: no new automated tests — UI behavior verified by spec compliance + acceptance checklist.

### Known caveats
- **SmartScreen warning still expected.** Installer is not yet Authenticode-signed (Azure Trusted Signing setup is the next backlog item, ~$10/mo).
- **No DLQ replay.** If `rpc_record_usage` ever fails, events land in `/var/lib/aethercloud/usage_dlq.jsonl` on VPS2; manual replay until Stage K cron lands.
- **Stripe metered billing (Stage H) not yet wired.** Overage USD is stubbed to 0 in `/account/usage` — UI handles the 0 cleanly.
- **Stage B.5 deferred.** `agent/claude_agent.py` + `hardened_claude_agent.py` (file-agent SDK paths) still use the Anthropic SDK directly. Not in the UVT-metered hot path.

---

## v0.9.5 — AetherBrowser Integration + Project Orchestrator Wiring Fix (2026-04-15)

First shipped release after v0.9.4. Rolls two separate bodies of work into one version: the AetherBrowser / AetherForge infrastructure work (originally drafted as "v1.0.0" but never released) and the project orchestrator wiring fix.

### Fixed — Project Orchestrator Frontend↔Backend Wiring
- **Project orchestrator was fully broken on v0.9.4.** Every autonomous-goal chat query (`launchProject`) silently failed because four integration bugs in [desktop/pages/dashboard.html](desktop/pages/dashboard.html) prevented any request from reaching the backend.
  - `launchProject`, `connectProjectStream`, `loadProjectContext` used relative URLs (`/project/start`, `/project/stream/...`, `/project/context/...`). Pages are loaded via `file://`, so these resolved to `file:///project/...` and never reached VPS2.
  - Session tokens were read from `sessionStorage` / `localStorage` — keys that are **never populated anywhere** in the app. The real token lives in encrypted electron-store and is exposed via `window.aetherAPI.authGet()` / `getSessionToken()`.
  - `POST /project/answer` was being called for agent question prompts, but **no such endpoint existed** in [project_routes.py](project_routes.py) — and `project_orchestrator.py` never emitted `question` events to begin with, making the entire answer-UI path unreachable dead code.
- **Rewired all three hot-path calls** to use `authFetch(API_BASE + '/project/...')` with proper token resolution, and **removed the dead question-answer UI** (`renderOpenQuestion`, `answerProjectQuestion`, `case 'question'`) rather than stub a fake backend endpoint.

### Verification — Orchestrator Fix
- All 5 post-fix grep audits pass with zero matches (no relative `/project/` URLs, no `sessionStorage.session_token`, no `/project/answer`, no `renderOpenQuestion`/`answerProjectQuestion`, no `case 'question'` handlers).
- SSE event-shape contract re-validated: every field the frontend reads (`ev.task_id`, `ev.title`, `ev.qopc_score`, `ev.error`, `ev.status`, `ev.done`, `ev.total`) is emitted by [project_orchestrator.py](project_orchestrator.py).
- `/project/start` response-shape contract re-validated: `{project_id, task_count, tasks, message}` matches frontend reads.
- `node -c` clean on `main.js`, `preload.js`, and extracted `dashboard.html` inline JS.
- Backend pytest: **636 passed · 2 failed · 5 skipped** (the 2 failures are pre-existing stale tests in [tests/test_marketing_agent.py:572](tests/test_marketing_agent.py:572) and [tests/test_security_fixes.py:341](tests/test_security_fixes.py:341), unrelated to this fix).
- Electron IPC contract re-audited: all 47 channels in [desktop/preload.js](desktop/preload.js) match `ipcMain.handle` / `on` declarations in [desktop/main.js](desktop/main.js).

### Browser Automation (NEW)
- **AetherBrowser client** (`agent/aetherbrowser_client.py`) — async HTTP client for all AetherCloud-to-AetherBrowser communication with typed exceptions, session lifecycle management, and automatic cleanup in finally blocks
- **Browser tool injector** (`agent/browser_tool_injector.py`) — dynamically appends `browser_navigate`, `browser_interact`, `browser_snapshot`, `browser_end` tools to Claude's context when `requires_browser_sandbox=True`
- **Browser Operating Manual** — injected into Claude's system prompt with viewport rules, tool priority hierarchy (API tools first, browser fallback), and interaction guidelines
- **Browser tool routing** — `_process_browser_tool_loop()` in `api_server.py` intercepts Claude's browser tool calls, routes them through `aetherbrowser_client.py`, and feeds results back in a multi-turn tool-use loop
- **`requires_browser_sandbox`** flag on `ResolvedAgent` (mcp_router.py) and `TaskCreateRequest` (api_server.py) — gates all browser tool injection, default false

### Vault Credential Pipeline (NEW)
- **Browser credential tokens** (`vault/browser_credential.py`) — one-time signed JWT tokens using Protocol-C ephemeral ECDSA, 60-second expiry, JTI-based replay prevention
- **Token lifecycle** — `issue_browser_credential_token()` creates tokens bound to credential key + session ID; `redeem_browser_credential_token()` validates signature, checks expiry, enforces one-time use
- **In-memory JTI tracking** — redeemed token IDs stored in a set, cleared on restart (expired tokens are already invalid)

### Infrastructure
- **AetherBrowser deployed to VPS5** — port 8092, Tailscale reachable at 100.84.205.12
- **AetherForge deployed to VPS5** — port 8091, Tailscale reachable at 100.84.205.12
- **Environment wiring** — `AETHERBROWSER_URL`, `AETHERBROWSER_BEARER_TOKEN`, `AETHERFORGE_URL`, `AETHERFORGE_SECRET` added to VPS2 `.env`
- **UFW hardened** — ports 8091/8092 restricted to wg0 interface on VPS5, port 80 outbound locked after install

### Files Added
| File | Lines | Purpose |
|------|-------|---------|
| `agent/aetherbrowser_client.py` | 128 | Async HTTP client for browser automation |
| `agent/browser_tool_injector.py` | 146 | Dynamic tool injection + operating manual |
| `vault/browser_credential.py` | 148 | One-time credential token service |
| `docs/SMOKE_TEST_v0.9.5.md` | — | 4-phase manual smoke-test plan for this release |

### Files Modified
| File | Change |
|------|--------|
| `desktop/pages/dashboard.html` | Fixed `launchProject` / `connectProjectStream` / `loadProjectContext`; removed 36 lines of dead question-answer UI |
| `project_routes.py` | Synced `DASHBOARD_PROJECT_JS` template string so future re-embeds stay consistent with the fixed dashboard code |
| `api_server.py` | Added `requires_browser_sandbox` to TaskCreateRequest, browser tool injection call, `_process_browser_tool_loop()` tool routing, browser tool definitions |
| `mcp_router.py` | Added `requires_browser_sandbox: bool = False` to ResolvedAgent, populated from team.json config |
| `desktop/package.json` | Version bump 0.9.4 → 0.9.5 |
| `README.md` | Version footer + test counts refreshed (643 tests) |

### Known Non-Blockers (deferred)
- [desktop/pages/terminal.html:280](desktop/pages/terminal.html:280) — MCP-routed terminal queries call `window.aether.authGet()` but `authGet` is exposed on `window.aetherAPI`. Error is swallowed by try/catch, leaving MCP requests unauthenticated. Non-blocking (non-MCP path still works via `aetherAPI.chat`) but should be fixed next patch.
- Two stale test assertions: `test_total_suffix_count` expects 9 (current count is 10), `test_totp_code_is_8_digits` expects 8 (TOTP is 6-digit per RFC 6238). Tests need updating, not code.
- One commit in the merged AetherBrowser work is tagged `(v1.0.0)` in its message (`96f4d29`) — that was a draft version name that never shipped. The actual released version is v0.9.5.

---

## v0.9.2 — Security Hardening Release (2026-03-26)

### Security
- HTTPS enforced — all traffic encrypted via self-signed cert on VPS1
- Zero Trust authentication — 15-minute JWT tokens with silent refresh
- Device fingerprint binding — tokens tied to machine hardware ID
- Prompt injection detector — 40+ patterns, 6 categories
- Session management — login history, device tracking, revocation
- MCP agents isolated on dedicated VPS5 — separate from core backend
- Protocol-C audit trail on every MCP agent call
- Ed25519 node certificates — VPS2↔VPS5 mutual authentication

### Features
- DO Spaces vault storage — files stored in cloud, not on VPS disk
- Per-client vault isolation — cryptographic prefix enforcement
- Storage usage meter with upgrade prompts
- Active session management — view and revoke sessions from dashboard
- Security events timeline in LOGS tab
- MCP breach alert panel with severity indicators
- License activation screen — prompted once per machine, stored encrypted

### Infrastructure
- VPS5 deployed — 8GB dedicated MCP agent worker
- Scrambler switched to OS_URANDOM — $0 IBM cost until client onboarded
- License server operational — AETH-CLD and AETH-SCRM key types live
- All 5 VPS nodes hardened — SSH keys, fail2ban, UFW locked

### Tests
- 656 tests passing across all repos

---

## v0.6.0 — Agent Marketing Skills Patch (2026-03-20)

### Features
- **5 new marketing agent methods** — `create_competitive_card()`, `draft_content()`, `draft_email_sequence()`, `review_content()`, `develop_positioning()`
- **Hardened wrappers** — All 5 marketing methods get full Protocol-L commit+verify (SHA-256, ECDSA, RFC 3161)
- **Intent router** — `route_request()` on AetherFileAgent dispatches to any skill by intent string
- **Expanded system prompt** — 5 new competencies (8-12): Competitive Analysis, Content Drafting, Email Sequences, Content Review, Market Positioning
- **5 new QOPC task suffixes** — Structured JSON schemas for each marketing output type
- **5 new prompt optimizer variants** — Marketing tasks get independent accuracy tracking via QOPC feedback loop
- **4 new QOPC outcome types** — PUBLISHED, REVISED, DISCARDED, A_B_TESTED for marketing content lifecycle
- **Desktop offline fallback** — Agent chat recognizes competitive/content/email/positioning keywords

### Tests
- 44 new tests in `test_marketing_agent.py` — all 5 skills, QOPC outcomes, suffix registry, prompt variants
- **497 tests passing**, zero regressions

---

## v0.5.1 — Real Filesystem Wired to Vault Graph (2026-03-20)

### Features
- **`/vault/browse` endpoint** — Scans any directory path, returns folders/files with metadata (names, sizes, extensions only — no file contents leave the machine)
- **CONNECT button** — Desktop app calls backend, populates vault graph with real files and folders from the selected directory
- **Folder expand** — Clicking a folder fetches real subfolder contents via API
- **Dynamic sidebar** — Working folders update with actual names and file counts
- **Pan/zoom** — Left-click drag to pan background, click nodes to center + zoom
- **Key manager** — Encrypted API key storage via `electron-store` (AES at rest, tied to machine profile)
- **File access permission dialog** — One-time prompt after install for vault directory access
- **Dev user `ZO`** — Registered on startup with bcrypt-hashed password (never stored in plaintext)
- **IBM quantum key** — Stored at `~/.aether/ibm_credentials.json` (mode 600)

### Helpers
- `_get_category_by_name()` — Name-based keyword categorization with extension fallback
- `_get_folder_icon()` — Contextual emoji icons for folder names (code, trading, security, etc.)
- Folders sorted alphabetically, files sorted by size descending
- Capped at 12 folders + 8 loose files for graph display performance

### Tests
- 43 new tests in `test_vault_browse.py` — endpoint, helpers, edge cases (permissions, hidden files, caps)
- **453 tests passing**, zero regressions

---

## v0.5.0 — Code Hardening & Investor-Ready Polish (2026-03-19)

### Improvements
- **Investor-grade README** — Simplified, table-driven, problem→solution structure
- **Unified extension metadata** — Merged icon and category maps into single `_EXT_META` dict; eliminates drift
- **Services dataclass** — Replaced 6 mutable globals with a typed `Services` container in `api_server.py`
- **IBM quantum status caching** — 30-second TTL avoids redundant per-request imports
- **Audit DOM capping** — Max 100 entries in desktop UI; Set-based dedup replaces naive count comparison
- **Exponential backoff** — Python process restart uses 2s → 30s cap instead of fixed delay
- **Login latency** — Reduced artificial UI delay from 1500ms to ~500ms
- **Interval cleanup** — Audit poll timer cleared on `beforeunload` to prevent leaks

### Bug Fixes
- Fixed bare `except` blocks silently swallowing errors — all now log warnings
- Removed false-positive threat detection from `/agent/chat` (keyword parsing on "no threats detected")
- Fixed flawed audit dedup that diverged over time
- Removed duplicate `files` field from `VaultListResponse` (folders already contain files)
- Fixed global `mousemove` listener firing when tooltip hidden
- Fixed test accessing private `_sessions` dict — now uses public `generate_token()` API
- Removed unused imports (`HARDENED_AGENT_ENABLED`, `CLAUDE_API_KEY`, `CLAUDE_MODEL`)

---

## v0.4.0 — FastAPI Backend + Electron IPC Bridge (2026-03-19)

### Features
- **REST API server** — FastAPI on `localhost:8741` with 8 endpoints: auth, vault, agent, audit, status
- **Python process management** — Electron spawns Python backend, polls `/status` until ready
- **IPC bridge** — `window.aetherAPI` provides typed HTTP methods for all endpoints with graceful fallback
- **Pydantic models** — Request/response validation for every endpoint
- **HTTPBearer auth** — Session token middleware with `_require_session()` dependency
- **CORS** — Configured for Electron localhost origins
- **Lifespan context manager** — Replaced deprecated `on_event("startup")`
- **49 API tests** — 10 test classes covering all endpoints, auth flows, helpers, and integration

### Endpoints
| Endpoint | Method | Description |
|---|---|---|
| `POST /auth/login` | Auth | Returns quantum-seeded session token |
| `POST /auth/logout` | Auth | Terminates session with audit entry |
| `GET /vault/list` | Vault | File/folder tree with stats |
| `POST /agent/chat` | Agent | Protocol-L committed AI chat |
| `POST /agent/analyze` | Agent | File analysis + rename suggestions |
| `POST /agent/scan` | Agent | Security threat assessment |
| `GET /audit/trail` | Audit | Query signed audit entries |
| `GET /status` | Health | System status (no auth) |

---

## v0.3.0 — Electron Desktop App (2026-03-18)

### Features
- **Frameless Electron shell** — Custom title bar, quantum-themed UI
- **Three-page flow** — Installer → Login → App with IPC-driven navigation
- **Vault graph** — Interactive node visualization of file hierarchy
- **Agent chat** — Real-time AI conversation panel with Protocol-L verification badges
- **Audit sidebar** — Live-updating signed audit trail
- **Cross-platform builds** — Electron Builder configs for Windows (NSIS), macOS (DMG), Linux (AppImage)
- **Window geometry** — Per-page size configs with min constraints

---

## v0.2.2 — QOPC Recursive Truth Loop (2026-03-17)

### Features
- **QOPC feedback loop** — Quantum Oracle Protocol Commitment with recursive verification
- **Specialist agent prompts** — Domain-specific prompt templates for file analysis
- **361 tests passing** — Comprehensive coverage across all Protocol-L modules

---

## v0.2.0 — HardenedClaudeAgent + Protocol-L (2026-03-16)

### Features
- **HardenedClaudeAgent** — Every Claude API response is SHA-256 hashed, ECDSA-signed, and RFC 3161 timestamped before the system acts on it
- **Protocol-L engine** — 16-module quantum cryptographic layer with pure Python secp256k1
- **Ephemeral ECDSA keys** — Generated from quantum entropy, destroyed after single use
- **Tamper detection** — Any modification invalidates the signature chain

---

## v0.1.0 — Initial Scaffold (2026-03-15)

### Features
- **Claude AI agent** — File analysis, organization, natural language queries
- **File watcher** — Real-time monitoring with intrusion detection
- **Textual dashboard** — Rich retro terminal with 13 commands
- **Quantum seed integration** — IBM Quantum hardware, Aer simulator, and OS entropy fallback
- **Append-only audit log** — JSONL + SQLite index with ECDSA-signed entries
- **Session management** — Quantum-seeded token generation and validation

---

*For architecture details, see [README.md](README.md).*
