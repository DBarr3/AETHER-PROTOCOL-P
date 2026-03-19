"""Type stubs for aether_protocol.commitment"""

from typing import Optional, Tuple
from .state import AccountSnapshot

class CommitmentError(Exception): ...

class ReasoningCapture:
    reasoning_text: str
    reasoning_hash: str
    reasoning_model: str
    captured_at: int
    token_count: int
    def __init__(
        self,
        reasoning_text: str,
        reasoning_hash: str,
        reasoning_model: str,
        captured_at: int,
        token_count: int,
    ) -> None: ...
    @classmethod
    def from_text(
        cls,
        text: str,
        model: str = "human",
        token_count: Optional[int] = None,
    ) -> ReasoningCapture: ...
    def verify(self) -> bool: ...
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> ReasoningCapture: ...

class QuantumDecisionCommitment:
    order_id: str
    trade_details: dict
    account_state_hash: str
    quantum_seed_commitment: str
    seed_measurement_method: str
    key_temporal_window: dict
    nonce: int
    timestamp: int
    reasoning: Optional[ReasoningCapture]
    def __init__(
        self,
        order_id: str,
        trade_details: dict,
        account_state_hash: str,
        quantum_seed_commitment: str,
        seed_measurement_method: str,
        key_temporal_window: dict,
        nonce: int,
        timestamp: int,
        reasoning: Optional[ReasoningCapture] = None,
    ) -> None: ...
    def to_signable_dict(self) -> dict: ...
    @classmethod
    def create_and_sign(
        cls,
        order_id: str,
        trade_details: dict,
        account_state: AccountSnapshot,
        quantum_seed: int | bytes,
        measurement_method: str = "OS_URANDOM",
        reasoning: Optional[ReasoningCapture] = None,
    ) -> Tuple[dict, dict, QuantumDecisionCommitment]: ...

class QuantumCommitmentVerifier:
    @staticmethod
    def verify_signature(commitment: dict, signature: dict) -> bool: ...
    @staticmethod
    def verify_state_binding(commitment: dict) -> bool: ...
    @staticmethod
    def verify_quantum_binding(commitment: dict) -> bool: ...
    @staticmethod
    def verify_temporal_safety(commitment: dict) -> bool: ...
    @staticmethod
    def verify_nonce(commitment: dict, expected_nonce: int) -> bool: ...
