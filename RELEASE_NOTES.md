# AetherCloud-L — Release Notes

*Aether Systems LLC · Patent Pending (Application #64/010,131)*

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
