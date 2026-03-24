"""
aether_protocol/state.py

Quantum-aware account state snapshots.

AccountSnapshot: immutable record of account state at a point in time.
QuantumStateSnapshot: account state + quantum seed context, used to
    bind trade decisions to both the account state AND the quantum
    measurement that generated the signing key.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class StateError(Exception):
    """Raised when state operations fail."""


@dataclass(frozen=True)
class AccountSnapshot:
    """
    Immutable snapshot of account state at decision time.

    Fields:
        capital: Available capital (USD or base currency).
        equity: Total account equity.
        open_positions: Tuple of position dicts (tuple for immutability).
        risk_used: Current risk utilisation (0.0 - 1.0).
        risk_limit: Maximum allowed risk (0.0 - 1.0).
        nonce: Monotonically increasing counter for replay prevention.
        timestamp: Unix timestamp of snapshot creation.
    """

    capital: float
    equity: float
    open_positions: tuple  # tuple of dicts for immutability
    risk_used: float
    risk_limit: float
    nonce: int
    timestamp: int

    def __post_init__(self) -> None:
        """Validate field ranges."""
        if self.capital < 0:
            raise StateError("capital cannot be negative")
        if self.equity < 0:
            raise StateError("equity cannot be negative")
        if not (0.0 <= self.risk_used <= 1.0):
            raise StateError("risk_used must be between 0.0 and 1.0")
        if not (0.0 <= self.risk_limit <= 1.0):
            raise StateError("risk_limit must be between 0.0 and 1.0")
        if self.nonce < 0:
            raise StateError("nonce cannot be negative")

    def to_json(self) -> dict:
        """
        Canonical JSON-serialisable dict representation.

        Returns:
            Dictionary with all fields in a deterministic layout.
        """
        return {
            "capital": self.capital,
            "equity": self.equity,
            "open_positions": list(self.open_positions),
            "risk_used": self.risk_used,
            "risk_limit": self.risk_limit,
            "nonce": self.nonce,
            "timestamp": self.timestamp,
        }

    def to_hash(self) -> str:
        """
        Compute canonical SHA-256 hash of the snapshot.

        The hash is deterministic: same fields always produce the same hash.

        Returns:
            Hex-encoded SHA-256 digest of the canonical JSON form.
        """
        canonical = json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def from_dict(data: dict) -> "AccountSnapshot":
        """
        Reconstruct an AccountSnapshot from a dict.

        Args:
            data: Dictionary with snapshot fields.

        Returns:
            A frozen AccountSnapshot instance.

        Raises:
            StateError: If required fields are missing.
        """
        required = {"capital", "equity", "open_positions", "risk_used",
                     "risk_limit", "nonce", "timestamp"}
        missing = required - set(data.keys())
        if missing:
            raise StateError(f"Missing required fields: {missing}")

        return AccountSnapshot(
            capital=float(data["capital"]),
            equity=float(data["equity"]),
            open_positions=tuple(data["open_positions"]),
            risk_used=float(data["risk_used"]),
            risk_limit=float(data["risk_limit"]),
            nonce=int(data["nonce"]),
            timestamp=int(data["timestamp"]),
        )


@dataclass(frozen=True)
class QuantumStateSnapshot:
    """
    Account state bound to a quantum cryptographic context.

    Combines the account snapshot with the quantum seed commitment hash
    and measurement method, proving that the state was captured at the
    same time a specific quantum measurement was taken.

    Fields:
        account_snapshot: The account state at decision time.
        quantum_seed_commitment: SHA-256 hash of the quantum seed used.
        seed_measurement_method: Source of the quantum seed
            ("IBM_QUANTUM" | "AER_SIMULATOR" | "OS_URANDOM").
    """

    account_snapshot: AccountSnapshot
    quantum_seed_commitment: str
    seed_measurement_method: str

    def to_json(self) -> dict:
        """Canonical JSON-serialisable representation."""
        return {
            "account_snapshot": self.account_snapshot.to_json(),
            "quantum_seed_commitment": self.quantum_seed_commitment,
            "seed_measurement_method": self.seed_measurement_method,
        }

    def to_hash(self) -> str:
        """
        Hash combining account state and quantum context.

        Returns:
            Hex-encoded SHA-256 digest.
        """
        canonical = json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
