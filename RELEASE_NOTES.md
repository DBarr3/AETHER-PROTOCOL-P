# AetherCloud-L — Release Notes

*Aether Systems LLC · Patent Pending (Application #64/010,131)*

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
