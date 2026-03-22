"""
aether_protocol/async_protocol.py

Async interface for the AETHER-PROTOCOL-L quantum trade protocol.

All blocking operations (seed generation, signing, audit I/O) run in a
thread pool via ``asyncio.get_running_loop().run_in_executor`` so the
event loop is never blocked.  No new protocol logic is introduced --
this module is a pure async wrapper around the existing synchronous
classes.

Usage::

    protocol = AsyncQuantumProtocol(log_path="audit.jsonl")

    seed = await protocol.get_seed()
    c, c_sig = await protocol.commit(seed, {
        "order_id": "order_001",
        "trade_details": {"symbol": "YM", "qty": 5, "side": "long", "price": 34000},
        "account_state": {"capital": 100_000, ...},
    })
    result = await protocol.verify("order_001")
"""

from __future__ import annotations

import asyncio
import functools
import os
import time
from pathlib import Path
from typing import Any, Optional, Tuple

from .audit import AuditLog
from .commitment import QuantumDecisionCommitment, ReasoningCapture
from .execution import ExecutionResult, QuantumExecutionAttestation
from .quantum_backend import QuantumSeedResult, generate_quantum_seed
from .settlement import QuantumSettlementRecord
from .state import AccountSnapshot
from .verify import AuditVerifier

# Protocol variant: "C" = CSPRNG (default), "L" = quantum
PROTOCOL_VARIANT = os.getenv("AETHER_PROTOCOL_VARIANT", "C")

try:
    from .dispute_report import DisputeReportGenerator
    _REPORTLAB_AVAILABLE = True
except Exception:
    _REPORTLAB_AVAILABLE = False


