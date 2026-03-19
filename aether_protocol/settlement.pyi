"""Type stubs for aether_protocol.settlement"""

from typing import Tuple

class SettlementError(Exception): ...

def compute_flow_merkle(
    commitment_sig: dict,
    execution_sig: dict,
    broker_sig: str,
) -> str: ...

class QuantumSettlementRecord:
    order_id: str
    commitment_sig: dict
    commitment_quantum_seed_commitment: str
    commitment_temporal_window: dict
    execution_sig: dict
    execution_quantum_seed_commitment: str
    execution_temporal_window: dict
    broker_settlement_sig: str
    settlement_timestamp: int
    settlement_quantum_seed_commitment: str
    settlement_temporal_window: dict
    flow_merkle_hash: str
    def __init__(
        self,
        order_id: str,
        commitment_sig: dict,
        commitment_quantum_seed_commitment: str,
        commitment_temporal_window: dict,
        execution_sig: dict,
        execution_quantum_seed_commitment: str,
        execution_temporal_window: dict,
        broker_settlement_sig: str,
        settlement_timestamp: int,
        settlement_quantum_seed_commitment: str,
        settlement_temporal_window: dict,
        flow_merkle_hash: str,
    ) -> None: ...
    def to_signable_dict(self) -> dict: ...
    @classmethod
    def create_and_sign(
        cls,
        order_id: str,
        commitment_sig: dict,
        commitment_seed_hash: str,
        commitment_window: dict,
        execution_sig: dict,
        execution_seed_hash: str,
        execution_window: dict,
        broker_sig: str,
        quantum_seed: int | bytes,
        measurement_method: str = "OS_URANDOM",
    ) -> Tuple[dict, dict, QuantumSettlementRecord]: ...

class QuantumSettlementVerifier:
    @staticmethod
    def verify_signature(settlement: dict, signature: dict) -> bool: ...
    @staticmethod
    def verify_chain(commitment_sig: dict, execution_sig: dict, settlement: dict) -> bool: ...
    @staticmethod
    def verify_all_seeds_independent(settlement: dict) -> bool: ...
    @staticmethod
    def verify_all_temporal_windows(settlement: dict) -> bool: ...
