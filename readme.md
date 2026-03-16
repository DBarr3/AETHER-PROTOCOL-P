# AETHER PROTOCOL

**Cryptographically Verified Short-Lived Identity Infrastructure for Autonomous AI Systems**

*Patent Pending — US Application 64/006,746 — Filed March 16, 2026*

> *"Every AI system in the world can be compromised by injecting false instructions into its pipeline. Aether Protocol makes that physically impossible."*

---

## The Problem

On February 25, 2026, Check Point Research disclosed CVE-2025-59536 — a critical vulnerability (CVSS 8.7) in Claude Code that allowed attackers to inject malicious instructions into `.claude/settings.json` configuration files that executed immediately upon a developer opening a project folder.

The root cause was not a bug in Claude's reasoning. It was the absence of a cryptographic authentication layer between AI instruction and execution.

This gap — between what an AI decides and what gets executed — exists in every autonomous AI system deployed today. APIs, state stores, configuration files, message queues, shared memory — all of them carry AI instructions to execution layers with no authentication in between.

Anthropic's Frontier Safety Roadmap (February 2026) explicitly identifies **"cryptographically verified short-lived identities"** as a priority goal for April 2026.

The Aether Protocol is a working implementation of that goal.

---

## The Solution: Ontological Root of Trust

Classical and post-quantum cryptography both rest on mathematical hardness — problems that are computationally difficult to solve. The security guarantee degrades as computing power scales.

The Aether Protocol rests on a different foundation entirely: **physical non-determinism**.

Each session, a quantum circuit executes on IBM Quantum hardware. The measurement outcomes arise from quantum vacuum fluctuations in superconducting qubits cooled to 15 millikelvin. These outcomes cannot be predicted before they occur — not by any algorithm, classical or quantum. This is not a computational limitation. It is a consequence of quantum mechanical non-determinism, confirmed by the violation of Bell inequalities.

A signing key derived from this outcome inherits the same property: it could not have been predicted before the measurement, and it did not exist before this session.

Destroyed at session end — hours after creation — the key cannot be retroactively attacked. Shor's algorithm on the signing curve requires days of quantum computation. The key is gone before any attack could complete.

This is the **Ontological Root of Trust**: security grounded in physics, not mathematics.

---

## How It Works

```
## How It Works

The Protocol operates on a three-phase session model:
initialization, operation, and destruction.

Full architecture is documented in the white paper:
[`docs/AETHER_PROTOCOL_WHITEPAPER.md`](docs/AETHER_PROTOCOL_WHITEPAPER.md)

The white paper applies black box disclosure — architecture
and results are shared openly. Implementation details are
available under a Mutual Non-Disclosure Agreement.
```

**Application to CVE-2025-59536:**


| Attacker injects malicious hook | Hook written to `.claude/settings.json` | N/A |
| Claude Code initializes | Hook executes automatically | `verify_decision()` called first |
| Verification | None | ECDSA signature checked |
| Outcome | Arbitrary shell execution | Unsigned instruction dropped |
| Attacker's path around this | — | Forge ECDSA without key (infeasible) or predict IBM measurement (physically impossible) |

---

## Proof: What Is Running Today

This is not theoretical. Two production systems are running the Protocol today.

### AetherSecurity
Autonomous penetration testing platform with:
- IBM Quantum ibm_fez 30-qubit entropy circuit
- QuantumOracle signing every approved agent decision
- QOPC exploit search over 1.1 trillion configurations
- Barcode Quantum Defense Scrambler — 5 mutation types

### Aether Terminal
Institutional-grade trading platform with:
- Redux quantum middleware verifying every AI trade decision
- Feature flag `ENABLE_QUANTUM_SIGNED_DISPATCH = True` live
- Qwen + Claude hybrid AI decision engine

### Live Statistics (March 16, 2026)

```
═══════════════════════════════════════════════════════════
  U-SCORE    27.2 / 100  ↑  [ACTIVE]
═══════════════════════════════════════════════════════════
  Q  Quantum Entropy    0.123   ibm_fez — live hardware
  S  Session Depth      0.548   43 sessions accumulated
  D  Mutation Diversity 0.200   Defense rotations active
  R  Resilience         1.000   3,371 probes / 0 breaches
  A  Attack Coverage    0.111   Categories defended
═══════════════════════════════════════════════════════════
```

**R = 1.000**: 3,371 probe attempts across 43 sessions. Zero breaches. Zero vulnerabilities confirmed.

Combined test coverage: **3,705 passing tests** across both systems.

---

## The U-Score: Deployment Maturity

The Unlearnability Score measures the demonstrated difficulty of attacking a specific deployment given its documented operational history.

```
U = 5th-root(Q × S × D × R × A) × 100
```

| Level | Range | Characteristic |
|---|---|---|
| Nascent | 0–20 | Quantum entropy active, no operational history |
| **Active** | **20–40** | **Real adversarial pressure absorbed — current deployment** |
| Mature | 40–60 | Broad attack category coverage proven |
| Hardened | 60–80 | Demonstrated resilience across all dimensions |
| Sovereign | 80–100 | Maximum documented immunity |

