# AetherCloud-L

**Quantum-Secured AI File Intelligence System**
*Aether Systems LLC — Patent Pending*

---

## Why Does This Exist?

Every day, billions of files are created, moved, renamed, and deleted across personal and enterprise systems. Not a single one of those operations leaves a cryptographically verifiable trail. If a file is tampered with, accessed by an unauthorized party, or silently modified by malware — there is no mathematical proof it happened. The audit logs that do exist can themselves be altered.

AetherCloud-L solves this with three innovations:

**1. Every file operation is cryptographically signed before it executes.** Not hashed. Not logged. *Signed* — with an ECDSA key derived from quantum entropy, then immediately destroyed. The signature is mathematically bound to the exact state of the file at that moment. Alter the log and the signature breaks. Alter the file and the commitment breaks. There is no way to retroactively forge the trail.

**2. If someone bypasses the system entirely and touches a file directly, the intrusion is detected in real time and signed into the audit chain.** The VaultWatcher monitors the filesystem independently. A hacker can delete their footprints from a traditional log. They cannot delete a cryptographically signed entry from an append-only ledger without invalidating every entry that follows it.

**3. Every AI decision the system makes is cryptographically committed before it is acted upon.** When Claude analyzes a file and suggests a rename, that response is SHA-256 hashed, bound to a quantum-seeded session token, ECDSA signed, and RFC 3161 timestamped. If the response is modified between generation and action — by a man-in-the-middle, a compromised dependency, or a memory corruption — the verification fails and AetherCloud-L refuses to act. This is the first system with *cryptographically verified AI reasoning*.

The result: a personal file vault where every access, every AI decision, and every intrusion attempt produces immutable, dispute-proof, quantum-safe evidence.

---

## What Is It?

