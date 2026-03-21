# AetherCloud-L

**Quantum-Secured File Intelligence Platform**
*Aether Systems LLC — Patent Pending (Application #64/010,131)*

---

## The Problem

Every enterprise handling sensitive files faces three unsolved problems:

**1. Audit trails are not evidence.**
Traditional audit logs can be modified by administrators, compromised servers, or subpoenaed cloud providers. In a dispute, your log is opinion — not proof.

**2. AI outputs have no chain of custody.**
The response your AI generated and the response your system acted on may not be the same. No existing product proves they match.

**3. AI tools start from zero every session.**
No content tool learns which outputs you published, revised, or discarded. You pay for the same mediocre first draft indefinitely.

AetherCloud-L solves all three.

---

## What AetherCloud-L Is

A **desktop-native file intelligence platform** with two capabilities that do not exist in any competing product:

### Dispute-Proof File Chain of Custody

Every file operation — read, write, move, rename, delete, external access — is:

- **SHA-256 hashed** for content integrity
- **Signed with a quantum-seeded ephemeral ECDSA key** destroyed after a single use
- **RFC 3161 timestamped** for legal admissibility
- **Appended to an immutable audit log** — no update or delete operations exist in the codebase
- **Exportable as cryptographic proof packages** for litigation or compliance

The result: a chain of evidence that proves *exactly* what happened, *exactly* when, signed by a key that no longer exists and cannot be coerced. This is not an improvement to existing audit systems. It is a different category of evidence.

### Self-Improving AI Agent with Signed Outputs

Every AI output is **committed to the same cryptographic chain** before the system acts on it. Tampered responses are automatically rejected — the signature check fails and the system refuses to proceed.

The **QOPC Feedback Loop** (Quantum Optimized Prompt Circuit) observes what you do with every recommendation: accept, revise, publish, discard. Each outcome adjusts prompt variant weights. The agent gets measurably better over time — not because the model changed, but because the prompts driving it have been optimized by your behavior.

No other file system signs its AI outputs. No other AI tool learns from your publish/revise/discard patterns.

---

## Architecture

```
Electron Desktop App
        |
   VPS1 (Ghost Proxy — 143.198.162.111)
        |
   VPS2 (API Server — 198.211.115.41:8080)
        |
   +---------+-----------+-----------+------------------+
   |         |           |           |                  |
 Auth    Vault/FS    AI Agent    Protocol-L        Scheduler
 Layer    Layer       Layer      Engine             Engine
   |         |           |           |                  |
 bcrypt   Watcher    Claude AI   Quantum Seeds     APScheduler
 Sessions  ReadDetect  Hardened   ECDSA Signing    QOPC Auto-Optimize
 MFA      FileBase    QOPC Loop  RFC 3161 TSA     NL Schedule Parser
        |
   VPS3 (Dark Node — 161.35.109.243:8077)
```

| Layer | Components | Lines of Code |
|---|---|---|
| **Aether Protocol** | 16 modules — quantum crypto, ECDSA signing, audit, timestamps, commitments | ~4,000 |
| **AI Agent** | 10 modules — Claude intelligence, QOPC feedback, task scheduling, marketing engine | ~3,500 |
| **Vault** | 5 modules — file storage, indexing, access watching, read detection | ~1,500 |
| **Auth** | 4 modules — bcrypt login, quantum-seeded sessions, MFA | ~500 |
| **API Server** | FastAPI REST — 24 endpoints, Pydantic models, per-user data isolation | ~1,600 |
| **Desktop** | Electron app — preload bridge, secure key manager, 4 HTML pages | ~7,500 |
| **Tests** | 19 test files, **576 tests**, zero external dependencies | ~5,000 |

**Total: ~68 Python files, ~23,000+ lines of application code**

---

## Core Capabilities

### File Intelligence

| Capability | Description |
|---|---|
| **Cryptographic Audit Trail** | Every file event Protocol-L committed with SHA-256 + ECDSA + RFC 3161 |
| **Live Access Logging** | LOGS tab with color-coded event feed, detail drawer, proof export |
| **Unauthorized Read Detection** | st_atime polling detects external file reads and seals them into the audit chain |
| **VaultWatcher Protocol-L** | Real-time filesystem watcher classifies AETHERCLOUD vs EXTERNAL sources |
| **File Analysis** | AI-powered categorization, rename suggestions, security risk flagging |
| **Natural Language Search** | "Where is my patent filing?" returns paths with audit references |
| **Threat Detection** | Analyzes audit trail for brute force, enumeration, credential access, anomalous hours |

### AI Marketing Engine

| Capability | Description |
|---|---|
| **Competitive Intelligence** | Feature matrices with WIN/LOSE/TIE verdicts and counter-positioning |
| **Content Drafting** | Blog posts, LinkedIn, press releases, landing pages — multiple variants with A/B recommendations |
| **Email Sequences** | Multi-email drip campaigns with subject lines, preview text, body, CTA, send timing |
| **Content Review** | Flesch-Kincaid scoring, claim verification, accuracy checking, full rewrites |
| **Market Positioning** | Value proposition canvas, ICP definition, messaging hierarchy, moat analysis |

### Task Scheduling + QOPC Learning

| Capability | Description |
|---|---|
| **Scheduled Tasks** | Natural language scheduling ("every weekday at 9am") backed by APScheduler |
| **QOPC Signal Collection** | Records USED, EDITED, OPENED, IGNORED, DELETED, MANUAL_RUN per task |
| **Auto-Reschedule** | Midnight optimizer adjusts task timing based on actual interaction patterns |
| **Prompt Injection** | QOPC insights prepended to Claude API calls for context-aware responses |

---

## Security Model

| Property | Implementation |
|---|---|
| **Perfect Forward Secrecy** | Ephemeral ECDSA keys from quantum entropy, destroyed after single use |
| **Quantum Safety** | secp256k1 requires ~2,330 logical qubits to break; current hardware: ~10 |
| **Tamper Detection** | Any modification invalidates the ECDSA signature chain |
| **Immutable Audit** | Append-only JSONL + SQLite index — no update/delete operations in the codebase |
| **Zero File Leakage** | File contents never leave the machine — only filenames and paths sent to AI |
| **AI Verification** | Every response SHA-256 hashed, ECDSA signed, RFC 3161 timestamped before action |
| **Session Binding** | Every AI response cryptographically bound to the requesting session |
| **Secure Key Storage** | API keys loaded from `/etc/aethercloud/.env` (chmod 600) via `key_manager.py` |
| **CORS Hardened** | Restricted origins, explicit method/header allowlists |
| **Auth Protection** | bcrypt password hashing, configurable lockout, session expiration |

---

## Competitive Position

| Capability | AetherCloud-L | Dropbox | Box | Tresorit | Google Drive |
|---|---|---|---|---|---|
| Quantum-seeded signing | **Yes** | No | No | No | No |
| Ephemeral key destruction | **Yes** | No | No | No | No |
| Cryptographically verified AI | **Yes** | No | No | No | No |
| Self-improving AI (QOPC) | **Yes** | No | No | No | No |
| RFC 3161 legal timestamps | **Yes** | No | No | No | No |
| Marketing content engine | **Yes** | No | No | No | No |
| Zero file content leakage | **Yes** | No | No | Partial | No |
| Dispute-proof audit trail | **Yes** | No | No | No | No |
| Scheduled AI tasks + learning | **Yes** | No | No | No | No |
| Proof package export | **Yes** | No | No | No | No |
| Desktop-native | **Yes** | No | No | No | No |

No existing product combines cryptographic chain of custody with self-improving AI reasoning. AetherCloud-L is the first.

---

## API Reference (24 Endpoints)

### Authentication
| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/auth/login` | POST | No | Returns quantum-seeded session token |
| `/auth/logout` | POST | Yes | Terminates session with signed audit entry |
| `/auth/setup` | POST | No | First-run admin creation (disabled after first user) |
| `/auth/health` | GET | No | Auth readiness check for Electron pre-login |

### Vault
| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/vault/list` | GET | Yes | File/folder tree with categories and stats |
| `/vault/browse` | GET | No | Directory scan for vault graph display |
| `/vault/scan` | POST | No | Filesystem scan returning structured vault data |

### AI Agent
| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/agent/chat` | POST | Yes | Natural language vault queries — Protocol-L committed |
| `/agent/analyze` | POST | Yes | File analysis with rename/security flags |
| `/agent/scan` | POST | Yes | Security threat assessment on audit trail |
| `/agent/context` | POST/GET | Yes | Set/get user context preferences |

### Audit Trail
| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/audit/trail` | GET | Yes | Query signed, timestamped audit entries |
| `/audit/trail/live` | GET | Yes | Live audit feed with filtering |
| `/audit/export-proof` | POST | Yes | Export cryptographic proof package |
| `/audit/exports` | GET | Yes | List all proof packages |
| `/audit/download/{filename}` | GET | Yes | Download proof package JSON |

### Scheduled Tasks
| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/tasks/create` | POST | Yes | Create scheduled task with NL schedule |
| `/tasks/list` | GET | Yes | List tasks with QOPC scores |
| `/tasks/{id}` | DELETE | Yes | Remove task |
| `/tasks/{id}` | PATCH | Yes | Update task schedule/status |
| `/tasks/{id}/run` | POST | Yes | Manual trigger with QOPC injection |
| `/tasks/{id}/history` | GET | Yes | Per-user execution history |
| `/tasks/{id}/signal` | POST | Yes | Record QOPC signal |
| `/tasks/{id}/qopc` | GET | Yes | Full QOPC state and prompt injection |

### System
| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/status` | GET | No | System health — Protocol-L, agent, watcher, quantum status |
| `/routing-check` | GET | No | VPS2 identity verification and key status |

---

## How the QOPC Feedback Loop Works

```
Node 1: DQVL   Capture verified vault state (ground truth)
Node 2: QOPGC  Select optimal prompt variant (weighted by history)
Node 3: LLMRE  Call Claude with selected variant (hardened, signed)
Node 4: QOVL   Validate response against vault state (catch hallucinations)
Node 5: REAL   Observe user action (outcome scoring)
  Loop: D(n)   Delta feeds back to Node 2 for next cycle
```

| Outcome | Score | Meaning |
|---|---|---|
| `PUBLISHED` | 1.0 | Content published unchanged |
| `ACCEPTED` | 1.0 | Suggestion taken as-is |
| `A_B_TESTED` | 0.8 | Entered A/B testing |
| `REVISED` | 0.6 | Edited then used |
| `IGNORED` | 0.5 | No action taken |
| `CORRECTED` | 0.3 | Significantly modified |
| `REJECTED` | 0.0 | Explicitly rejected |
| `DISCARDED` | 0.0 | Thrown away |

Blended scoring: **`final = outcome_score x 0.7 + context_alignment x 0.3`**

---

## Quick Start

### VPS2 Backend
```bash
# First time — secure key setup
sudo bash scripts/setup_keys.sh
sudo nano /etc/aethercloud/.env
# Add: ANTHROPIC_API_KEY=sk-ant-...

# Start server
python api_server.py

# Verify
bash scripts/verify_vps2.sh
```

### Desktop App (Windows)
```bash
cd desktop
npm install
npm start

# Build portable .exe
npx electron-builder --win portable
```

### Run Tests
```bash
pip install -r requirements.txt
python -m pytest tests/ -q
# 576 passed
```

---

## Directory Structure

```
AETHER-CLOUD/
|-- api_server.py              FastAPI server (24 endpoints)
|-- main.py                    CLI entry point
|-- aether_protocol/           Quantum cryptographic engine (16 modules)
|   |-- audit.py               Immutable append-only audit log
|   |-- quantum_backend.py     IBM Quantum / simulator / OS fallback
|   |-- quantum_crypto.py      Quantum seed commitments + ephemeral keys
|   |-- ephemeral_signer.py    secp256k1 ECDSA with RFC 6979
|   |-- commitment.py          Decision commitment binding
|   |-- execution.py           Trade execution attestation
|   |-- settlement.py          Final settlement sealing
|   |-- timestamp_authority.py RFC 3161 timestamp tokens
|   +-- verify.py              Complete flow verification
|-- agent/                     AI intelligence layer (10 modules)
|   |-- claude_agent.py        Base Claude agent
|   |-- hardened_claude_agent.py  Cryptographic output verification
|   |-- file_agent.py          File categorization + organization
|   |-- task_scheduler.py      APScheduler + NL parser
|   |-- task_qopc.py           QOPC feedback for scheduled tasks
|   +-- qopc_feedback.py       Prompt optimization loop
|-- auth/                      Authentication (4 modules)
|   |-- login.py               bcrypt + quantum-seeded sessions
|   |-- session.py             In-memory session management
|   +-- mfa.py                 Multi-factor authentication
|-- vault/                     File management (5 modules)
|   |-- filebase.py            File storage + retrieval
|   |-- watcher.py             VaultWatcher Protocol-L
|   |-- read_detector.py       st_atime read detection
|   +-- index.py               File indexing + metadata
|-- config/                    Configuration (5 modules)
|   |-- storage.py             Single source of truth for all paths
|   |-- key_manager.py         Secure API key loading
|   +-- settings.py            App constants
|-- desktop/                   Electron app
|   |-- main.js                Main process + backend health check
|   |-- preload.js             IPC bridge (aether + aetherAPI)
|   |-- key-manager.js         AES-encrypted key storage
|   +-- pages/
|       |-- login.html         Auth screen with protocol indicators
|       +-- dashboard.html     Main UI (~6,400 lines)
|-- tests/                     576 tests across 19 files
|-- scripts/                   Deployment + verification
+-- deploy/                    VPS automation
```

---

## Test Coverage

**576 tests. All passing. Zero external dependencies — every API call mocked.**

```bash
python -m pytest tests/ -q
# 576 passed in ~30s
```

| Suite | Tests | Coverage |
|---|---|---|
| Protocol-L crypto | 180+ | SHA-256, ECDSA, quantum seeds, RFC 3161, ephemeral keys |
| Vault operations | 80+ | File CRUD, audit trail, watcher, permissions |
| AI agent (file) | 23 | Analysis, batch, chat, security scan, fallbacks |
| AI agent (marketing) | 44 | Competitive cards, content, email, review, positioning |
| QOPC feedback | 50+ | Optimizer, validator, outcome observer, blended scoring |
| User context | 31 | Intent parsing, alignment scoring, context injection |
| API server | 43+ | Auth, vault, endpoints, error handling |
| CLI terminal | 30+ | All commands, edge cases |
| Scheduled tasks | 40+ | CRUD, NL parsing, QOPC signals, auto-reschedule |

---

## Intellectual Property

- **Patent Application #64/010,131** — Filed with USPTO
- Three core claims:
  1. Quantum-signed file operations with ephemeral key destruction
  2. Real-time intrusion detection with cryptographic sealing
  3. Cryptographically verified AI reasoning with session binding
- **Proprietary. All rights reserved.**

---

*Aether Systems LLC — Patent Pending*
*Version 0.8.9 | See [RELEASE_NOTES.md](RELEASE_NOTES.md) for version history*