class AsyncQuantumProtocol:
    """
    Async wrapper around the synchronous AETHER-PROTOCOL-L classes.

    Every method delegates to the corresponding synchronous call inside
    ``run_in_executor(None, ...)`` so the event loop is never blocked.

    Args:
        log_path: Path to the JSONL audit log (default: ``"audit.jsonl"``).
        seed_method: Default entropy source (``"IBM_QUANTUM"``,
            ``"AER_SIMULATOR"``, or ``"OS_URANDOM"``).
        max_file_size_mb: Audit log rotation threshold (default 100 MB).
    """

    def __init__(
        self,
        log_path: str | Path = "audit.jsonl",
        seed_method: str | None = None,
        max_file_size_mb: int = 100,
    ) -> None:
        self._audit_log = AuditLog(log_path, max_file_size_mb=max_file_size_mb)
        # Default seed method: CSPRNG for Protocol-C, OS_URANDOM for Protocol-L
        if seed_method is None:
            self._seed_method = "CSPRNG" if PROTOCOL_VARIANT == "C" else "OS_URANDOM"
        else:
            self._seed_method = seed_method
        self._verifier = AuditVerifier()

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    async def _run(fn, *args, **kwargs):
        """Run *fn* in the default thread-pool executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, functools.partial(fn, *args, **kwargs)
        )

    # ── seed ──────────────────────────────────────────────────────────

    async def get_seed(
        self, method: Optional[str] = None
    ) -> QuantumSeedResult:
        """
        Generate a quantum seed.

        Args:
            method: Entropy source override; defaults to the instance's
                ``seed_method``.

        Returns:
            :class:`QuantumSeedResult` with full provenance metadata.
        """
        m = method or self._seed_method
        return await self._run(generate_quantum_seed, method=m)

    # ── commit ────────────────────────────────────────────────────────

    async def commit(
        self,
        seed: QuantumSeedResult,
        decision_params: dict,
        reasoning: Optional[ReasoningCapture] = None,
    ) -> Tuple[dict, dict]:
        """
        Create a quantum decision commitment and append it to the audit log.

        Args:
            seed: Quantum seed for this phase.
            decision_params: Dict with keys ``order_id`` (str),
                ``trade_details`` (dict), ``account_state`` (dict -- fed
                to :meth:`AccountSnapshot.from_dict`).
            reasoning: Optional :class:`ReasoningCapture` to bind to
                the commitment.

        Returns:
            ``(commitment_dict, signature_dict)``
        """

        def _sync():
            snap = AccountSnapshot.from_dict(decision_params["account_state"])
            c_dict, c_sig, _ = QuantumDecisionCommitment.create_and_sign(
                order_id=decision_params["order_id"],
                trade_details=decision_params["trade_details"],
                account_state=snap,
                quantum_seed=seed.seed_int,
                measurement_method=seed.method,
                reasoning=reasoning,
            )
            self._audit_log.append_commitment(c_dict, c_sig)
            return c_dict, c_sig

        return await self._run(_sync)

    # ── execute ───────────────────────────────────────────────────────

    async def execute(
        self,
        seed: QuantumSeedResult,
        commitment: dict,
        commitment_sig: dict,
        execution_params: dict,
    ) -> Tuple[dict, dict]:
        """
        Create a quantum execution attestation and append it to the audit log.

        Args:
            seed: Quantum seed for this phase.
            commitment: Commitment dict from the commit phase.
            commitment_sig: Commitment signature dict.
            execution_params: Dict with keys ``order_id``, ``filled_qty``,
                ``fill_price``, ``new_account_state`` (dict).  Optional
                keys: ``execution_timestamp``, ``broker_response``.

        Returns:
            ``(attestation_dict, signature_dict)``
        """

        def _sync():
            er = ExecutionResult(
                order_id=execution_params["order_id"],
                filled_qty=execution_params["filled_qty"],
                fill_price=execution_params["fill_price"],
                execution_timestamp=execution_params.get(
                    "execution_timestamp", int(time.time())
                ),
                broker_response=execution_params.get("broker_response", {}),
            )
            snap_after = AccountSnapshot.from_dict(
                execution_params["new_account_state"]
            )
            att_dict, att_sig, _ = QuantumExecutionAttestation.create_and_sign(
                commitment_sig=commitment_sig,
                commitment_seed_hash=commitment["quantum_seed_commitment"],
                execution_result=er,
                new_account_state=snap_after,
                quantum_seed=seed.seed_int,
                measurement_method=seed.method,
            )
            self._audit_log.append_execution(att_dict, att_sig)
            return att_dict, att_sig

        return await self._run(_sync)

    # ── settle ────────────────────────────────────────────────────────

    async def settle(
        self,
        seed: QuantumSeedResult,
        commitment: dict,
        commitment_sig: dict,
        attestation: dict,
        attestation_sig: dict,
        outcome: dict,
    ) -> Tuple[dict, dict]:
        """
        Create a quantum settlement record and append it to the audit log.

        Args:
            seed: Quantum seed for this phase.
            commitment: Commitment dict.
            commitment_sig: Commitment signature dict.
            attestation: Execution attestation dict.
            attestation_sig: Execution attestation signature dict.
            outcome: Dict with keys ``order_id`` (str) and
                ``broker_sig`` (str).

        Returns:
            ``(settlement_dict, signature_dict)``
        """

        def _sync():
            s_dict, s_sig, _ = QuantumSettlementRecord.create_and_sign(
                order_id=outcome["order_id"],
                commitment_sig=commitment_sig,
                commitment_seed_hash=commitment["quantum_seed_commitment"],
                commitment_window=commitment["key_temporal_window"],
                execution_sig=attestation_sig,
                execution_seed_hash=attestation[
                    "execution_quantum_seed_commitment"
                ],
                execution_window=attestation["key_temporal_window"],
                broker_sig=outcome["broker_sig"],
                quantum_seed=seed.seed_int,
                measurement_method=seed.method,
            )
            self._audit_log.append_settlement(s_dict, s_sig)
            return s_dict, s_sig

        return await self._run(_sync)

    # ── query ─────────────────────────────────────────────────────────

    async def query_log(
        self,
        record_type: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        seed_method: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Query the audit log using the SQLite index.

        All parameters are optional filters.

        Returns:
            List of parsed record dicts.
        """
        return await self._run(
            self._audit_log.query,
            record_type=record_type,
            since=since,
            until=until,
            seed_method=seed_method,
            limit=limit,
        )

    async def get_record(self, record_id: str) -> dict | None:
        """
        Retrieve a single record by its record_id.

        Returns:
            Parsed record dict, or ``None`` if not found.
        """
        return await self._run(self._audit_log.get_by_id, record_id)

    # ── verify ────────────────────────────────────────────────────────

    async def verify(self, order_id: str) -> dict:
        """
        Verify a complete trade flow.

        Returns:
            Verification result dict (see :meth:`AuditVerifier.verify_trade_flow`).
        """
        return await self._run(
            self._verifier.verify_trade_flow, order_id, self._audit_log
        )

    # ── dispute report ─────────────────────────────────────────────

    async def generate_dispute_report(
        self,
        order_id: str,
        reasoning: Optional[dict] = None,
        timestamp_token: Optional[dict] = None,
    ) -> bytes:
        """
        Generate a PDF dispute report for a trade flow.

        Requires ``reportlab`` (install with ``pip install
        aether-protocol-l[compliance]``).

        Args:
            order_id: The order to generate a report for.
            reasoning: Optional reasoning capture dict.
            timestamp_token: Optional timestamp token dict.

        Returns:
            Raw PDF bytes.
        """

        def _sync():
            if not _REPORTLAB_AVAILABLE:
                raise ImportError(
                    "reportlab is required for PDF reports.  "
                    "Install with:  pip install aether-protocol-l[compliance]"
                )
            flow = self._audit_log.get_trade_flow(order_id)
            verification = self._verifier.verify_trade_flow(
                order_id, self._audit_log
            )
            gen = DisputeReportGenerator()
            return gen.generate(
                order_id=order_id,
                flow=flow,
                verification=verification,
                reasoning=reasoning,
                timestamp_token=timestamp_token,
            )

        return await self._run(_sync)
