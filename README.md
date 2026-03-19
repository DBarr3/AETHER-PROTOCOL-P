# AetherCloud-L

**Quantum-Secured AI File Intelligence System**
*Powered by Aether Protocol-L*

---

## What is AetherCloud-L?

A quantum-secured personal file intelligence system that combines:

- **AI File Agent** — Understands file intent, suggests organization, answers natural language queries about your vault
- **Aether Protocol-L** — SHA-256 + quantum commitment layer on every file access event
- **Tamper-Proof Audit Trail** — Every login, file touch, rename, and access is cryptographically timestamped and signed
- **Hacker Detection** — Real-time file system monitoring detects unauthorized access with signed proof
- **Local AI** — Uses Ollama/Qwen locally — no file data ever leaves your machine

## Architecture

```
AetherCloud-L/
├── aether_protocol/   ← Protocol-L (unchanged)
├── auth/              ← Login, sessions, MFA
├── agent/             ← AI file agent + organizer
├── vault/             ← File directory + watcher
├── ui/                ← Terminal interface
├── tests/             ← Full test suite
├── config/            ← Settings and constants
└── main.py            ← Entry point
```

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

## Commands

| Command | Description |
|---------|-------------|
| `login` | Authenticate |
| `ls [path]` | List files |
| `audit [path]` | Show audit trail |
| `organize [--dry-run]` | Run AI organization |
| `chat "<query>"` | Ask the agent |
| `rename <file>` | Get AI name suggestion |
| `move <file> <dest>` | Move with audit log |
| `status` | Vault stats + Protocol-L status |
| `logout` | End session |
| `help` | Show commands |

## Stack

- **Protocol-L**: SHA-256 + quantum commitment layer
- **Ollama/Qwen**: Local AI file analysis
- **Watchdog**: Unauthorized access detection
- **Rich**: Terminal UI
- **bcrypt**: Password hashing

---

*Aether Systems LLC — Patent Pending*
