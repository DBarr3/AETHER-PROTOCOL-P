⬡ AETHER PROTOCOL
Cryptographically Verified Short-Lived Identity Infrastructure for Autonomous AI Systems
Aether AI LLC · Patent Pending · US Application 64/006,746 · Filed March 16, 2026

"Every AI system in the world can be compromised by injecting false instructions into its pipeline. Aether Protocol makes that physically impossible."


The Problem
On February 25, 2026, Check Point Research disclosed CVE-2025-59536 — a critical vulnerability (CVSS 8.7) in Claude Code that allowed attackers to inject malicious instructions into .claude/settings.json configuration files, executing immediately upon a developer opening a project folder.
The root cause was not a bug in Claude's reasoning. It was the absence of a cryptographic authentication layer between AI instruction and execution.
This gap exists in every autonomous AI system deployed today. APIs, state stores, configuration files, message queues, and shared memory all carry AI instructions to execution layers with no authentication in between.
Anthropic's Frontier Safety Roadmap (February 2026) explicitly identifies "cryptographically verified short-lived identities" as a priority goal for April 2026.
The Aether Protocol is a working implementation of that goal.

The Solution: Ontological Root of Trust
Classical and post-quantum cryptography both rest on mathematical hardness — problems that are computationally difficult to solve. The security guarantee degrades as computing power scales.
The Aether Protocol rests on a different foundation entirely: physical non-determinism.
Each session, a quantum circuit executes on IBM Quantum hardware. The measurement outcomes arise from quantum vacuum fluctuations in superconducting qubits cooled to 15 millikelvin. These outcomes cannot be predicted before they occur — not by any algorithm, classical or quantum. This is not a computational limitation. It is a consequence of quantum mechanical non-determinism, confirmed by the violation of Bell inequalities.
A signing key derived from this outcome inherits the same property: it could not have been predicted before the measurement, and it did not exist before this session. Destroyed at session end — hours after creation — the key cannot be retroactively attacked. Shor's algorithm on the signing curve requires days of quantum computation. The key is gone before any attack could complete.
This is the Ontological Root of Trust: security grounded in physics, not mathematics.

How It Works
<img width="1332" height="711" alt="image" src="https://github.com/user-attachments/assets/645f8357-1c50-4634-a6dc-fd9018e6b956" />
The Protocol operates on a three-phase session model: initialization, operation, and destruction.
PhaseDescriptionInitializationIBM Quantum hardware executes a quantum entropy circuit. The physically unpredictable measurement outcome seeds an ephemeral asymmetric keypair held exclusively in volatile memory.OperationEvery AI decision is cryptographically signed before dispatch. Execution layers verify the signature before acting. Unsigned or tampered instructions are dropped before execution.DestructionThe private key is explicitly zeroed in memory at session end. No valid signatures for this session can be produced by any party after destruction.
Full architecture is documented in the white paper: docs/AETHER_PROTOCOL_WHITEPAPER.md
The white paper applies black box disclosure — architecture and results are shared openly. Implementation details are available under a Mutual Non-Disclosure Agreement.

Protocol Suite
Protocol-C — Commitment Infrastructure at Zero Cost
The Economics
IBM QPU time costs roughly $100/minute. At 10,000 users generating commitments, that translates to approximately $3,300/month for operations that do not require quantum entropy. Protocol-C eliminates that cost entirely by sourcing entropy from the OS kernel — same chain architecture, zero QPU overhead.
What It Guarantees
SHA-256 commitment chain. RFC 3161 trusted timestamps. Ephemeral key destruction after every signing operation. The output is computationally indistinguishable from quantum-seeded commitments — identical chain format, identical verification path.
Who Uses It
SaaS platforms, AI companies committing model outputs, and financial institutions operating at scale. A single environment variable switches any Protocol-C deployment to Protocol-L when quantum assurance becomes necessary.

Protocol-L — Cryptographic Accountability for Autonomous AI
The Lifecycle: Commit → Execute → Settle
Three independently signed phases. Each phase receives its own ephemeral secp256k1 key, seeded from a unique quantum measurement. A SHA-256 binding chain links the phases together — tampering with any phase invalidates the entire commitment.
Quantum Entropy Foundation
156-qubit IBM circuit (Fez). Quantum measurement is non-deterministic by physical law — no seed, no state, no replay. Ephemeral keys live approximately one hour, providing a 168× safety margin against Shor's algorithm at current qubit counts.
Dispute Resolution: Evidence, Not Logs
Exportable proof packages for regulators and counterparties. Structured for DORA, SEC, MiFID II, and FCA compliance frameworks. Every commitment is independently verifiable — no trust in the issuing party required.
COMMIT → EXECUTE → SETTLE · secp256k1 + RFC 6979 · RFC 3161 / DigiCert · Patent Filed

