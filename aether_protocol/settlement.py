"""
aether_protocol/settlement.py

Quantum-sealed settlement records.

Final merkle of commitment + execution + settlement, sealed with a THIRD
independent quantum seed.

Quantum Safety of Complete Trade:
    - 3 different quantum measurements (different seeds)
    - 3 different ephemeral keys (all destroyed)
    - 3 temporal windows (all closed before Shor's)
    - Merkle hash proves nothing was modified
    - To forge: need all 3 keys (impossible, destroyed)
      or solve ECDLP 3x (impossible at current QC scale)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .quantum_crypto import (
    QuantumEphemeralKey,
    verify_signature,
    make_temporal_window,
)


class SettlementError(Exception):
    """Raised when settlement operations fail."""


def compute_flow_merkle(
    commitment_sig: dict, execution_sig: dict, broker_sig: str
) -> str:
    """
    Compute the flow merkle hash from three signature components.

    This is a SHA-256 of the canonical concatenation of commitment
    signature, execution signature, and broker settlement acknowledgement.

    Args:
        commitment_sig: Commitment signature envelope.
        execution_sig: Execution signature envelope.
        broker_sig: Broker's settlement acknowledgement string.

    Returns:
        Hex-encoded SHA-256 merkle hash.
    """
    commitment_str = json.dumps(commitment_sig, sort_keys=True, separators=(",", ":"))
    execution_str = json.dumps(execution_sig, sort_keys=True, separators=(",", ":"))
    combined = commitment_str + execution_str + broker_sig
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class QuantumSettlementRecord:
    """
    Final settlement record sealed with a THIRD quantum seed.

    Contains the complete chain of quantum seed commitments and temporal
    windows from all three phases, plus the flow merkle hash.

    Fields:
        order_id: The order being settled.
        commitment_sig: Signature from commitment phase.
        commitment_quantum_seed_commitment: Seed hash from commitment.
        commitment_temporal_window: Temporal window from commitment key.
        execution_sig: Signature from execution phase.
        execution_quantum_seed_commitment: Seed hash from execution.
        execution_temporal_window: Temporal window from execution key.
        broker_settlement_sig: Broker's settlement acknowledgement.
        settlement_timestamp: Unix timestamp of settlement.
        settlement_quantum_seed_commitment: Seed hash for THIS phase's key.
        settlement_temporal_window: Temporal window for THIS key.
        flow_merkle_hash: Merkle hash of (commitment_sig + execution_sig + broker_sig).
    """

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

    def to_signable_dict(self) -> dict:
        """
        Canonical signable representation of the entire trade flow.

        Returns:
            Dict ready for signing.
        """
        return {
            "order_id": self.order_id,
            "commitment_sig": self.commitment_sig,
            "commitment_quantum_seed_commitment": self.commitment_quantum_seed_commitment,
            "commitment_temporal_window": self.commitment_temporal_window,
            "execution_sig": self.execution_sig,
            "execution_quantum_seed_commitment": self.execution_quantum_seed_commitment,
            "execution_temporal_window": self.execution_temporal_window,
            "broker_settlement_sig": self.broker_settlement_sig,
            "settlement_timestamp": self.settlement_timestamp,
            "settlement_quantum_seed_commitment": self.settlement_quantum_seed_commitment,
            "settlement_temporal_window": self.settlement_temporal_window,
            "flow_merkle_hash": self.flow_merkle_hash,
        }

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
    ) -> Tuple[dict, dict, "QuantumSettlementRecord"]:
        """
        Seal the trade with a THIRD quantum seed.

        Args:
            order_id: Order identifier.
            commitment_sig: Commitment signature envelope.
            commitment_seed_hash: Commitment quantum seed hash.
            commitment_window: Commitment key temporal window.
            execution_sig: Execution signature envelope.
            execution_seed_hash: Execution quantum seed hash.
            execution_window: Execution key temporal window.
            broker_sig: Broker's settlement acknowledgement string.
            quantum_seed: THIRD quantum seed for settlement.
            measurement_method: Source of the seed.

        Returns:
            Tuple of (settlement_dict, signature_envelope, settlement_object).

        Raises:
            SettlementError: If signing fails.
        """
        now = int(time.time())

        # Derive THIRD ephemeral key
        ephemeral_key = QuantumEphemeralKey(
            quantum_seed=quantum_seed,
            method=measurement_method,
        )

        # Compute flow merkle
        flow_merkle = compute_flow_merkle(commitment_sig, execution_sig, broker_sig)

        settlement = cls(
            order_id=order_id,
            commitment_sig=commitment_sig,
            commitment_quantum_seed_commitment=commitment_seed_hash,
            commitment_temporal_window=commitment_window,
            execution_sig=execution_sig,
            execution_quantum_seed_commitment=execution_seed_hash,
            execution_temporal_window=execution_window,
            broker_settlement_sig=broker_sig,
            settlement_timestamp=now,
            settlement_quantum_seed_commitment=ephemeral_key.seed_commitment.seed_hash,
            settlement_temporal_window=ephemeral_key.seed_commitment.temporal_window_dict,
            flow_merkle_hash=flow_merkle,
        )

        signable = settlement.to_signable_dict()

        try:
            signature = ephemeral_key.sign(signable)
        except Exception as exc:
            raise SettlementError(f"Failed to sign settlement: {exc}") from exc

        assert ephemeral_key.is_destroyed, "CRITICAL: Key not destroyed after signing"

        return signable, signature, settlement


class QuantumSettlementVerifier:
    """
    Verifies quantum settlement record signatures and chain linkage.
    """

    @staticmethod
    def verify_signature(settlement: dict, signature: dict) -> bool:
        """Verify the settlement signature."""
        return verify_signature(settlement, signature)

    @staticmethod
    def verify_chain(
        commitment_sig: dict, execution_sig: dict, settlement: dict
    ) -> bool:
        """
        Verify the settlement correctly links commitment and execution.

        Checks:
        1. Settlement references correct commitment_sig
        2. Settlement references correct execution_sig
        3. Flow merkle hash matches recomputed value

        Returns:
            True if the chain is valid.
        """
        if settlement.get("commitment_sig") != commitment_sig:
            return False
        if settlement.get("execution_sig") != execution_sig:
            return False

        broker_sig = settlement.get("broker_settlement_sig", "")
        expected_merkle = compute_flow_merkle(commitment_sig, execution_sig, broker_sig)
        return settlement.get("flow_merkle_hash") == expected_merkle

    @staticmethod
    def verify_all_seeds_independent(settlement: dict) -> bool:
        """
        Verify all three quantum seeds are independent (different measurements).

        P4: Perfect Forward Secrecy requires each phase to use an
        independent quantum seed.

        Returns:
            True if all three seed commitments are different.
        """
        seeds = {
            settlement.get("commitment_quantum_seed_commitment"),
            settlement.get("execution_quantum_seed_commitment"),
            settlement.get("settlement_quantum_seed_commitment"),
        }
        # Must have exactly 3 different, non-None seeds
        seeds.discard(None)
        return len(seeds) == 3

    @staticmethod
    def verify_all_temporal_windows(settlement: dict) -> bool:
        """
        Verify all three temporal windows prove safety against Shor's.

        Returns:
            True if all keys expired before Shor's earliest attack.
        """
        for window_key in [
            "commitment_temporal_window",
            "execution_temporal_window",
            "settlement_temporal_window",
        ]:
            window = settlement.get(window_key, {})
            if not isinstance(window, dict):
                return False
            expires_at = window.get("expires_at", 0)
            shor_attack = window.get("shor_earliest_attack", 0)
            if not expires_at or not shor_attack:
                return False
            if expires_at >= shor_attack:
                return False
        return True
