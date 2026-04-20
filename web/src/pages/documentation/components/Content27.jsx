"use client";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@relume_io/relume-ui";
import React, { Fragment } from "react";

export function Content27() {
  return (
    <section id="relume" className="px-[5%] py-16 md:py-24 lg:py-28">
      <div className="container">
        <div className="grid grid-cols-1 gap-y-8 lg:grid-cols-[20rem_1fr] lg:gap-x-16 xxl:gap-x-48">
          <div>
            <div className="lg:sticky lg:top-24">
              <Accordion
                type="single"
                defaultValue="aside-menu"
                className="lg:block"
                collapsible={true}
              >
                <AccordionItem value="aside-menu" className="border-none">
                  <AccordionTrigger className="flex cursor-pointer items-center justify-between gap-3 border border-border-primary px-4 py-3 lg:pointer-events-none lg:cursor-auto lg:border-none lg:p-0 [&_svg]:size-4 [&_svg]:lg:hidden">
                    <h3 className="text-lg font-bold leading-[1.4] md:text-2xl">
                      Table of contents
                    </h3>
                  </AccordionTrigger>
                  <AccordionContent className="pb-0">
                    <div className="mt-3 md:mt-4">
                      <a
                        href="#quickstart"
                        className="block px-4 py-3 md:text-md"
                        style={{ marginLeft: 0 }}
                      >
                        Quickstart
                      </a>
                      <a
                        href="#architecture"
                        className="block px-4 py-3 md:text-md"
                        style={{ marginLeft: 0 }}
                      >
                        Architecture
                      </a>
                      <a
                        href="#ghost-protocol"
                        className="block px-4 py-3 md:text-md"
                        style={{ marginLeft: "16px" }}
                      >
                        Ghost Protocol
                      </a>
                      <a
                        href="#scrambler-protocol"
                        className="block px-4 py-3 md:text-md"
                        style={{ marginLeft: "16px" }}
                      >
                        Scrambler Protocol
                      </a>
                      <a
                        href="#predator-protocol"
                        className="block px-4 py-3 md:text-md"
                        style={{ marginLeft: "16px" }}
                      >
                        Predator Protocol
                      </a>
                      <a
                        href="#attestation"
                        className="block px-4 py-3 md:text-md"
                        style={{ marginLeft: 0 }}
                      >
                        Attestation
                      </a>
                      <a
                        href="#commitment-ledger"
                        className="block px-4 py-3 md:text-md"
                        style={{ marginLeft: 0 }}
                      >
                        Commitment Ledger
                      </a>
                      <a
                        href="#integration"
                        className="block px-4 py-3 md:text-md"
                        style={{ marginLeft: 0 }}
                      >
                        Integration
                      </a>
                      <a
                        href="#cli-reference"
                        className="block px-4 py-3 md:text-md"
                        style={{ marginLeft: 0 }}
                      >
                        CLI Reference
                      </a>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            </div>
          </div>
          <div className="max-w-lg">
            <div className="prose md:prose-md lg:prose-lg">
              <Fragment>
                {/* ── QUICKSTART ── */}
                <h2 id="quickstart">Quickstart</h2>
                <p>
                  <strong>
                    Get your first endpoint rotation running in under five
                    minutes. The aetherctl CLI bootstraps your node identity,
                    connects to the coordination mesh, and performs an initial
                    Ghost rotation automatically.
                  </strong>
                </p>
                <p>
                  Install the CLI from our signed package registry. Binaries are
                  available for Linux (amd64, arm64), macOS (Apple Silicon and
                  Intel), and Windows (x64).
                </p>
                <pre>
                  <code>{`# Install aetherctl
curl -fsSL https://get.aethersystems.net | sh

# Authenticate and bootstrap node identity
aetherctl init --org <YOUR_ORG_ID> --token <API_TOKEN>

# Run your first rotation
aetherctl rotate --protocol ghost --cadence 30s

# Verify the rotation receipt
aetherctl verify --last`}</code>
                </pre>
                <p>
                  The <code>init</code> command generates a node keypair, stores
                  it in the local secure enclave (TPM 2.0 on Linux, Secure
                  Enclave on macOS, Windows Hello on Windows), and registers the
                  node with your organization's coordination mesh. The first
                  rotation happens within one cadence interval.
                </p>

                {/* ── ARCHITECTURE ── */}
                <h2 id="architecture">Architecture</h2>
                <p>
                  <strong>
                    Aether Security implements a three-layer moving target
                    defense architecture. Each layer operates independently but
                    shares entropy and coordination signals through the mesh.
                  </strong>
                </p>
                <p>
                  The architecture is designed around three core rotation
                  protocols that work in concert:
                </p>
                <ul>
                  <li>
                    <strong>Layer 1 — Ghost Protocol:</strong> Rotates endpoint
                    identifiers (IP addresses, DNS records, TLS certificates,
                    service ports) on configurable cadences from 10 seconds to 24
                    hours. Authorized peers receive rotation schedules via
                    encrypted broadcast channels.
                  </li>
                  <li>
                    <strong>Layer 2 — Scrambler Protocol:</strong> Rewrites
                    network topology in real-time. Path randomization ensures no
                    two consecutive requests traverse the same route through the
                    mesh. Topology state is held in ephemeral memory only.
                  </li>
                  <li>
                    <strong>Layer 3 — Predator Protocol:</strong> Active threat
                    hunting layer that detects adversary reconnaissance patterns
                    and triggers counter-rotations. When an attacker maps one
                    endpoint, Predator invalidates the mapping and initiates
                    trace-back operations.
                  </li>
                </ul>
                <p>
                  All three layers share a quantum-seeded entropy source (QRNG)
                  that feeds rotation decisions. Entropy is harvested from
                  quantum-tap hardware modules deployed at coordination nodes and
                  distributed via the attestation subsystem.
                </p>

                {/* ── GHOST PROTOCOL ── */}
                <h3 id="ghost-protocol">Ghost Protocol</h3>
                <p>
                  Ghost is the foundational rotation layer. It manages the
                  lifecycle of endpoint identifiers — creating, publishing,
                  rotating, and revoking the addresses through which your
                  services are reachable.
                </p>
                <p>
                  <strong>Rotation Semantics.</strong> Each rotation event
                  generates a new endpoint tuple{" "}
                  <code>(IP, port, TLS fingerprint, DNS label)</code>. The
                  outgoing tuple remains valid for a configurable overlap window
                  (default: 2x cadence) to allow in-flight connections to drain.
                  The new tuple is broadcast to authorized peers before it
                  becomes the primary, ensuring zero-downtime transitions.
                </p>
                <p>
                  <strong>Cadence Configuration.</strong> Cadences are set per
                  service or globally via policy. Supported cadence values range
                  from <code>10s</code> to <code>24h</code>. Higher-security
                  services typically use 30-second cadences; internal services
                  may use 5-minute or longer intervals.
                </p>
                <pre>
                  <code>{`# Set cadence per service
aetherctl ghost set-cadence --service api-gateway --interval 30s
aetherctl ghost set-cadence --service internal-db --interval 5m

# Set global default cadence
aetherctl ghost set-cadence --global --interval 60s

# View current rotation schedule
aetherctl ghost schedule --output table`}</code>
                </pre>
                <p>
                  <strong>Peer Broadcasting.</strong> Authorized peers subscribe
                  to rotation channels keyed by service identity. When a
                  rotation fires, the new endpoint tuple is encrypted with each
                  subscriber's public key and pushed via the coordination mesh.
                  Peers that miss a broadcast can request the current tuple using
                  a challenge-response handshake.
                </p>

                {/* ── SCRAMBLER PROTOCOL ── */}
                <h3 id="scrambler-protocol">Scrambler Protocol</h3>
                <p>
                  Scrambler operates at the network topology layer, ensuring
                  that traffic paths through the Aether mesh are non-repeating
                  and unpredictable. Even if an adversary compromises a single
                  relay node, they cannot reconstruct the full path of any
                  request.
                </p>
                <p>
                  <strong>Topology Rewriting.</strong> The mesh maintains a
                  real-time graph of available relay nodes. On each routing
                  decision, Scrambler selects a path using a weighted random walk
                  seeded by QRNG entropy. Path weights factor in latency, node
                  trust score, and recency of use — recently used paths are
                  penalized to prevent repetition.
                </p>
                <p>
                  <strong>Path Randomization.</strong> Every connection between
                  two endpoints is routed through 3-7 relay hops (configurable
                  via <code>scrambler.min_hops</code> and{" "}
                  <code>scrambler.max_hops</code>). No relay node sees both the
                  true source and true destination. Each hop uses a fresh
                  ephemeral key negotiated via X25519.
                </p>
                <pre>
                  <code>{`# Configure hop range
aetherctl scrambler config --min-hops 3 --max-hops 7

# View current mesh topology stats
aetherctl scrambler topology --format json

# Force immediate topology reshuffle
aetherctl scrambler reshuffle --reason "incident-response"`}</code>
                </pre>
                <p>
                  <strong>Mesh Restructuring.</strong> The Scrambler
                  periodically restructures the mesh graph itself — adding
                  decoy nodes, removing stale relays, and rebalancing capacity.
                  Restructuring events are coordinated across the mesh and
                  logged to the commitment ledger for audit purposes.
                </p>

                {/* ── PREDATOR PROTOCOL ── */}
                <h3 id="predator-protocol">Predator Protocol</h3>
                <p>
                  Predator is the active defense layer. While Ghost and
                  Scrambler make your infrastructure a moving target, Predator
                  detects when an adversary is attempting to track that movement
                  and responds with counter-measures.
                </p>
                <p>
                  <strong>Adversary Hunting.</strong> Predator analyzes
                  connection patterns across the mesh to identify reconnaissance
                  signatures: port scanning sequences, DNS enumeration patterns,
                  certificate transparency log monitoring, and timing correlation
                  attacks. Detection models are updated continuously from
                  Aether's threat intelligence feed.
                </p>
                <p>
                  <strong>Counter-Rotation.</strong> When Predator detects an
                  active adversary, it triggers an immediate out-of-cadence
                  rotation on the targeted endpoints. This invalidates any
                  mapping the attacker has built. Counter-rotations are cascading
                  — if Service A is targeted, dependent services B and C rotate
                  simultaneously to prevent lateral pivoting.
                </p>
                <pre>
                  <code>{`# View active threat detections
aetherctl predator threats --status active

# Manually trigger counter-rotation
aetherctl predator counter-rotate --target api-gateway --cascade

# Enable trace-back on a detection
aetherctl predator traceback --detection-id DET-2024-0847 --depth 5

# Export threat report
aetherctl predator report --format pdf --last 24h`}</code>
                </pre>
                <p>
                  <strong>Trace-Back Operations.</strong> For high-confidence
                  detections, Predator can initiate trace-back — a controlled
                  operation that follows the adversary's connection chain back
                  through relay nodes to identify the true origin. Trace-back
                  operates passively by correlating timing data across mesh nodes
                  and does not involve any active probing of external systems.
                </p>

                {/* ── ATTESTATION ── */}
                <h2 id="attestation">Attestation</h2>
                <p>
                  <strong>
                    Every rotation event, topology change, and threat detection
                    is cryptographically attested. Attestation receipts provide
                    non-repudiable proof of what happened, when, and which nodes
                    were involved.
                  </strong>
                </p>
                <p>
                  <strong>Hardware-Backed Signing.</strong> Attestation keys are
                  generated and stored in hardware security modules (HSMs) at
                  coordination nodes or in local TPM/Secure Enclave on edge
                  nodes. Private keys never leave the hardware boundary.
                  Signatures use Ed25519 with a deterministic nonce derived from
                  the QRNG entropy pool.
                </p>
                <p>
                  <strong>Quantum-Tap Entropy Source.</strong> Rotation decisions
                  must be unpredictable to be secure. The QRNG hardware modules
                  at coordination nodes harvest entropy from quantum vacuum
                  fluctuations, producing a minimum of 256 Kbit/s of certified
                  random data. This entropy seeds all rotation schedules, path
                  selections, and nonce generation across the mesh.
                </p>
                <p>
                  <strong>Receipt Format.</strong> Each attestation receipt is a
                  CBOR-encoded structure containing the event type, timestamp
                  (nanosecond precision, NTP-synchronized), the node identity of
                  the signer, the rotation parameters, and the Ed25519 signature.
                  Receipts are approximately 340 bytes and can be independently
                  verified without contacting Aether's infrastructure.
                </p>
                <pre>
                  <code>{`# Verify a specific receipt
aetherctl verify --receipt-id REC-20240315-a8f3e2

# Dump receipt contents
aetherctl verify --receipt-id REC-20240315-a8f3e2 --decode

# Batch verify all receipts in a time range
aetherctl verify --from 2024-03-01T00:00:00Z --to 2024-03-15T23:59:59Z

# Export receipts for external audit
aetherctl export receipts --format cbor --output ./audit-bundle/`}</code>
                </pre>

                {/* ── COMMITMENT LEDGER ── */}
                <h2 id="commitment-ledger">Commitment Ledger</h2>
                <p>
                  <strong>
                    The commitment ledger aggregates attestation receipts into
                    tamper-evident daily digests using a Merkle tree structure.
                    Digests are anchored to public timestamping services for
                    independent verifiability.
                  </strong>
                </p>
                <p>
                  <strong>Merkle-Anchored Daily Digests.</strong> At 00:00 UTC
                  each day, all attestation receipts from the previous 24 hours
                  are organized into a Merkle tree. The root hash is signed by
                  the coordination node's HSM and submitted to two independent
                  public timestamping authorities (RFC 3161). The signed root,
                  along with the timestamp response, forms the daily digest.
                </p>
                <p>
                  <strong>Audit Export.</strong> Auditors can request a complete
                  export of the commitment ledger for any date range. The export
                  includes the Merkle tree, all constituent receipts, and the
                  timestamp authority responses. Verification requires only the
                  public keys of your organization's coordination nodes and the
                  timestamp authorities' certificates.
                </p>
                <pre>
                  <code>{`# Export ledger for audit
aetherctl ledger export --from 2024-01-01 --to 2024-03-31 \\
  --format json --output ./q1-audit/

# Verify ledger integrity
aetherctl ledger verify --path ./q1-audit/

# Generate compliance report
aetherctl ledger compliance --framework nist-800-53 --output report.pdf`}</code>
                </pre>
                <p>
                  <strong>Compliance Mapping.</strong> The ledger supports
                  automated compliance mapping to NIST 800-53, ISO 27001, SOC 2
                  Type II, and PCI DSS v4.0. Each rotation event maps to
                  specific control objectives — for example, Ghost rotations
                  satisfy SC-28 (Protection of Information at Rest) and SC-8
                  (Transmission Confidentiality), while Predator detections map
                  to SI-4 (System Monitoring) and IR-4 (Incident Handling).
                </p>

                {/* ── INTEGRATION ── */}
                <h2 id="integration">Integration</h2>
                <p>
                  <strong>
                    Aether Security integrates into existing infrastructure
                    through REST APIs, gRPC services, a Kubernetes operator, and
                    a Terraform provider. Choose the integration path that
                    matches your deployment model.
                  </strong>
                </p>
                <p>
                  <strong>REST API.</strong> The Aether REST API exposes all
                  rotation, attestation, and ledger operations over HTTPS. Base
                  URL: <code>https://api.aethersystems.net/v2</code>.
                  Authentication uses short-lived JWT tokens obtained via OAuth
                  2.0 client credentials flow. Rate limits: 1,000 requests/min
                  for rotation operations, 100 requests/min for ledger queries.
                </p>
                <p>
                  <strong>gRPC.</strong> For high-throughput integrations, the
                  gRPC interface supports streaming rotation events and
                  bidirectional peer coordination. Proto definitions are
                  published at{" "}
                  <code>
                    buf.build/aethersecurity/aether-proto
                  </code>
                  . The gRPC interface supports mTLS with automatic certificate
                  rotation (managed by Ghost).
                </p>
                <p>
                  <strong>Kubernetes Operator.</strong> The{" "}
                  <code>aether-operator</code> manages rotation policies as
                  Custom Resources. Install via Helm:
                </p>
                <pre>
                  <code>{`helm repo add aether https://charts.aethersystems.net
helm install aether-operator aether/aether-operator \\
  --namespace aether-system --create-namespace \\
  --set auth.token=<API_TOKEN>

# Apply a rotation policy
kubectl apply -f - <<EOF
apiVersion: aether.security/v1alpha1
kind: RotationPolicy
metadata:
  name: api-gateway-ghost
spec:
  protocol: ghost
  cadence: 30s
  targets:
    - kind: Service
      name: api-gateway
  overlap: 60s
EOF`}</code>
                </pre>
                <p>
                  <strong>Terraform Provider.</strong> The{" "}
                  <code>aether/aethersecurity</code> Terraform provider manages
                  rotation policies, mesh membership, and attestation
                  configuration as infrastructure-as-code. Published on the
                  Terraform Registry.
                </p>
                <pre>
                  <code>{`terraform {
  required_providers {
    aether = {
      source  = "aether/aethersecurity"
      version = "~> 2.4"
    }
  }
}

resource "aether_rotation_policy" "api" {
  name     = "api-gateway-ghost"
  protocol = "ghost"
  cadence  = "30s"
  overlap  = "60s"
  targets  = ["service:api-gateway"]
}`}</code>
                </pre>

                {/* ── CLI REFERENCE ── */}
                <h2 id="cli-reference">CLI Reference</h2>
                <p>
                  <strong>
                    The aetherctl CLI is the primary interface for managing
                    Aether Security deployments. All commands support{" "}
                    <code>--output json</code> for machine-readable output and{" "}
                    <code>--verbose</code> for debug logging.
                  </strong>
                </p>
                <p>
                  <strong>
                    <code>aetherctl rotate</code>
                  </strong>{" "}
                  — Trigger an immediate rotation on one or more services. Use{" "}
                  <code>--protocol</code> to specify Ghost, Scrambler, or
                  Predator (or <code>all</code> for a full-stack rotation).
                  The <code>--cascade</code> flag rotates dependent services
                  simultaneously.
                </p>
                <pre>
                  <code>{`aetherctl rotate --protocol ghost --service api-gateway
aetherctl rotate --protocol all --cascade`}</code>
                </pre>
                <p>
                  <strong>
                    <code>aetherctl verify</code>
                  </strong>{" "}
                  — Verify one or more attestation receipts. Supports individual
                  receipt IDs, time ranges, and batch verification against the
                  commitment ledger.
                </p>
                <pre>
                  <code>{`aetherctl verify --last
aetherctl verify --receipt-id REC-20240315-a8f3e2
aetherctl verify --from 2024-03-01 --to 2024-03-15`}</code>
                </pre>
                <p>
                  <strong>
                    <code>aetherctl proof</code>
                  </strong>{" "}
                  — Generate a Merkle inclusion proof for a specific receipt
                  within a daily digest. Useful for providing targeted audit
                  evidence without exporting the full ledger.
                </p>
                <pre>
                  <code>{`aetherctl proof --receipt-id REC-20240315-a8f3e2 --output proof.json`}</code>
                </pre>
                <p>
                  <strong>
                    <code>aetherctl export</code>
                  </strong>{" "}
                  — Export receipts, ledger digests, or compliance reports. Formats
                  include JSON, CBOR, CSV, and PDF.
                </p>
                <pre>
                  <code>{`aetherctl export receipts --format json --from 2024-Q1
aetherctl export ledger --format cbor --output ./audit/
aetherctl export compliance --framework soc2 --output report.pdf`}</code>
                </pre>
                <p>
                  <strong>
                    <code>aetherctl status</code>
                  </strong>{" "}
                  — Display the current state of the local node, active rotation
                  policies, mesh connectivity, and any active Predator detections.
                </p>
                <pre>
                  <code>{`aetherctl status
aetherctl status --service api-gateway
aetherctl status --mesh --format table`}</code>
                </pre>
              </Fragment>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