Protocol-T — Prove What Ran, Not Just What Was Signed
The Problem
There is a gap in every AI audit trail. Logs are circumstantial — they cannot prove which model version ran, whether the pipeline was intact, or if intermediate data was modified. Signatures prove intent, not execution context.
How Attestation Works
MRENCLAVE is the SHA-256 measurement of the exact binary loaded into the enclave. The enclave cannot be observed or modified by the host OS, hypervisor, or cloud provider. Attestation quotes are verifiable via Intel or AMD root certificates.
Who Needs It
Healthcare AI under HIPAA/FDA. Financial institutions governed by OCC/SEC. AI labs required to prove safety evaluations ran unmodified. Any confidential compute environment where execution integrity is non-negotiable.
Intel SGX / AMD SEV-SNP · MRENCLAVE Binding · Remote Attestation · 76 Tests

Proof: What Is Running Today
This is not theoretical. Two production systems are running the Protocol today.
AetherSecurity — Autonomous penetration testing platform integrating live IBM Quantum hardware for defense entropy, quantum-guided exploit search, and cryptographically signed agent decisions.
Aether Terminal (in development) — Trading platform with quantum middleware verifying every AI-generated trade decision before execution.

Security Properties
PropertyDescriptionP1 — Ontological Seed UnpredictabilityThe session seed cannot be predicted before measurement. No algorithm improves on random guessing over the quantum state space.P2 — Signature UnforgeabilityTwo simultaneous barriers: predict the quantum measurement (physically impossible) or recover the private key from the public key (computationally infeasible).P3 — Temporal Quantum SafetyKey lifetime is hours. The quantum attack that threatens classical cryptography requires days at minimum. The key is destroyed before any such attack could complete.P4 — Perfect Forward SecrecyEach session derives an independent keypair from an independent quantum measurement. Compromise of any session reveals nothing about any other.P5 — Tamper DetectionAny modification to a signed decision — a single bit — invalidates the signature and is detected before execution.

Aether Protocol vs. Post-Quantum Cryptography
PropertyPost-Quantum CryptographyAether ProtocolSecurity basisMathematical hardnessPhysical non-determinismDegrades with compute scaling?Slower — but yesNo — physics does not changeKey lifetimeMonths to yearsHours (one session)Quantum attack threatResistant (different problems)Irrelevant — key destroyed firstRoot of trustMathematicalOntological
PQC and the Aether Protocol are complementary — PQC hardens long-lived infrastructure keys; the Protocol authenticates individual AI decisions at the dispatch layer.

Verifiable Claims
The following can be independently verified without source code or an MNDA.

IBM Quantum workloads are real — job records on IBM Quantum hardware are visible in IBM's dashboard and verifiable by any IBM Quantum account holder
Signatures are verifiable without source code — signed decision objects contain everything needed for standard asymmetric signature verification
Patent is real — US Application 64/006,746, filed March 16, 2026, Confirmation #2009, verifiable through USPTO Patent Center


White Paper
Full technical specification: docs/AETHER_PROTOCOL_WHITEPAPER.md
Covers: CVE-2025-59536 attack analysis, Ontological Root of Trust, session lifecycle architecture, formal security properties (P1–P5), complete threat model (T1–T6), verifiable claims, Anthropic Frontier Safety Roadmap alignment, U-Score formal definition, and commercial applications.
Black box disclosure — architecture and results shared openly. Implementation details available under MNDA.

Roadmap
v1.0 — Live (March 2026)

IBM Quantum entropy circuit
Ephemeral asymmetric signer with zero external cryptographic dependencies
AetherSecurity: QuantumOracle, Scrambler, exploit search
Aether Terminal: quantum middleware live
U-Score engine — 43 sessions, R = 1.000
Patent filed: US Application 64/006,746

v1.1 — Near-Term

Higher qubit entropy circuit
Replay protection nonce registry
Federated Adversarial Intelligence (anonymized delta sharing)

v1.2 — Medium-Term

Trusted Execution Environment integration for host key protection
Enterprise deployment tooling
Claude Code integration proof of concept

v2.0 — Long-Term

IBM Quantum fault-tolerant logical qubits (2029+)
Post-quantum backup layer
Multi-party quantum signing


Patent
Application:    64/006,746
Confirmation:   2009
Filed:          March 16, 2026 — 11:51:11 AM ET
Inventor:       Brandon Barrante
Assignee:       Aether Systems LLC
Title:          Quantum-Seeded Ephemeral Cryptographic Signing
                for Authenticated Artificial Intelligence Decision Dispatch
Type:           Utility Provisional — 35 U.S.C. § 111(b)

Contact
Aether AI LLC
Brandon Barrante, Founder
Bradenton, Florida, USA
aetherterminals.carrd.co · aethersystems.net
Research collaboration, licensing inquiries, and demonstration requests are welcome. Implementation details are available under MNDA.

License
Proprietary and Confidential. © 2026 Aether AI LLC. All Rights Reserved.
This repository contains trade secrets of Aether AI LLC protected under applicable trade secret law and US Provisional Patent Application 64/006,746. The white paper is shared under black box disclosure for research evaluation purposes. Source code is not included in this repository and is available only under a signed Mutual Non-Disclosure Agreement.

<p align="center">
  <strong>PATENT PENDING · AETHER AI LLC · © 2026</strong><br>
  <em>Cryptographically verified short-lived identities for autonomous AI systems.<br>
  Grounded in physics. Not mathematics.</em>
</p>
