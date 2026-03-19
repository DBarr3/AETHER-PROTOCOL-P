"""Type stubs for aether_protocol.execution"""

from typing import Tuple
from .state import AccountSnapshot

class ExecutionError(Exception): ...

class ExecutionResult:
    order_id: str
    filled_qty: float
    fill_price: float
    execution_timestamp: int
    broker_response: dict
    def __init__(
        self,
        order_id: str,
        filled_qty: float,
        fill_price: float,
        execution_timestamp: int = ...,
        broker_response: dict = ...,
    ) -> None: ...
    def to_json(self) -> dict: ...
    def to_hash(self) -> str: ...

class QuantumExecutionAttestation:
    commitment_sig: dict
    commitment_quantum_seed_commitment: str
    execution_result: dict
    execution_quantum_seed_commitment: str
    new_account_state_hash: str
    nonce_after: int
    key_temporal_window: dict
    def __init__(
        self,
        commitment_sig: dict,
        commitment_quantum_seed_commitment: str,
        execution_result: dict,
        execution_quantum_seed_commitment: str,
        new_account_state_hash: str,
        nonce_after: int,
        key_temporal_window: dict,
    ) -> None: ...
    def to_signable_dict(self) -> dict: ...
    @classmethod
    def create_and_sign(
        cls,
        commitment_sig: dict,
        commitment_seed_hash: str,
        execution_result: ExecutionResult,
        new_account_state: AccountSnapshot,
        quantum_seed: int | bytes,
        measurement_method: str = "OS_URANDOM",
    ) -> Tuple[dict, dict, QuantumExecutionAttestation]: ...

class QuantumExecutionVerifier:
    @staticmethod
    def verify_signature(attestation: dict, signature: dict) -> bool: ...
    @staticmethod
    def verify_references_commitment(attestation: dict, commitment_sig: dict) -> bool: ...
    @staticmethod
    def verify_nonce_increment(commitment_nonce: int, attestation: dict) -> bool: ...
    @staticmethod
    def verify_independent_seeds(commitment_seed_hash: str, execution_seed_hash: str) -> bool: ...
    @staticmethod
    def verify_quantum_binding(attestation: dict) -> bool: ...
    @staticmethod
    def verify_temporal_safety(attestation: dict) -> bool: ...
