"""
quantum_session.py

IBM hard-cap session manager for AETHER-PROTOCOL-L.

Enforces exactly 1 IBM Quantum call per session. The 30-qubit entropy
circuit is deterministic in architecture -- 1 batch run suffices. Results
are cached and shared across all FastAPI endpoints via an asyncio.Lock.

Mirrors AETHER-PREDATOR naming: _ibm_submit_single, initialize_batch_session,
get_batch_result.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from typing import Any, List, Optional

# Protocol variant: "C" = CSPRNG (default), "L" = quantum
PROTOCOL_VARIANT = os.getenv("AETHER_PROTOCOL_VARIANT", "C")

# ── Suppress qiskit_ibm_runtime INFO/WARNING spam ─────────────────────────
if PROTOCOL_VARIANT == "L":
    logging.getLogger('qiskit_ibm_runtime').setLevel(logging.ERROR)
    logging.getLogger('qiskit_ibm_provider').setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


class QuantumSessionManager:
    """
    IBM hard-cap session manager.

    Guarantees at most IBM_CALL_LIMIT IBM Quantum API calls per session
    instance. All results are pre-fetched in a single batch and served
    from cache thereafter.
    """

    # ── IBM billing hard cap ─────────────────────────────────────────
    IBM_CALL_LIMIT: int = 1
    _ibm_calls_this_session: int = 0

    def __init__(self) -> None:
        self._ibm_calls_this_session = 0
        self._batch_results: List[dict] = []
        self._batch_job_id: str = ""
        self._initialized: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

    # ── IBM hard cap enforcement ─────────────────────────────────────

    def _ibm_submit_single(self, circuits: list, service):
        """
        The ONE and ONLY entry point for IBM calls. Hard cap enforced.

        Parameters
        ----------
        circuits : list
            List of (circuit,) PUBs to submit.
        service : QiskitRuntimeService
            Active IBM Quantum service instance.

        Returns
        -------
        Job result from SamplerV2.

        Raises
        ------
        RuntimeError
            If this is the 2nd+ call (IBM HARD CAP VIOLATED).
        """
        self._ibm_calls_this_session += 1
        if self._ibm_calls_this_session > self.IBM_CALL_LIMIT:
            raise RuntimeError(
                f"IBM HARD CAP VIOLATED: call #{self._ibm_calls_this_session} "
                f"attempted (limit: {self.IBM_CALL_LIMIT}). "
                f"All IBM calls must happen inside initialize_batch_session() only. "
                f"This is a billing protection -- fix the code path that triggered "
                f"this before running again."
            )
        logger.info(
            "[IBM] Submitting call #%d/%d",
            self._ibm_calls_this_session, self.IBM_CALL_LIMIT,
        )
        from qiskit_ibm_runtime import SamplerV2

        backend = service.backend('ibm_marrakesh')
        sampler = SamplerV2(backend)
        job = sampler.run(circuits, shots=1)
        return job

    # ── Batch session pre-generation ─────────────────────────────────

    def initialize_batch_session(
        self,
        max_cycles: int = 100,
        service=None,
        n_qubits: int = 30,
    ) -> str:
        """
        Build circuits and run a SINGLE IBM batch (or Aer fallback).

        For IBM (service is not None):
            Builds max_cycles circuits, submits as one SamplerV2 batch
            via _ibm_submit_single, and pre-fetches all results.

        For Aer fallback (service is None):
            Runs circuits locally on AerSimulator. Zero IBM calls.

        Parameters
        ----------
        max_cycles : int
            Number of circuits to pre-generate (default 100).
        service : QiskitRuntimeService, optional
            If provided, uses IBM hardware. If None, falls back to Aer.
        n_qubits : int
            Number of qubits per circuit (default 30).

        Returns
        -------
        str
            Batch job ID.
        """
        import secrets

        # ── Protocol-C: pure CSPRNG, no circuits needed ───────────────
        if PROTOCOL_VARIANT == "C":
            self._batch_results = []
            for _ in range(max_cycles):
                random_bytes = secrets.token_bytes(32)
                seed_int = int.from_bytes(random_bytes, "big")
                self._batch_results.append({
                    "seed_int": seed_int,
                    "seed_bytes": random_bytes,
                    "raw_bitstring": None,
                    "method": "CSPRNG",
                    "backend_name": "csprng_os_urandom",
                    "n_qubits": 0,
                    "job_id": None,
                    "timestamp": int(time.time()),
                    "circuit_depth": 0,
                })
            self._batch_job_id = f"csprng_batch_{max_cycles}"
            self._initialized = True
            logger.info(
                "[QUANTUM-SESSION] CSPRNG batch: %d seeds | 0 IBM calls | Protocol-C",
                max_cycles,
            )
            return self._batch_job_id

        # ── Protocol-L: quantum circuit paths ─────────────────────────
        from aether_protocol.quantum_backend import _build_entropy_circuit, _bitstring_to_seed

        circuits = []
        for _ in range(max_cycles):
            qc = _build_entropy_circuit(n_qubits)
            circuits.append(qc)

        if service is not None:
            # ── IBM hardware path ────────────────────────────────────
            from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

            backend_obj = service.backend('ibm_marrakesh')
            pm = generate_preset_pass_manager(
                optimization_level=1,
                backend=backend_obj,
            )

            pubs = []
            for qc in circuits:
                transpiled = pm.run(qc)
                pubs.append((transpiled,))

            job = self._ibm_submit_single(pubs, service)
            result = job.result()
            self._batch_job_id = (
                job.job_id()
                if hasattr(job, 'job_id') and callable(job.job_id)
                else f"ibm_batch_{id(job)}"
            )

            self._batch_results = []
            for i in range(max_cycles):
                pub_result = result[i]
                data_bin = pub_result.data
                bitarray = None
                for attr_name in dir(data_bin):
                    if attr_name.startswith("_"):
                        continue
                    attr = getattr(data_bin, attr_name)
                    if hasattr(attr, "get_bitstrings"):
                        bitarray = attr
                        break
                if bitarray is not None:
                    raw_bitstring = bitarray.get_bitstrings()[0]
                else:
                    raw_bitstring = "0" * n_qubits

                seed_int, seed_bytes = _bitstring_to_seed(raw_bitstring)
                self._batch_results.append({
                    "seed_int": seed_int,
                    "seed_bytes": seed_bytes,
                    "raw_bitstring": raw_bitstring,
                    "method": "IBM_QUANTUM",
                    "backend_name": "ibm_marrakesh",
                    "n_qubits": n_qubits,
                    "job_id": self._batch_job_id,
                    "timestamp": int(time.time()),
                    "circuit_depth": circuits[i].depth(),
                })

            logger.info(
                "[QUANTUM-SESSION] IBM batch: %d circuits | job=%s | 1 API call",
                max_cycles, self._batch_job_id,
            )

        else:
            # ── Aer fallback (zero IBM calls) ────────────────────────
            try:
                from qiskit_aer import AerSimulator
                sim = AerSimulator(method="automatic")
            except ImportError:
                # Pure classical fallback
                import secrets
                self._batch_results = []
                for i in range(max_cycles):
                    random_bytes = secrets.token_bytes(32)
                    seed_int = int.from_bytes(random_bytes, "big")
                    self._batch_results.append({
                        "seed_int": seed_int,
                        "seed_bytes": random_bytes,
                        "raw_bitstring": None,
                        "method": "OS_URANDOM",
                        "backend_name": "os_urandom",
                        "n_qubits": 0,
                        "job_id": None,
                        "timestamp": int(time.time()),
                        "circuit_depth": 0,
                    })
                self._batch_job_id = f"classical_fallback_{max_cycles}"
                self._initialized = True
                return self._batch_job_id

            self._batch_results = []
            for i, qc in enumerate(circuits):
                job = sim.run(qc, shots=1)
                counts = job.result().get_counts()
                raw_bitstring = list(counts.keys())[0]
                seed_int, seed_bytes = _bitstring_to_seed(raw_bitstring)
                self._batch_results.append({
                    "seed_int": seed_int,
                    "seed_bytes": seed_bytes,
                    "raw_bitstring": raw_bitstring,
                    "method": "AER_SIMULATOR",
                    "backend_name": "aer_simulator",
                    "n_qubits": n_qubits,
                    "job_id": None,
                    "timestamp": int(time.time()),
                    "circuit_depth": qc.depth(),
                })

            self._batch_job_id = f"aer_batch_{max_cycles}"
            logger.info(
                "[QUANTUM-SESSION] Aer batch: %d circuits | 0 IBM calls",
                max_cycles,
            )

        self._initialized = True
        return self._batch_job_id

    # ── Cached result lookup (zero IBM calls) ────────────────────────

    def get_batch_result(self, cycle: int) -> dict:
        """
        Get pre-fetched quantum result for a cycle. ZERO IBM calls.

        Parameters
        ----------
        cycle : int
            Cycle index (wraps around via modulo).

        Returns
        -------
        dict
            Result dict with seed_int, seed_bytes, raw_bitstring, etc.

        Raises
        ------
        RuntimeError
            If initialize_batch_session() has not been called.
        """
        if not self._batch_results:
            raise RuntimeError(
                "initialize_batch_session() must be called before get_batch_result(). "
                "No batch results available."
            )
        idx = cycle % len(self._batch_results)
        return self._batch_results[idx]

    # ── Async cache-or-initialize for FastAPI ────────────────────────

    async def get_cached_or_initialize(
        self,
        service=None,
        n_qubits: int = 30,
    ) -> List[dict]:
        """
        asyncio.Lock-guarded initialization.

        First caller triggers initialize_batch_session(). All subsequent
        callers receive the cached results immediately.

        Parameters
        ----------
        service : QiskitRuntimeService, optional
            If provided, uses IBM hardware. If None, Aer fallback.
        n_qubits : int
            Number of qubits (default 30).

        Returns
        -------
        list[dict]
            All pre-generated batch results.
        """
        async with self._lock:
            if not self._initialized:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self.initialize_batch_session(
                        max_cycles=100,
                        service=service,
                        n_qubits=n_qubits,
                    ),
                )
        return self._batch_results
