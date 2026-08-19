# Aether Protocol — White Paper Index

**Cryptographically Verified Short-Lived Identity Infrastructure for Autonomous AI Systems**

*Aether AI · 2026 · Patent Pending — US Application 64/006,746*

This document applies **black-box disclosure**: the problem, architecture, and guarantees are public; implementation details for the quantum and attestation variants are available under a Mutual Non-Disclosure Agreement. The fully open variant — Protocol-C — has a complete, public technical white paper, linked below.

---

## The problem

On disclosure by Check Point Research, **CVE-2025-59536** (CVSS 8.7) allowed attacker-authored project configuration to execute arbitrary commands and exfiltrate credentials in Claude Code. Anthropic patched the specific defect in 1.0.111. The patch closed that door, not the class of door: the root cause was the **absence of a cryptographic authentication boundary between an AI instruction and its execution** — a gap present across config files, tool/MCP calls, message queues, and shared state in nearly every autonomous AI deployment. Anthropic's Frontier Safety roadmap names *"cryptographically verified short-lived identities"* as a priority. The Aether Protocol implements that layer.

## The three variants

| Variant | Entropy / root of trust | Status | Use it for |
|---|---|---|---|
| **Protocol-C** | OS CSPRNG (`secrets`) — classical, temporal safety margin | **Open source (Apache-2.0)** | Free commitment/authentication at any scale; the available CVE-class mitigation |
| **Protocol-L** | IBM Quantum hardware measurement (physical non-determinism) | Private — MNDA | High-assurance, regulator-facing accountability |
| **Protocol-T** | Trusted-execution attestation (SGX / SEV-SNP MRENCLAVE) | Private — MNDA | Proving *what ran*, not just what was signed |

All three share one commitment/verification model: an ephemeral key per decision, destroyed immediately after a single signature, producing an independently verifiable, tamper-evident record. Protocol-C and Protocol-L are chain-compatible — one environment variable switches the entropy source without changing the verification path.

## Read the open white paper

The complete, public technical white paper for the open-source variant:

→ **[Protocol-C: A Free, Auditable Authentication Layer for AI Decisions](PROTOCOL-C-WHITEPAPER.md)**

It covers the CVE-2025-59536 framing, the commit→sign-once→destroy design, the security properties (P1–P5), the economics of $0 entropy, and an explicit, honest statement of scope: Protocol-C is classical cryptography with a *temporal* safety margin — not post-quantum, not quantum-sourced.

- **Source + CLI:** [github.com/AetherAI3/PROTOCOL-C](https://github.com/AetherAI3/PROTOCOL-C) · `pip install git+https://github.com/AetherAI3/PROTOCOL-C.git` (not yet on PyPI)
- **Protocol-L / Protocol-T** architecture beyond the public summaries above is available under MNDA.

---

*Aether AI · [aethersystems.net](https://aethersystems.net)*