A system built from scratch today starts at **Nascent (0)**. This deployment is at **Active (27.2)** with 43 sessions of documented adversarial history that cannot be simulated or recreated — only earned.

---

## Security Properties

**P1 — Ontological Seed Unpredictability**
The quantum seed cannot be predicted before the session. No algorithm improves on random guessing over 2^n states.

**P2 — Signature Unforgeability**
Predict the quantum measurement (physically impossible) or solve ECDLP (computationally infeasible). Both barriers must fall simultaneously.

**P3 — Temporal Quantum Safety**
Key lifetime: hours. Shor's attack time: days minimum. Key destroyed before any quantum attack completes.

**P4 — Perfect Forward Secrecy**
Each session: independent quantum measurement, independent keypair. Compromise of any session reveals nothing about any other.

**P5 — Tamper Detection**
Any modification to a signed decision — a single bit — invalidates the signature. Detected before execution.

---

## vs. Post-Quantum Cryptography

| Property | Post-Quantum Crypto | Aether Protocol |
|---|---|---|
| Security basis | Mathematical hardness (harder problems) | Physical non-determinism |
| Degrades with compute scaling? | Slower — but yes | No — physics does not change |
| Key lifetime | Months to years | Hours (one session) |
| Shor's algorithm threat | Resistant (different problems) | Irrelevant — key destroyed first |
| Root of trust | Mathematical | **Ontological** |

PQC and the Aether Protocol are complementary — PQC hardens long-lived infrastructure keys, the Protocol authenticates individual AI decisions at the dispatch layer. The Protocol's v2.0 roadmap includes CRYSTALS-Dilithium as a backup layer.

---

## Verifiable Claims

These can be independently verified without source code or an MNDA:

- **IBM Quantum workloads are real** — job records on ibm_fez and ibm_torino visible in IBM's dashboard
- **Signatures are verifiable without source code** — session public key + signed decision objects contain everything needed for standard ECDSA verification
- **Patent is real** — US Application 64/006,746, filed March 16, 2026, Confirmation #2009, verifiable through USPTO Patent Center

---

## White Paper

Full technical specification: [`docs/AETHER_PROTOCOL_WHITEPAPER.md`](docs/AETHER_PROTOCOL_WHITEPAPER.md)

Covers: CVE-2025-59536 attack analysis, Ontological Root of Trust, session lifecycle, formal security properties, complete threat model, verifiable claims, Frontier Safety Roadmap alignment, U-Score formal definition, and commercial applications.

Black box disclosure — architecture and results shared openly. Implementation details available under MNDA.

---

## Roadmap

**v1.0 — Live (March 2026)**
- IBM Quantum entropy circuit (20-30 qubits)
- Ephemeral asymmetric signer — zero external cryptographic dependencies
- AetherSecurity: QuantumOracle, Scrambler, QOPC
- Aether Terminal: Redux quantum middleware live
- U-Score engine — 43 sessions, R = 1.000
- Patent filed: US Application 64/006,746

**v1.1 — Near-term**
- 30-qubit entropy circuit (1,073,741,824 states)
- Nonce registry for replay protection
- Federated Adversarial Intelligence (anonymized delta sharing)

**v1.2 — Medium-term**
- TEE integration (Intel SGX) for host key protection
- Claude Code integration proof of concept
- Enterprise deployment tooling

**v2.0 — Long-term**
- IBM Quantum fault-tolerant logical qubits (2029+)
- CRYSTALS-Dilithium backup layer
- Multi-party quantum signing

---

## Patent

```
Application:    64/006,746
Confirmation:   2009
Filed:          March 16, 2026 — 11:51:11 AM ET
Inventor:       Brandon Barrante
Assignee:       Aether Systems LLC
Title:          Quantum-Seeded Ephemeral Cryptographic Signing
                for Authenticated Artificial Intelligence
                Decision Dispatch
Type:           Utility Provisional — 35 U.S.C. § 111(b)
```

---

## Contact

**Aether Systems LLC**
Brandon Barrante, Founder
Bradenton, Florida, USA
aetherterminals.carrd.co

Research collaboration, licensing inquiries, and demonstration requests welcome. Implementation details available under MNDA.

---

## License

Proprietary and Confidential. © 2026 Aether Systems LLC. All Rights Reserved.

Trade secrets protected under applicable law and US Provisional Patent Application 64/006,746. White paper shared under black box disclosure for research evaluation. Source code not included — available under signed MNDA only.

*Patent Pending — US Application 64/006,746*

---

<p align="center">
<strong>PATENT PENDING — AETHER SYSTEMS LLC — © 2026</strong><br>
<em>Cryptographically verified short-lived identities for autonomous AI systems.<br>
Grounded in physics. Not mathematics.</em>
</p>
