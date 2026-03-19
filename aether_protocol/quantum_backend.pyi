"""Type stubs for aether_protocol.quantum_backend"""

from typing import Optional, Tuple

# Constants
DEFAULT_SEED_QUBITS: int

# Exceptions
class QuantumBackendError(Exception): ...
class IBMConnectionError(QuantumBackendError): ...
class CircuitExecutionError(QuantumBackendError): ...
class QuantumSeedPoolTimeout(QuantumBackendError): ...

def load_ibm_credentials(
    credentials_path: Optional[str] = None,
) -> str: ...

def _build_entropy_circuit(n_qubits: int = ...): ...

# Backward-compatible alias
_build_hadamard_circuit = _build_entropy_circuit

def _bitstring_to_seed(bitstring: str) -> Tuple[int, bytes]: ...

class QuantumSeedResult:
    seed_int: int
    seed_bytes: bytes
    method: str
    backend_name: str
    n_qubits: int
    raw_bitstring: Optional[str]
    job_id: Optional[str]
    timestamp: int
    circuit_depth: int
    def __init__(
        self,
        seed_int: int,
        seed_bytes: bytes,
        method: str,
        backend_name: str,
        n_qubits: int,
        raw_bitstring: Optional[str],
        job_id: Optional[str],
        timestamp: int,
        circuit_depth: int,
    ) -> None: ...
    @property
    def seed_hash(self) -> str: ...
    def to_dict(self) -> dict: ...

class IBMQuantumBackend:
    def __init__(
        self,
        credentials_path: Optional[str] = None,
        backend_name: str = "ibm_fez",
        channel: str = "ibm_quantum_platform",
    ) -> None: ...
    def connect(self) -> IBMQuantumBackend: ...
    @property
    def is_connected(self) -> bool: ...
    @property
    def backend_name(self) -> str: ...
    @property
    def num_qubits(self) -> Optional[int]: ...
    @property
    def service(self): ...
    @property
    def backend(self): ...
    def get_backend_status(self) -> dict: ...
    def generate_seed(
        self,
        n_qubits: int = ...,
        shots: int = 1,
    ) -> QuantumSeedResult: ...

class AerSimulatorBackend:
    def __init__(self) -> None: ...
    @property
    def is_available(self) -> bool: ...
    def generate_seed(self, n_qubits: int = ...) -> QuantumSeedResult: ...

class QuantumSeedPool:
    def __init__(
        self,
        min_pool_size: int = 3,
        max_pool_size: int = 10,
        backend_name: str = "ibm_fez",
        credentials_path: Optional[str] = None,
    ) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def get(self, timeout: float = 30.0) -> QuantumSeedResult: ...
    def status(self) -> dict: ...

def get_pool_status() -> Optional[dict]: ...

def generate_quantum_seed(
    method: str = "OS_URANDOM",
    backend_name: str = "ibm_fez",
    credentials_path: Optional[str] = None,
    n_qubits: int = ...,
) -> QuantumSeedResult: ...
