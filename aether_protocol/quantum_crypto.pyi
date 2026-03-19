"""Type stubs for aether_protocol.quantum_crypto"""

from typing import Optional, Tuple

# Constants
DEFAULT_KEY_LIFETIME_SECONDS: int
SHOR_EARLIEST_ATTACK_SECONDS: int
MEASUREMENT_METHODS: tuple[str, ...]

# Exceptions
class QuantumCryptoError(Exception): ...
class KeyDestroyedError(QuantumCryptoError): ...

class QuantumSeedCommitment:
    seed_hash: str
    measurement_timestamp: int
    measurement_method: str
    key_creation_timestamp: int
    key_expiration_timestamp: int
    def __init__(
        self,
        seed_hash: str,
        measurement_timestamp: int,
        measurement_method: str,
        key_creation_timestamp: int,
        key_expiration_timestamp: int,
    ) -> None: ...
    @property
    def temporal_window_hours(self) -> float: ...
    @property
    def temporal_window_dict(self) -> dict: ...
    def to_dict(self) -> dict: ...
    @staticmethod
    def from_dict(data: dict) -> QuantumSeedCommitment: ...

class QuantumEphemeralKey:
    def __init__(
        self,
        quantum_seed: int | bytes,
        method: str = "OS_URANDOM",
        key_lifetime_seconds: int = ...,
    ) -> None: ...
    @property
    def seed_commitment(self) -> QuantumSeedCommitment: ...
    @property
    def public_key_hex(self) -> str: ...
    @property
    def is_destroyed(self) -> bool: ...
    def sign(self, message: dict) -> dict: ...
    def verify(self, message: dict, signature: dict) -> bool: ...

def get_quantum_seed(
    method: str = "OS_URANDOM",
    backend_name: str = "ibm_fez",
    credentials_path: Optional[str] = None,
    n_qubits: int = 30,
) -> Tuple[int, str]: ...

def verify_signature(message: dict, signature: dict) -> bool: ...

def make_temporal_window(
    created_at: int | None = None,
    lifetime_seconds: int = ...,
) -> dict: ...
