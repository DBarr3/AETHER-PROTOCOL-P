# AetherCloud-L

**Quantum-Secured AI File Intelligence**
*Aether Systems LLC — Patent Pending (Application #64/010,131)*

---

## The Problem

Every organization stores critical files — patents, contracts, financial records, source code. Yet no existing system can mathematically prove that a file was not tampered with, that an AI's recommendation was not altered in transit, or that an unauthorized actor did not access the vault. Traditional audit logs can be silently modified. Traditional access controls can be bypassed. There is no cryptographic chain of custody.

## The Solution

AetherCloud-L is the first file management system where **every operation, every AI decision, and every intrusion attempt produces immutable, dispute-proof, quantum-safe evidence**.

Three patent-pending innovations make this possible:

| Innovation | What It Does |
|---|---|
| **Quantum-Signed File Operations** | Every file access is ECDSA-signed with a key derived from quantum entropy, then the key is destroyed. No one — including us — can forge a past entry. |
| **Real-Time Intrusion Detection** | If someone touches a file outside the system, the event is detected, signed, and sealed into the audit chain within milliseconds. |
| **Cryptographically Verified AI** | Every Claude AI response is SHA-256 hashed, quantum-signed, and RFC 3161 timestamped *before* the system acts on it. Tampered responses are rejected automatically. |

---

## How It Works

```
User Action → SHA-256 Hash → Quantum Seed → ECDSA Sign → Destroy Key → Audit Log → Execute
```

The signing key is generated from quantum entropy (IBM Quantum hardware, simulator, or OS entropy) and destroyed after a single use. Even a full system compromise cannot forge historical entries.

For AI decisions, the chain adds **session binding** and **RFC 3161 timestamping** — creating a legally defensible record of every recommendation the AI makes.

---

## Product

| Component | Description |
|---|---|
| **Desktop App** | Electron-based GUI — visual vault graph, AI chat, real-time audit sidebar |
| **AI Agent** | Claude-powered file analysis, organization, threat detection, natural language queries |
| **Protocol-L Engine** | 16-module quantum cryptographic layer (pure Python secp256k1, no external crypto dependencies) |
| **REST API** | FastAPI server on localhost — 8 endpoints for auth, vault, agent, audit, and status |
| **CLI Terminal** | Rich retro terminal with 13 commands for power users |

---

## Quick Start

```bash
git clone https://github.com/DBarr3/AETHER-CLOUD.git
cd AETHER-CLOUD
pip install -r requirements.txt

# Terminal mode
python main.py

# API server mode (for desktop app)
python main.py --serve

# Desktop app
cd desktop && npm install && npm start
```

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `POST /auth/login` | Auth | Returns quantum-seeded session token |
| `POST /auth/logout` | Auth | Terminates session with audit entry |
| `GET /vault/list` | Vault | File/folder tree with stats |
| `POST /agent/chat` | Agent | Protocol-L committed AI chat |
| `POST /agent/analyze` | Agent | File analysis + rename suggestions |
| `POST /agent/scan` | Agent | Security threat assessment |
| `GET /audit/trail` | Audit | Query signed audit entries |
| `GET /status` | Health | System status (no auth required) |

---

## Security Model

| Property | Implementation |
|---|---|
| Perfect Forward Secrecy | Ephemeral ECDSA keys destroyed after single use |
| Quantum Safety | secp256k1 requires ~2,330 logical qubits to break; current hardware has ~10 |
| Tamper Detection | Any modification invalidates the ECDSA signature chain |
| Immutable Audit | Append-only JSONL + SQLite index — no update/delete operations exist |
| Zero File Leakage | File contents never leave the machine |
| AI Verification | Every Claude response committed and verified before action |

---

## Architecture

```
Desktop (Electron)  ←→  FastAPI :8741  ←→  Agent Layer  ←→  Protocol-L Engine
     │                       │                  │                    │
  Installer              Auth/Session     Claude AI (Hardened)   Quantum Seeds
  Login                  Vault CRUD       QOPC Feedback Loop    ECDSA Signing
  Vault Graph            Audit Query      File Analysis          RFC 3161 TSA
  Agent Chat             Status           Security Scan          Audit Log
```

---

## Test Coverage

**410 tests** across 16 test files. All passing.

```bash
pytest tests/ -v
```

---

## License

Proprietary. All rights reserved.

*Aether Systems LLC — Patent Pending (Application #64/010,131)*

*See [RELEASE_NOTES.md](RELEASE_NOTES.md) for version history.*
