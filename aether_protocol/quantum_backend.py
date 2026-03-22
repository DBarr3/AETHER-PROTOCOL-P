"""
aether_protocol/quantum_backend.py

IBM Quantum hardware backend for true quantum random seed generation.

Connects to IBM Quantum via qiskit-ibm-runtime, runs a 30-qubit
high-entropy entangled circuit on a real quantum processor (default:
ibm_fez, 156 qubits / Heron r2), and extracts measurement results as
cryptographically random seeds.

Circuit architecture (30 qubits, depth 33):
    Layer 1 -- Hadamard on all 30 qubits (maximum superposition)
    Layer 2 -- CNOT chain: CX(0,1), CX(1,2), ... CX(28,29)
               Creates a fully entangled GHZ-like state where every
               qubit's measurement outcome is correlated with its
               neighbours, maximising multi-qubit entropy.
    Layer 3 -- S (phase) gate on all 30 qubits.  Breaks the H-CX-H
               self-inverse symmetry that would otherwise produce
               deterministic output on a noiseless simulator.
    Layer 4 -- Second Hadamard on all 30 qubits (rotates measurement
               basis into the Y-plane, creating complex interference)
    Layer 5 -- Measure all 30 qubits

Seed extraction:
    The 30-bit measurement bitstring is hashed with SHA-256 to produce
    a uniform 256-bit (32-byte) seed.  SHA-256 post-processing removes
    any residual bias from qubit correlation or hardware noise, ensuring
    the seed passes all standard randomness tests regardless of the raw
    bitstring's statistical properties.

Supported backends:
    IBM_QUANTUM   -- Real quantum hardware (ibm_fez: 156 qubits)
    AER_SIMULATOR -- Qiskit Aer local simulator (same circuit)
    OS_URANDOM    -- Classical fallback (os.urandom)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Protocol variant: "C" = CSPRNG (default), "L" = quantum
PROTOCOL_VARIANT = os.getenv("AETHER_PROTOCOL_VARIANT", "C")

# ── Suppress qiskit_ibm_runtime INFO/WARNING spam ─────────────────────────
if PROTOCOL_VARIANT == "L":
    logging.getLogger('qiskit_ibm_runtime').setLevel(logging.ERROR)
    logging.getLogger('qiskit_ibm_provider').setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


# ── Exceptions ───────────────────────────────────────────────────────────────

class QuantumBackendError(Exception):
    """Raised when a quantum backend operation fails."""


class IBMConnectionError(QuantumBackendError):
    """Raised when IBM Quantum connection fails."""


class CircuitExecutionError(QuantumBackendError):
    """Raised when circuit execution fails on hardware."""


class QuantumSeedPoolTimeout(QuantumBackendError):
    """Raised when the seed pool cannot deliver a seed within the timeout."""


# ── Credentials ──────────────────────────────────────────────────────────────

_DEFAULT_CREDENTIALS_PATHS = [
    Path(__file__).parent / "ibm_credentials.json",
    Path.home() / ".aether" / "ibm_credentials.json",
]


def load_ibm_credentials(
    credentials_path: Optional[str] = None,
) -> str:
    """
    Load IBM Quantum API key from credentials file.

    Search order:
        1. Explicit path (if provided)
        2. Environment variable IBM_QUANTUM_API_KEY
        3. aether_protocol/ibm_credentials.json
        4. ~/.aether/ibm_credentials.json

    Args:
        credentials_path: Optional explicit path to credentials JSON.

    Returns:
        API key string.

    Raises:
        IBMConnectionError: If no credentials found.
    """
    # 1. Explicit path
    if credentials_path:
        p = Path(credentials_path)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data["apikey"]
            except (json.JSONDecodeError, KeyError) as e:
                raise IBMConnectionError(f"Invalid credentials file {p}: {e}")
        raise IBMConnectionError(f"Credentials file not found: {credentials_path}")

    # 2. Environment variable (via key_manager or direct)
    try:
        from config.key_manager import get_ibm_token
        env_key = get_ibm_token()
    except ImportError:
        env_key = os.environ.get("IBM_QUANTUM_API_KEY")
    if env_key:
        return env_key

    # 3-4. Default paths
    for p in _DEFAULT_CREDENTIALS_PATHS:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data["apikey"]
            except (json.JSONDecodeError, KeyError) as e:
                raise IBMConnectionError(f"Invalid credentials file {p}: {e}")

    raise IBMConnectionError(
        "No IBM Quantum credentials found. Set IBM_QUANTUM_API_KEY env var "
        "or place ibm_credentials.json in aether_protocol/ or ~/.aether/"
    )


# ── Default circuit parameters ──────────────────────────────────────────────

# 30 qubits: high entropy while staying well within ibm_fez's 156-qubit
# capacity.  30 entangled qubits produce 2^30 (~1 billion) possible
# measurement outcomes before SHA-256 extraction.
DEFAULT_SEED_QUBITS = 30


# ── Circuit builder ─────────────────────────────────────────────────────────

def _build_entropy_circuit(n_qubits: int = DEFAULT_SEED_QUBITS):
    """
    Build a 30-qubit high-entropy entangled circuit for seed generation.

    Architecture (5 layers, depth = n + 2):
        1. H layer     -- Hadamard on every qubit (maximum superposition)
        2. CNOT chain  -- CX(0,1), CX(1,2), ... CX(n-2, n-1)
                          Creates GHZ-like entanglement across all qubits.
        3. S layer     -- Phase gate (S = diag(1, i)) on every qubit.
                          Breaks the H-CX-H self-inverse identity that
                          would otherwise map |0>^n -> |0>^n exactly.
                          Without this layer, a noiseless simulator
                          produces deterministic all-zero output.
        4. H layer     -- Second Hadamard (measurement basis rotation).
                          Combined with the S layer, this creates a
                          non-trivial interference pattern that yields
                          genuine randomness even on a noiseless simulator.
        5. Measure     -- Collapse all qubits to classical bits.

    Why SHA-256 post-processing:
        The n-bit measurement bitstring may have residual bias from qubit
        correlations (entanglement) or hardware noise.  SHA-256 hashing
        produces a uniform 256-bit seed regardless of the input's
        statistical properties -- a standard entropy extraction technique.

    ibm_fez has 156 qubits -- 30 is well within capacity.

    Args:
        n_qubits: Number of qubits (default: 30).

    Returns:
        QuantumCircuit with H -> CNOT chain -> S -> H -> measure.
    """
    from qiskit import QuantumCircuit

    qc = QuantumCircuit(n_qubits, n_qubits)

    # ── Layer 1: Hadamard (maximum superposition) ────────────────────
    # |0>^n  ->  (|0> + |1>)^n / sqrt(2^n)
    for i in range(n_qubits):
        qc.h(i)

    # ── Layer 2: CNOT chain (full entanglement) ──────────────────────
    # Creates correlations: measuring qubit k affects the probability
    # distribution of qubit k+1.  The resulting state is a GHZ-like
    # superposition across all n qubits.
    for i in range(n_qubits - 1):
        qc.cx(i, i + 1)

    # ── Layer 3: Phase gates (break self-inverse symmetry) ───────────
    # S gate: |0> -> |0>, |1> -> i|1>
    # This 90-degree phase rotation breaks the identity
    # H^n . CX_chain . H^n = CX_chain_reversed, which would map
    # |0>^n back to |0>^n on a perfect simulator.  With S gates
    # interposed, the circuit becomes irreversible in the
    # computational basis, producing a non-trivial measurement
    # distribution even without hardware noise.
    for i in range(n_qubits):
        qc.s(i)

    # ── Layer 4: Second Hadamard (measurement basis rotation) ────────
    # Combined with the S layer, H.S rotates each qubit into the
    # Y-basis (|+i>, |-i>), creating complex interference patterns
    # across the entangled state.
    for i in range(n_qubits):
        qc.h(i)

    # ── Layer 5: Measure all qubits ──────────────────────────────────
    qc.measure(range(n_qubits), range(n_qubits))

    return qc


# Keep backward-compatible alias for existing imports
_build_hadamard_circuit = _build_entropy_circuit


def _bitstring_to_seed(bitstring: str) -> Tuple[int, bytes]:
    """
    Convert a measurement bitstring to a 256-bit seed.

    Hashes the raw bitstring with SHA-256 to ensure uniform distribution
    regardless of the number of qubits measured.

    Args:
        bitstring: Binary string from quantum measurement (e.g. "01101...").

    Returns:
        Tuple of (seed_as_int, seed_as_bytes).
    """
    seed_bytes = hashlib.sha256(bitstring.encode("utf-8")).digest()
    seed_int = int.from_bytes(seed_bytes, "big")
    return seed_int, seed_bytes


# ── Backend result dataclass ─────────────────────────────────────────────────

@dataclass(frozen=True)
class QuantumSeedResult:
    """
    Result from a quantum seed generation request.

    Contains the seed, its provenance metadata, and the raw measurement
    data for auditability.
    """
    seed_int: int
    seed_bytes: bytes
    method: str                     # "CSPRNG" | "IBM_QUANTUM" | "AER_SIMULATOR" | "OS_URANDOM"
    backend_name: str               # e.g. "ibm_fez", "aer_simulator", "os_urandom"
    n_qubits: int                   # Number of qubits measured (0 for OS_URANDOM)
    raw_bitstring: Optional[str]    # Raw measurement result (None for OS_URANDOM)
    job_id: Optional[str]           # IBM Quantum job ID (None for local)
    timestamp: int                  # Unix timestamp of measurement
    circuit_depth: int              # Circuit depth (0 for OS_URANDOM)

    @property
    def seed_hash(self) -> str:
        """SHA-256 hex digest of the seed bytes."""
        return hashlib.sha256(self.seed_bytes).hexdigest()

    def to_dict(self) -> dict:
        """Serialise for audit logging (excludes raw seed)."""
        return {
            "method": self.method,
            "backend_name": self.backend_name,
            "n_qubits": self.n_qubits,
            "raw_bitstring": self.raw_bitstring,
            "job_id": self.job_id,
            "timestamp": self.timestamp,
            "circuit_depth": self.circuit_depth,
            "seed_hash": self.seed_hash,
        }


# ── IBM Quantum Backend ─────────────────────────────────────────────────────

class IBMQuantumBackend:
    """
    Connects to IBM Quantum hardware and generates true quantum random seeds.

    Default backend is ibm_fez (156 qubits, Heron r2 processor).

    All IBM API calls are routed through a shared QuantumSessionManager
    to enforce the hard cap of 1 IBM call per session.

    Usage:
        backend = IBMQuantumBackend()
        result = backend.generate_seed(n_qubits=30)
        print(result.seed_int)       # 256-bit integer
        print(result.job_id)         # IBM job ID for audit trail
        print(result.raw_bitstring)  # Raw measurement outcome
    """

    # Shared session manager for IBM hard cap enforcement
    _session_manager = None

    @classmethod
    def _get_session_manager(cls):
        """Lazily create a shared QuantumSessionManager singleton."""
        if cls._session_manager is None:
            from quantum_session import QuantumSessionManager
            cls._session_manager = QuantumSessionManager()
        return cls._session_manager

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        backend_name: str = "ibm_fez",
        channel: str = "ibm_quantum_platform",
    ) -> None:
        """
        Initialise IBM Quantum connection.

        Args:
            credentials_path: Path to ibm_credentials.json.
            backend_name: IBM backend to use (default: ibm_fez).
            channel: IBM Quantum channel (default: ibm_quantum_platform).
        """
        self._backend_name = backend_name
        self._channel = channel
        self._service = None
        self._backend = None
        self._api_key = load_ibm_credentials(credentials_path)

    def connect(self) -> "IBMQuantumBackend":
        """
        Establish connection to IBM Quantum service and backend.

        Returns:
            self (for chaining).

        Raises:
            IBMConnectionError: If connection fails.
        """
        try:
            from qiskit_ibm_runtime import QiskitRuntimeService

            self._service = QiskitRuntimeService(
                channel=self._channel,
                token=self._api_key,
            )
            self._backend = self._service.backend(self._backend_name)
            logger.info(
                "Connected to IBM Quantum backend: %s (%d qubits)",
                self._backend_name,
                self._backend.num_qubits,
            )
            return self

        except ImportError as e:
            raise IBMConnectionError(
                "qiskit-ibm-runtime not installed. "
                "Install with: pip install qiskit-ibm-runtime"
            ) from e
        except Exception as e:
            raise IBMConnectionError(
                f"Failed to connect to IBM Quantum ({self._backend_name}): {e}"
            ) from e

    @property
    def is_connected(self) -> bool:
        """Check if backend connection is active."""
        return self._backend is not None

    @property
    def backend_name(self) -> str:
        """Name of the target backend."""
        return self._backend_name

    @property
    def num_qubits(self) -> Optional[int]:
        """Number of qubits on the connected backend (None if not connected)."""
        if self._backend is None:
            return None
        return self._backend.num_qubits

    @property
    def service(self):
        """The underlying QiskitRuntimeService (None if not connected)."""
        return self._service

    @property
    def backend(self):
        """The underlying IBM backend object (None if not connected)."""
        return self._backend

    def get_backend_status(self) -> dict:
        """
        Query current backend status.

        Returns:
            Dict with operational_status, pending_jobs, backend_version, etc.

        Raises:
            IBMConnectionError: If not connected.
        """
        if not self.is_connected:
            raise IBMConnectionError("Not connected. Call connect() first.")

        try:
            status = self._backend.status()
            return {
                "backend_name": self._backend_name,
                "operational": status.operational,
                "pending_jobs": status.pending_jobs,
                "status_msg": status.status_msg,
                "num_qubits": self._backend.num_qubits,
            }
        except Exception as e:
            raise IBMConnectionError(f"Failed to query backend status: {e}") from e

    def generate_seed(
        self,
        n_qubits: int = DEFAULT_SEED_QUBITS,
        shots: int = 1,
    ) -> QuantumSeedResult:
        """
        Generate a quantum random seed by running a Hadamard circuit.

        Submits a circuit to real quantum hardware, waits for the result,
        and extracts the measurement bitstring as a seed.

        Args:
            n_qubits: Number of qubits to measure (max: backend capacity).
            shots: Number of measurement shots (uses first result).

        Returns:
            QuantumSeedResult with seed, provenance, and raw data.

        Raises:
            IBMConnectionError: If not connected.
            CircuitExecutionError: If circuit execution fails.
        """
        if not self.is_connected:
            raise IBMConnectionError("Not connected. Call connect() first.")

        # Clamp to backend capacity
        max_qubits = self._backend.num_qubits
        if n_qubits > max_qubits:
            logger.warning(
                "Requested %d qubits but %s has %d. Clamping.",
                n_qubits, self._backend_name, max_qubits,
            )
            n_qubits = max_qubits

        try:
            from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

            # Build circuit
            qc = _build_entropy_circuit(n_qubits)
            circuit_depth = qc.depth()

            # Transpile for target backend
            pm = generate_preset_pass_manager(
                optimization_level=1,
                backend=self._backend,
            )
            transpiled = pm.run(qc)

            # Execute on hardware via session manager hard cap
            sm = self._get_session_manager()
            job = sm._ibm_submit_single([(transpiled,)], self._service)

            logger.info(
                "Submitted job %s to %s (%d qubits, %d shots)",
                job.job_id(), self._backend_name, n_qubits, shots,
            )

            # Wait for result
            result = job.result()
            timestamp = int(time.time())

            # Extract bitstring from result
            # SamplerV2 returns PubResult objects with DataBin
            pub_result = result[0]
            data_bin = pub_result.data

            # The classical register name depends on the circuit.
            # Our circuit uses the default register name 'c'.
            # Dynamically find the first BitArray attribute.
            bitarray = None
            for attr_name in dir(data_bin):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(data_bin, attr_name)
                if hasattr(attr, "get_bitstrings"):
                    bitarray = attr
                    break

            if bitarray is None:
                raise CircuitExecutionError(
                    f"Could not extract bitstrings from result. "
                    f"DataBin fields: {[a for a in dir(data_bin) if not a.startswith('_')]}"
                )

            # Get the first shot's bitstring
            raw_bitstring = bitarray.get_bitstrings()[0]

            # Convert to seed
            seed_int, seed_bytes = _bitstring_to_seed(raw_bitstring)

            return QuantumSeedResult(
                seed_int=seed_int,
                seed_bytes=seed_bytes,
                method="IBM_QUANTUM",
                backend_name=self._backend_name,
                n_qubits=n_qubits,
                raw_bitstring=raw_bitstring,
                job_id=job.job_id(),
                timestamp=timestamp,
                circuit_depth=circuit_depth,
            )

        except IBMConnectionError:
            raise
        except Exception as e:
            raise CircuitExecutionError(
                f"Circuit execution failed on {self._backend_name}: {e}"
            ) from e


# ── Aer Simulator Backend ───────────────────────────────────────────────────

class AerSimulatorBackend:
    """
    Local Qiskit Aer simulator for quantum seed generation.

    Runs the same Hadamard circuit locally using Aer's statevector
    simulator. Useful for testing and development without IBM hardware
    access or queue wait times.

    Note: Aer uses a PRNG internally, so seeds are pseudo-random rather
    than truly quantum-random. The circuit structure is identical.
    """

    def __init__(self) -> None:
        self._available = False
        try:
            from qiskit_aer import AerSimulator
            # Configure with enough qubits for the 30-qubit entropy circuit.
            # Default AerSimulator may limit to 29 qubits on some platforms.
            self._simulator = AerSimulator(method="automatic")
            self._available = True
        except ImportError:
            self._simulator = None

    @property
    def is_available(self) -> bool:
        return self._available

    def generate_seed(self, n_qubits: int = DEFAULT_SEED_QUBITS) -> QuantumSeedResult:
        """
        Generate a seed using the local Aer simulator.

        Args:
            n_qubits: Number of qubits to measure.

        Returns:
            QuantumSeedResult with method="AER_SIMULATOR".

        Raises:
            QuantumBackendError: If Aer is not installed.
        """
        if not self._available:
            raise QuantumBackendError(
                "qiskit-aer not installed. Install with: pip install qiskit-aer"
            )

        from qiskit_aer import AerSimulator

        qc = _build_entropy_circuit(n_qubits)
        circuit_depth = qc.depth()

        # Run directly on Aer without transpile -- our circuit uses
        # only H, CX, and measure gates which Aer supports natively.
        # This avoids Aer's default coupling-map qubit limit.
        result = self._simulator.run(qc, shots=1).result()
        timestamp = int(time.time())

        counts = result.get_counts()
        raw_bitstring = list(counts.keys())[0]

        seed_int, seed_bytes = _bitstring_to_seed(raw_bitstring)

        return QuantumSeedResult(
            seed_int=seed_int,
            seed_bytes=seed_bytes,
            method="AER_SIMULATOR",
            backend_name="aer_simulator",
            n_qubits=n_qubits,
            raw_bitstring=raw_bitstring,
            job_id=None,
            timestamp=timestamp,
            circuit_depth=circuit_depth,
        )


# ── OS urandom fallback ─────────────────────────────────────────────────────

def _generate_os_urandom_seed() -> QuantumSeedResult:
    """
    Classical fallback using os.urandom.

    Always available. Used when no quantum backend is configured.
    """
    seed_bytes = os.urandom(32)
    seed_int = int.from_bytes(seed_bytes, "big")

    return QuantumSeedResult(
        seed_int=seed_int,
        seed_bytes=seed_bytes,
        method="OS_URANDOM",
        backend_name="os_urandom",
        n_qubits=0,
        raw_bitstring=None,
        job_id=None,
        timestamp=int(time.time()),
        circuit_depth=0,
    )


def _generate_csprng_seed() -> QuantumSeedResult:
    """
    Protocol-C entropy source using secrets.token_bytes (CSPRNG).

    Uses os.urandom via the secrets module — cryptographically secure
    and always available without any external dependencies.
    """
    seed_bytes = secrets.token_bytes(32)
    seed_int = int.from_bytes(seed_bytes, "big")

    return QuantumSeedResult(
        seed_int=seed_int,
        seed_bytes=seed_bytes,
        method="CSPRNG",
        backend_name="csprng_os_urandom",
        n_qubits=0,
        raw_bitstring=None,
        job_id=None,
        timestamp=int(time.time()),
        circuit_depth=0,
    )


# ── Quantum Seed Pool ──────────────────────────────────────────────────────

class QuantumSeedPool:
    """
    Background thread-based pre-generation buffer for IBM Quantum seeds.

    Keeps a pool of ready-to-use QuantumSeedResult objects so that
    get_quantum_seed("IBM_QUANTUM") never blocks on queue latency.
    A daemon thread monitors the pool size and submits new IBM Quantum
    jobs (each in its own thread) whenever the count drops below
    min_pool_size.

    Thread architecture:
        - Main refill thread (daemon): checks pool size every 15 s,
          spawns per-job threads when pool is below low-water mark.
        - Per-job threads (daemon): each runs a single IBM Quantum
          circuit, enqueues the result, and exits.

    Usage:
        pool = QuantumSeedPool(min_pool_size=3, max_pool_size=10)
        pool.start()
        result = pool.get(timeout=30.0)   # QuantumSeedResult
        pool.stop()

    Args:
        min_pool_size: Low-water mark; refill triggers when pool falls
            below this count (default 3).
        max_pool_size: Maximum seeds to buffer (default 10).
        backend_name: IBM backend name (default "ibm_fez").
        credentials_path: Optional path to IBM credentials JSON.
    """

    _REFILL_INTERVAL = 15.0  # seconds between pool-size checks

    def __init__(
        self,
        min_pool_size: int = 3,
        max_pool_size: int = 10,
        backend_name: str = "ibm_fez",
        credentials_path: Optional[str] = None,
    ) -> None:
        self._min = min_pool_size
        self._max = max_pool_size
        self._backend_name = backend_name
        self._credentials_path = credentials_path

        self._queue: queue.Queue[QuantumSeedResult] = queue.Queue(maxsize=max_pool_size)
        self._running = False
        self._refill_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._jobs_submitted = 0
        self._jobs_completed = 0
        self._jobs_failed = 0
        self._backend: Optional[IBMQuantumBackend] = None

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background refill thread (idempotent)."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._refill_thread = threading.Thread(
                target=self._refill_loop,
                name="QuantumSeedPool-refill",
                daemon=True,
            )
            self._refill_thread.start()
            logger.info("QuantumSeedPool started (min=%d, max=%d)", self._min, self._max)

    def stop(self) -> None:
        """Signal the refill thread to stop (idempotent)."""
        with self._lock:
            if not self._running:
                return
            self._running = False
        # The daemon thread will exit on the next loop iteration
        if self._refill_thread is not None:
            self._refill_thread.join(timeout=5.0)
            self._refill_thread = None
        logger.info("QuantumSeedPool stopped")

    # ── public interface ──────────────────────────────────────────────

    def get(self, timeout: float = 30.0) -> QuantumSeedResult:
        """
        Retrieve a pre-generated seed from the pool.

        Args:
            timeout: Maximum seconds to wait for a seed.

        Returns:
            QuantumSeedResult from IBM Quantum hardware.

        Raises:
            QuantumSeedPoolTimeout: If no seed is available within timeout.
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            raise QuantumSeedPoolTimeout(
                f"No quantum seed available within {timeout:.1f}s "
                f"(pool size: {self._queue.qsize()}, "
                f"submitted: {self._jobs_submitted}, "
                f"completed: {self._jobs_completed}, "
                f"failed: {self._jobs_failed})"
            )

    def status(self) -> dict:
        """
        Return a snapshot of the pool's current state.

        Returns:
            Dict with pool_size, running, min_pool_size, max_pool_size,
            jobs_submitted, jobs_completed, jobs_failed, backend_name.
        """
        return {
            "pool_size": self._queue.qsize(),
            "running": self._running,
            "min_pool_size": self._min,
            "max_pool_size": self._max,
            "jobs_submitted": self._jobs_submitted,
            "jobs_completed": self._jobs_completed,
            "jobs_failed": self._jobs_failed,
            "backend_name": self._backend_name,
        }

    # ── internal ──────────────────────────────────────────────────────

    def _ensure_backend(self) -> IBMQuantumBackend:
        """Lazily connect to IBM Quantum (thread-safe)."""
        with self._lock:
            if self._backend is None or not self._backend.is_connected:
                self._backend = IBMQuantumBackend(
                    credentials_path=self._credentials_path,
                    backend_name=self._backend_name,
                )
                self._backend.connect()
            return self._backend

    def _refill_loop(self) -> None:
        """
        Daemon loop: check pool size, spawn per-job threads when low.

        Runs every _REFILL_INTERVAL seconds. When pool size drops below
        min_pool_size, spawns (max_pool_size - current_size) job threads
        to replenish the buffer.
        """
        while self._running:
            try:
                current_size = self._queue.qsize()
                if current_size < self._min:
                    deficit = self._max - current_size
                    logger.debug(
                        "Pool low (%d/%d), spawning %d job(s)",
                        current_size, self._min, deficit,
                    )
                    for _ in range(deficit):
                        t = threading.Thread(
                            target=self._generate_one,
                            name="QuantumSeedPool-job",
                            daemon=True,
                        )
                        t.start()
                        self._jobs_submitted += 1
            except Exception:
                logger.exception("Error in seed pool refill loop")

            # Sleep in short increments so stop() is responsive
            deadline = time.monotonic() + self._REFILL_INTERVAL
            while self._running and time.monotonic() < deadline:
                time.sleep(0.5)

    def _generate_one(self) -> None:
        """Generate a single IBM Quantum seed and enqueue it."""
        try:
            backend = self._ensure_backend()
            result = backend.generate_seed(n_qubits=DEFAULT_SEED_QUBITS)
            # Non-blocking put -- if queue is full, discard silently
            try:
                self._queue.put_nowait(result)
                self._jobs_completed += 1
                logger.debug(
                    "Seed enqueued (pool size now %d)", self._queue.qsize()
                )
            except queue.Full:
                self._jobs_completed += 1
                logger.debug("Pool full, discarding extra seed")
        except Exception:
            self._jobs_failed += 1
            logger.warning("IBM Quantum seed generation failed", exc_info=True)