AetherCloud-L is a local-first file intelligence system built on [Aether Protocol-L](https://github.com/DBarr3/AETHER-PROTOCOL-L), a quantum-authenticated decision protocol. It combines:

- **AI File Agent** — Claude API-powered file analysis, organization, naming, and natural language queries
- **Protocol-L Commitment Layer** — SHA-256 + quantum ephemeral key + ECDSA signature on every operation
- **Tamper-Proof Audit Trail** — Append-only JSONL with SQLite index, automatic rotation, RFC 3161 timestamps
- **Real-Time Intrusion Detection** — VaultWatcher monitors for unauthorized filesystem access
- **Hardened AI Verification** — Every Claude response cryptographically committed and verified before action
- **Retro Terminal + TUI Dashboard** — Rich CLI and Textual three-panel dashboard

File contents **never leave your machine**. Only filenames and directory paths are sent to the Claude API for analysis.

---

## Architecture

```
AetherCloud-L v0.3.0
=====================

                 ┌─────────────────────────────────────┐
                 │            UI LAYER                  │
                 │  Terminal (Rich)  │  Dashboard (TUI) │
                 └────────┬─────────┴────────┬─────────┘
                          │                  │
              ┌───────────▼──────────────────▼───────────┐
              │              AGENT LAYER                  │
              │                                           │
              │   FileAgent ─── routes to ───┐            │
              │       │                      │            │
              │   ClaudeAgent          HardenedClaudeAgent│
              │   (standard)           (Protocol-L signed) │
              │       │                      │            │
              │   Organizer   IntentAnalyzer  Suggester   │
              └───────┬──────────────────────┬───────────┘
                      │                      │
              ┌───────▼──────────────────────▼───────────┐
              │              VAULT LAYER                   │
              │                                           │
              │   AetherVault ─── every op commits ───┐   │
              │       │                               │   │
              │   VaultWatcher        VaultIndex       │   │
              │   (intrusion detect)  (SQLite search)  │   │
              └───────┬──────────────────────┬────────┘   │
                      │                      │            │
              ┌───────▼──────────────────────▼───────────┐
              │              AUTH LAYER                    │
              │                                           │
              │   AetherCloudAuth ── bcrypt + lockout     │
              │   SessionManager  ── token lifecycle      │
              │   MFAManager      ── TOTP (scaffold)      │
              └───────┬──────────────────────────────────┘
                      │
         ┌────────────▼────────────────────────────────────┐
         │           AETHER PROTOCOL-L                      │
         │                                                  │
         │  QuantumSeedCommitment    QuantumEphemeralKey     │
         │  EphemeralSigner (ECDSA)  RFC3161TimestampAuthority│
         │  AuditLog (JSONL+SQLite)  AuditVerifier           │
         │  DisputeProofGenerator    ReasoningCapture         │
         │                                                  │
         │  Backends: IBM Quantum │ AER Simulator │ OS_URANDOM│
         └──────────────────────────────────────────────────┘
```

---

## How the Cryptographic Chain Works

Every file operation in AetherCloud-L follows this sequence:

```
1. User action (read, move, rename, delete)
        │
2. SHA-256 hash the operation details
        │
3. Generate quantum seed (IBM Quantum / AER Simulator / OS_URANDOM)
        │
4. Derive ephemeral ECDSA key from seed
        │
5. Sign the commitment with ephemeral key
        │
6. DESTROY the private key (zeroed from memory)
        │
7. Append signed entry to audit log (JSONL + SQLite index)
        │
8. Execute the file operation
```

The key is destroyed after a single use. Even if an attacker compromises the system *after* the operation, they cannot forge a past entry because the signing key no longer exists. This is **perfect forward secrecy**.

For the Hardened AI Agent, Claude responses go through the same pipeline *plus* session binding and RFC 3161 timestamping — creating a verifiable chain of custody for every AI decision.

---

## Three Patent Claims

### Claim 1: Quantum-Authenticated File Audit Trail
Every file operation is committed via Protocol-L with an independent quantum seed. The seed derives an ephemeral ECDSA key that signs the operation and is immediately destroyed. The result is an append-only, tamper-proof, dispute-proof audit trail where each entry is mathematically independent.

### Claim 2: Real-Time Intrusion Detection with Cryptographic Proof
VaultWatcher monitors the filesystem for any access that did not go through AetherCloud-L. Unauthorized events (file created, modified, or deleted outside the system) are detected, signed via Protocol-L, and appended to the audit chain. A hacker cannot delete the evidence without invalidating the signature chain.

### Claim 3: Cryptographically Verified AI Reasoning
Every Claude API response is SHA-256 hashed, bound to a quantum-seeded session token, ECDSA signed with an ephemeral key, and RFC 3161 timestamped. Before the system acts on any AI decision, the full cryptographic chain is verified. If tampering is detected, a `ResponseTamperingError` is raised and the action is refused. This creates an immutable, dispute-proof record of every AI decision.

---

## Quick Start

### Prerequisites

- Python 3.11+
- [Anthropic API key](https://console.anthropic.com/) (for Claude AI agent)

### Install

```bash
git clone https://github.com/DBarr3/AETHER-CLOUD.git
cd AETHER-CLOUD
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### Run

```bash
python main.py
```

### Run Tests

```bash
pytest tests/ -v
```

300 tests across 13 test files.

---

## Commands

| Command | Description |
|---------|-------------|
| `login` | Authenticate with bcrypt-verified credentials |
| `logout` | End session (signed audit entry) |
| `ls [path]` | List files in vault with metadata |
| `audit [path]` | Show cryptographically signed audit trail |
| `organize [--dry-run]` | AI-powered file organization |
| `chat "<query>"` | Natural language vault queries |
| `scan` | Security threat analysis on audit trail |
| `verify` | Show agent verification report (tamper detection stats) |
| `rename <file>` | Get AI name suggestion |
| `move <src> <dest>` | Move file with signed audit entry |
| `status` | Vault stats, watcher state, Protocol-L status |
| `help` | Show all commands |
| `exit` | Quit (preserves audit trail) |

---

## Configuration

All configuration is via environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *required* | Claude API key |
| `AETHER_VAULT_ROOT` | `./vault_data` | Vault storage directory |
| `AETHER_AGENT_MODEL` | `claude-opus-4-5` | Claude model for AI agent |
| `AETHER_SESSION_TIMEOUT` | `8` | Session timeout in hours |
| `AETHER_MAX_LOGIN_ATTEMPTS` | `5` | Failed attempts before lockout |
| `AETHER_LOCKOUT_DURATION` | `900` | Lockout duration in seconds |
| `AETHER_HARDENED_AGENT` | `true` | Enable Protocol-L hardened AI |
| `AETHER_RFC3161_ENABLED` | `true` | Enable RFC 3161 timestamping |
| `AETHER_AUDIT_MAX_MB` | `100` | Audit log rotation threshold |

---

## Directory Structure

```
AETHER-CLOUD/
├── aether_protocol/              # Protocol-L quantum audit engine (16 modules)
│   ├── quantum_crypto.py         #   QuantumSeedCommitment, QuantumEphemeralKey
│   ├── ephemeral_signer.py       #   Pure Python secp256k1 ECDSA (no external crypto)
│   ├── audit.py                  #   Append-only JSONL + SQLite index
│   ├── commitment.py             #   Decision commitments + ReasoningCapture
│   ├── execution.py              #   Execution attestations
│   ├── settlement.py             #   Settlement records with 3-way merkle
│   ├── verify.py                 #   Trade flow verification + dispute proofs
│   ├── timestamp_authority.py    #   RFC 3161 TSA integration
│   ├── quantum_backend.py        #   IBM Quantum / AER Simulator / OS_URANDOM
│   ├── quantum_session.py        #   IBM hard-cap session manager
│   ├── async_protocol.py         #   Async wrapper for non-blocking ops
│   ├── state.py                  #   Account state snapshots
│   ├── dispute_report.py         #   PDF dispute report generation
│   ├── server.py                 #   FastAPI server (scaffold)
│   └── terminal_ui.py            #   Protocol-L console output
│
├── agent/                        # AI file intelligence layer
│   ├── hardened_claude_agent.py   #   Protocol-L hardened Claude wrapper [Patent Claim 3]
│   ├── claude_agent.py           #   Standard Claude API agent
│   ├── file_agent.py             #   High-level agent orchestrator
│   ├── organizer.py              #   YYYYMMDD_CATEGORY_Description naming enforcer
│   ├── intent.py                 #   File intent/purpose analyzer
│   └── suggest.py                #   Proactive suggestion engine
│
├── vault/                        # File directory + monitoring
│   ├── filebase.py               #   AetherVault — every op commits via Protocol-L
│   ├── watcher.py                #   VaultWatcher — real-time intrusion detection
│   └── index.py                  #   VaultIndex — SQLite searchable file index
│
├── auth/                         # Authentication & sessions
│   ├── login.py                  #   bcrypt auth + lockout + Protocol-L audit
│   ├── session.py                #   In-memory session token lifecycle
│   └── mfa.py                    #   TOTP multi-factor (scaffold)
│
├── ui/                           # User interfaces
│   ├── terminal.py               #   Rich retro terminal (13 commands)
│   └── dashboard.py              #   Textual TUI 3-panel dashboard
│
├── desktop/                      # Electron desktop app
│   ├── main.js                   #   Electron main process (frameless, secure)
│   ├── preload.js                #   Context bridge (minimal IPC surface)
│   ├── package.json              #   Electron + electron-builder config
│   └── pages/
│       ├── installer.html        #   4-step install wizard
│       ├── login.html            #   Quantum-themed authentication
│       └── app.html              #   Main vault — node graph + agent chat + sidebar
│
├── config/
│   └── settings.py               #   All configuration + system prompt
│
├── tests/                        # 361 tests across 15 files
│   ├── conftest.py               #   Shared fixtures
│   ├── test_hardened_agent.py    #   65 tests — commit/verify/tamper detection
│   ├── test_claude_agent.py      #   30 tests — Claude API + fallback
│   ├── test_agent.py             #   29 tests — FileAgent orchestration
│   ├── test_auth.py              #   25 tests — login/logout/lockout
│   ├── test_vault.py             #   25 tests — file operations
│   ├── test_terminal.py          #   22 tests — command dispatch
│   ├── test_watcher.py           #   13 tests — intrusion detection
│   ├── test_dashboard.py         #   13 tests — TUI components
│   ├── test_index.py             #   14 tests — SQLite index
│   ├── test_intent.py            #   18 tests — intent classification
│   ├── test_organizer.py         #   14 tests — naming convention
│   ├── test_suggest.py           #   12 tests — proactive suggestions
│   └── test_mfa.py               #   MFA scaffold tests
│
├── main.py                       # Entry point
├── requirements.txt              # Dependencies
├── .env.example                  # Configuration template
└── CLAUDE.md                     # AI assistant instructions
```

---

## Security Model

| Property | How It's Achieved |
|----------|-------------------|
| **Perfect Forward Secrecy** | Each operation uses an independent quantum seed to derive an ephemeral ECDSA key that is destroyed after a single signature |
| **Quantum Safety** | secp256k1 ECDSA requires ~2,330 logical qubits to break; current quantum computers have ~5-10. Keys expire in 1 hour; Shor's earliest attack window is 7+ days |
| **Tamper Detection** | Any modification to an audit entry invalidates its ECDSA signature and breaks the chain |
| **Immutable Audit** | Append-only JSONL with SQLite index. No update or delete operations exist |
| **Intrusion Proof** | VaultWatcher detects filesystem events outside AetherCloud-L and signs them into the audit chain |
| **AI Verification** | Every Claude response is committed and verified before the system acts on it |
| **Session Binding** | All operations are bound to authenticated session tokens |
| **Temporal Proof** | RFC 3161 timestamps from trusted authorities prove entries existed at specific times |
| **Zero File Leakage** | File contents never leave the machine. Only filenames and paths are sent to Claude |
| **Lockout Protection** | 5 failed login attempts trigger 15-minute account lockout |
| **Password Security** | bcrypt with random salt per user |

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `anthropic` | Claude API client |
| `bcrypt` | Password hashing |
| `watchdog` | Filesystem event monitoring |
| `rich` | Terminal UI rendering |
| `textual` | TUI dashboard framework |
| `cryptography` | ECDSA and X.509 operations |
| `python-dotenv` | Environment configuration |
| `pyasn1` | ASN.1 parsing for RFC 3161 |
| `qiskit` | Quantum circuit construction |
| `qiskit-ibm-runtime` | IBM Quantum hardware access |
| `qiskit-aer` | Local quantum simulator |
| `pytest` | Test framework |

---

## Version History

| Version | Phase | Changes |
|---------|-------|---------|
| **0.1.0** | Phase 0 | Initial scaffold — auth, vault, agent, UI, 177 tests |
| **0.2.0** | Phase 1 | Claude API agent, VaultWatcher boot, Textual dashboard, 235 tests |
| **0.3.0** | Phase 2 | HardenedClaudeAgent — Protocol-L verified AI reasoning, 300 tests |
| **0.4.0** | Phase 3 | Electron desktop app — installer wizard, quantum login, vault node graph UI |

---

## License

Proprietary. All rights reserved.
*Aether Systems LLC — Patent Pending*
