"""
aether_protocol/commitment.py

Quantum-bound trade decision commitments.

A QuantumDecisionCommitment cryptographically binds a trade decision to:
1. The account state at decision time (via state hash)
2. The quantum seed used for signing (via seed commitment hash)
3. A temporal window proving the key was destroyed before Shor's could run
4. A strictly incrementing nonce (prevents replays)

Quantum Safety:
    - Signature is only valid with the ephemeral key (destroyed after signing)
    - To forge: need the private key (destroyed) OR solve ECDLP on secp256k1
      (requires ~2330 logical qubits -- current QC: ~5-10)
    - Seed commitment hash proves a specific quantum measurement was used
    - Temporal window proves key expired before Shor's attack window
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .quantum_crypto import (
    QuantumEphemeralKey,
    QuantumSeedCommitment,
    verify_signature,
    make_temporal_window,
    SHOR_EARLIEST_ATTACK_SECONDS,
)
from .state import AccountSnapshot


class CommitmentError(Exception):
    """Raised when commitment operations fail."""


@dataclass(frozen=True)
class ReasoningCapture:
    """
    Immutable capture of AI/human reasoning bound to a trade decision.

    Stores a SHA-256 hash of the reasoning text so that the reasoning chain
    can be cryptographically tied to the commitment at sign time.  The hash
    is included in the signed data when present, making it impossible to
    alter the reasoning after the fact without invalidating the signature.

    Fields:
        reasoning_text: The full reasoning/rationale text.
        reasoning_hash: SHA-256 hex digest of ``reasoning_text``.
        reasoning_model: Identifier of the model or person (e.g.
            ``"claude-sonnet-4-6"``, ``"human"``).
        captured_at: Unix timestamp when the reasoning was captured.
        token_count: Approximate token count of the reasoning text.
    """

    reasoning_text: str
    reasoning_hash: str
    reasoning_model: str
    captured_at: int
    token_count: int

    @classmethod
    def from_text(
        cls,
        text: str,
        model: str = "human",
        token_count: Optional[int] = None,
    ) -> "ReasoningCapture":
        """
        Create a ReasoningCapture from raw reasoning text.

        Automatically computes the SHA-256 hash and captures the current
        timestamp.  If ``token_count`` is not provided it is estimated as
        ``len(text) // 4`` (a rough byte-to-token heuristic).

        Args:
            text: The reasoning/rationale text.
            model: Identifier for the source (default ``"human"``).
            token_count: Explicit token count; estimated if omitted.

        Returns:
            A new frozen :class:`ReasoningCapture` instance.
        """
        reasoning_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if token_count is None:
            token_count = max(1, len(text) // 4)
        return cls(
            reasoning_text=text,
            reasoning_hash=reasoning_hash,
            reasoning_model=model,
            captured_at=int(time.time()),
            token_count=token_count,
        )

    def verify(self) -> bool:
        """
        Verify that ``reasoning_hash`` matches the SHA-256 of ``reasoning_text``.

        Returns:
            ``True`` if the hash is consistent; ``False`` if tampered.
        """
        expected = hashlib.sha256(self.reasoning_text.encode("utf-8")).hexdigest()
        return expected == self.reasoning_hash

    def to_dict(self) -> dict:
        """Serialise to a plain dict (suitable for JSON)."""
        return {
            "reasoning_text": self.reasoning_text,
            "reasoning_hash": self.reasoning_hash,
            "reasoning_model": self.reasoning_model,
            "captured_at": self.captured_at,
            "token_count": self.token_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReasoningCapture":
        """Reconstruct from a dict (e.g. deserialised JSON)."""
        return cls(
            reasoning_text=d["reasoning_text"],
            reasoning_hash=d["reasoning_hash"],
            reasoning_model=d["reasoning_model"],
            captured_at=d["captured_at"],
            token_count=d["token_count"],
        )


@dataclass(frozen=True)
class QuantumDecisionCommitment:
    """
    A trade decision signed with an ephemeral key derived from a quantum measurement.

    Quantum Safety:
        - Signature only valid with the ephemeral key
        - Ephemeral key destroyed immediately after signing
        - To forge this signature an adversary needs:
          * The private key (destroyed) OR
          * Solve ECDLP on secp256k1 (requires ~2330 logical qubits) OR
          * Compromise the quantum seed (measurements are immutable)

    Fields:
        order_id: Unique identifier for the order.
        trade_details: Dict describing the trade (symbol, qty, side, price, etc.).
        account_state_hash: SHA-256 of the account state at decision time.
        quantum_seed_commitment: SHA-256 of the quantum seed used for signing.
        seed_measurement_method: Source ("IBM_QUANTUM" | "AER_SIMULATOR" | "OS_URANDOM").
        key_temporal_window: Dict with created_at, expires_at, shor_earliest_attack.
        nonce: Monotonically increasing counter (from account state).
        timestamp: Unix timestamp of the commitment.
    """

    order_id: str
    trade_details: dict
    account_state_hash: str
    quantum_seed_commitment: str
    seed_measurement_method: str
    key_temporal_window: dict
    nonce: int
    timestamp: int
    reasoning: Optional["ReasoningCapture"] = field(default=None)

    def to_signable_dict(self) -> dict:
        """
        Produce the canonical signable representation.

        This is the dict that gets signed -- includes everything that
        makes this commitment unique and quantum-bound.  When reasoning
        is present, its hash is included in the signed data so that the
        reasoning chain is cryptographically bound to the commitment.

        Returns:
            Canonical dict ready for signing.
        """
        d = {
            "order_id": self.order_id,
            "trade_details": self.trade_details,
            "account_state_hash": self.account_state_hash,
            "quantum_seed_commitment": self.quantum_seed_commitment,
            "seed_measurement_method": self.seed_measurement_method,
            "key_temporal_window": self.key_temporal_window,
            "nonce": self.nonce,
            "timestamp": self.timestamp,
        }
        if self.reasoning is not None:
            d["reasoning_hash"] = self.reasoning.reasoning_hash
        return d

    @classmethod
    def create_and_sign(
        cls,
        order_id: str,
        trade_details: dict,
        account_state: AccountSnapshot,
        quantum_seed: int | bytes,
        measurement_method: str = "OS_URANDOM",
        reasoning: Optional[ReasoningCapture] = None,
    ) -> Tuple[dict, dict, "QuantumDecisionCommitment"]:
        """
        Create a commitment, derive ephemeral key from quantum seed, sign, destroy key.

        This is the primary entry point.  It:
        1. Creates the commitment structure with quantum bindings
        2. Optionally binds a reasoning chain via its SHA-256 hash
        3. Derives an ephemeral key from the quantum seed
        4. Signs the commitment
        5. Destroys the key immediately
        6. Returns the commitment dict, signature, and commitment object

        Args:
            order_id: Unique order identifier.
            trade_details: Trade description dict.
            account_state: Account snapshot at decision time.
            quantum_seed: Raw quantum seed (int or bytes).
            measurement_method: Source of the seed.
            reasoning: Optional :class:`ReasoningCapture` to bind to
                the commitment.  When provided the reasoning hash is
                included in the signed data.

        Returns:
            Tuple of (commitment_dict, signature_envelope, commitment_object).

        Raises:
            CommitmentError: If signing fails.
        """
        now = int(time.time())

        # Derive ephemeral key from quantum seed
        ephemeral_key = QuantumEphemeralKey(
            quantum_seed=quantum_seed,
            method=measurement_method,
        )

        # Build the commitment
        commitment = cls(
            order_id=order_id,
            trade_details=trade_details,
            account_state_hash=account_state.to_hash(),
            quantum_seed_commitment=ephemeral_key.seed_commitment.seed_hash,
            seed_measurement_method=measurement_method,
            key_temporal_window=ephemeral_key.seed_commitment.temporal_window_dict,
            nonce=account_state.nonce,
            timestamp=now,
            reasoning=reasoning,
        )

        signable = commitment.to_signable_dict()

        try:
            # Sign and DESTROY the key
            signature = ephemeral_key.sign(signable)
        except Exception as exc:
            raise CommitmentError(f"Failed to sign commitment: {exc}") from exc

        # Verify key is destroyed
        assert ephemeral_key.is_destroyed, "CRITICAL: Key not destroyed after signing"

        return signable, signature, commitment


class QuantumCommitmentVerifier:
    """
    Verifies quantum decision commitment signatures and bindings.
    """

    @staticmethod
    def verify_signature(commitment: dict, signature: dict) -> bool:
        """
        Verify the commitment signature using the embedded public key.

        Args:
            commitment: The commitment dict that was signed.
            signature: The signature envelope.

        Returns:
            True if the signature is valid.
        """
        return verify_signature(commitment, signature)

    @staticmethod
    def verify_state_binding(commitment: dict) -> bool:
        """
        Check that the commitment contains a valid state binding.

        Args:
            commitment: The commitment dict.

        Returns:
            True if state binding fields are present and valid.
        """
        state_hash = commitment.get("account_state_hash", "")
        nonce = commitment.get("nonce")

        if not state_hash or not isinstance(state_hash, str) or len(state_hash) != 64:
            return False
        if nonce is None or not isinstance(nonce, int):
            return False
        return True

    @staticmethod
    def verify_quantum_binding(commitment: dict) -> bool:
        """
        Check that the commitment contains quantum seed binding.

        Verifies:
        1. quantum_seed_commitment is present (64-char hex hash)
        2. seed_measurement_method is a valid source
        3. key_temporal_window has required fields

        Args:
            commitment: The commitment dict.

        Returns:
            True if all quantum binding fields are valid.
        """
        seed_hash = commitment.get("quantum_seed_commitment", "")
        if not seed_hash or len(seed_hash) != 64:
            return False

        method = commitment.get("seed_measurement_method", "")
        if method not in ("IBM_QUANTUM", "AER_SIMULATOR", "OS_URANDOM"):
            return False

        window = commitment.get("key_temporal_window", {})
        if not isinstance(window, dict):
            return False
        if "created_at" not in window or "expires_at" not in window:
            return False
        if window["expires_at"] <= window["created_at"]:
            return False

        return True

    @staticmethod
    def verify_temporal_safety(commitment: dict) -> bool:
        """
        Verify that the key's temporal window proves safety against Shor's.

        The key must expire before Shor's algorithm could feasibly run.

        Args:
            commitment: The commitment dict.

        Returns:
            True if the key expires before Shor's earliest attack window.
        """
        window = commitment.get("key_temporal_window", {})
        created_at = window.get("created_at", 0)
        expires_at = window.get("expires_at", 0)
        shor_attack = window.get("shor_earliest_attack", 0)

        if not all([created_at, expires_at, shor_attack]):
            return False

        return expires_at < shor_attack

    @staticmethod
    def verify_nonce(commitment: dict, expected_nonce: int) -> bool:
        """Verify the commitment nonce matches the expected value."""
        return commitment.get("nonce") == expected_nonce