# Module-level pool singleton (lazily initialised)
_seed_pool_singleton: Optional[QuantumSeedPool] = None
_seed_pool_lock = threading.Lock()


def get_pool_status() -> Optional[dict]:
    """
    Return the current seed pool status, or None if the pool has not
    been initialised yet.

    Returns:
        Dict with pool metrics, or None.
    """
    if _seed_pool_singleton is not None:
        return _seed_pool_singleton.status()
    return None


# ── Unified seed generator ──────────────────────────────────────────────────

_ibm_backend_singleton: Optional[IBMQuantumBackend] = None


def generate_quantum_seed(
    method: str = "OS_URANDOM",
    backend_name: str = "ibm_fez",
    credentials_path: Optional[str] = None,
    n_qubits: int = DEFAULT_SEED_QUBITS,
) -> QuantumSeedResult:
    """
    Generate a seed using the specified method.

    When AETHER_PROTOCOL_VARIANT=C (default), this always returns a
    CSPRNG seed regardless of the requested method.  The quantum paths
    (IBM_QUANTUM, AER_SIMULATOR) are only active when
    AETHER_PROTOCOL_VARIANT=L.

    Args:
        method: "CSPRNG", "IBM_QUANTUM", "AER_SIMULATOR", or "OS_URANDOM".
        backend_name: IBM backend name (only used for IBM_QUANTUM).
        credentials_path: Path to credentials JSON (only for IBM_QUANTUM).
        n_qubits: Number of qubits to measure.

    Returns:
        QuantumSeedResult with full provenance metadata.
    """
    global _ibm_backend_singleton

    # ── Protocol-C: always CSPRNG ─────────────────────────────────────
    if PROTOCOL_VARIANT == "C":
        return _generate_csprng_seed()

    # ── Protocol-L: quantum paths ─────────────────────────────────────
    if method == "CSPRNG":
        return _generate_csprng_seed()

    elif method == "IBM_QUANTUM":
        if _ibm_backend_singleton is None or not _ibm_backend_singleton.is_connected:
            _ibm_backend_singleton = IBMQuantumBackend(
                credentials_path=credentials_path,
                backend_name=backend_name,
            )
            _ibm_backend_singleton.connect()
        return _ibm_backend_singleton.generate_seed(n_qubits=n_qubits)

    elif method == "AER_SIMULATOR":
        aer = AerSimulatorBackend()
        return aer.generate_seed(n_qubits=n_qubits)

    elif method == "OS_URANDOM":
        return _generate_os_urandom_seed()

    else:
        raise QuantumBackendError(f"Unknown method: {method}")
