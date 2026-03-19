"""
AETHER-PROTOCOL-L: Quantum-First Trade Auditability Protocol

Cryptographic protocol layer providing immutable, quantum-safe, dispute-proof
audit trails for trade decisions, executions, and settlements.

Every trade phase uses an independent quantum seed to derive an ephemeral key
that is destroyed immediately after signing -- providing perfect forward
secrecy and temporal safety against Shor's algorithm.

Public API:
    QuantumSeedCommitment    -- Immutable proof of a quantum measurement
    QuantumEphemeralKey      -- Ephemeral key with documented lifetime
    AccountSnapshot          -- Immutable account state snapshot
    QuantumStateSnapshot     -- Account state + quantum context
    QuantumDecisionCommitment       -- Trade decision bound to quantum seed + state
    QuantumCommitmentVerifier       -- Verify commitment signatures + quantum binding
    ExecutionResult          -- Trade execution result
    QuantumExecutionAttestation     -- Execution linked to commitment via chain
    QuantumExecutionVerifier        -- Verify execution attestations
    QuantumSettlementRecord         -- Final settlement sealed with 3rd quantum seed
    QuantumSettlementVerifier       -- Verify settlement chain + seed independence
    AuditLog                 -- Append-only JSONL audit log with quantum proofs
    AuditEntry               -- Single audit log entry
    AuditVerifier            -- Verify complete trade flows (quantum-aware)
    DisputeProofGenerator    -- Generate exportable dispute proofs
"""

from .quantum_crypto import (
    QuantumSeedCommitment,
    QuantumEphemeralKey,
    get_quantum_seed,
    verify_signature,
)
from .state import AccountSnapshot, QuantumStateSnapshot
from .commitment import QuantumDecisionCommitment, QuantumCommitmentVerifier, ReasoningCapture
from .execution import ExecutionResult, QuantumExecutionAttestation, QuantumExecutionVerifier
from .settlement import QuantumSettlementRecord, QuantumSettlementVerifier
from .audit import AuditLog, AuditEntry
from .verify import AuditVerifier, DisputeProofGenerator
from .async_protocol import AsyncQuantumProtocol
from .terminal_ui import AetherConsole, get_console
from .timestamp_authority import (
    RFC3161TimestampAuthority,
    TimestampToken,
    TimestampError,
)

try:
    from .dispute_report import DisputeReportGenerator, DisputeReportError
except ImportError:
    pass  # reportlab not installed
from .quantum_backend import (
    IBMQuantumBackend,
    AerSimulatorBackend,
    QuantumSeedResult,
    QuantumSeedPool,
    QuantumSeedPoolTimeout,
    generate_quantum_seed,
    load_ibm_credentials,
    get_pool_status,
)

__all__ = [
    # Quantum crypto
    "QuantumSeedCommitment",
    "QuantumEphemeralKey",
    "get_quantum_seed",
    "verify_signature",
    # Quantum backends
    "IBMQuantumBackend",
    "AerSimulatorBackend",
    "QuantumSeedResult",
    "QuantumSeedPool",
    "QuantumSeedPoolTimeout",
    "generate_quantum_seed",
    "load_ibm_credentials",
    "get_pool_status",
    # State
    "AccountSnapshot",
    "QuantumStateSnapshot",
    # Commitment
    "QuantumDecisionCommitment",
    "QuantumCommitmentVerifier",
    "ReasoningCapture",
    # Execution
    "ExecutionResult",
    "QuantumExecutionAttestation",
    "QuantumExecutionVerifier",
    # Settlement
    "QuantumSettlementRecord",
    "QuantumSettlementVerifier",
    # Audit
    "AuditLog",
    "AuditEntry",
    # Verification
    "AuditVerifier",
    "DisputeProofGenerator",
    # Async
    "AsyncQuantumProtocol",
    # Terminal UI
    "AetherConsole",
    "get_console",
    # Timestamp Authority
    "RFC3161TimestampAuthority",
    "TimestampToken",
    "TimestampError",
]

__version__ = "0.5.1"
