"""Type stubs for aether_protocol.async_protocol"""

from pathlib import Path
from typing import Optional, Tuple

from .commitment import ReasoningCapture
from .quantum_backend import QuantumSeedResult

class AsyncQuantumProtocol:
    def __init__(
        self,
        log_path: str | Path = "audit.jsonl",
        seed_method: str = "OS_URANDOM",
        max_file_size_mb: int = 100,
    ) -> None: ...
    async def get_seed(
        self, method: Optional[str] = None
    ) -> QuantumSeedResult: ...
    async def commit(
        self,
        seed: QuantumSeedResult,
        decision_params: dict,
        reasoning: Optional[ReasoningCapture] = None,
    ) -> Tuple[dict, dict]: ...
    async def execute(
        self,
        seed: QuantumSeedResult,
        commitment: dict,
        commitment_sig: dict,
        execution_params: dict,
    ) -> Tuple[dict, dict]: ...
    async def settle(
        self,
        seed: QuantumSeedResult,
        commitment: dict,
        commitment_sig: dict,
        attestation: dict,
        attestation_sig: dict,
        outcome: dict,
    ) -> Tuple[dict, dict]: ...
    async def query_log(
        self,
        record_type: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        seed_method: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]: ...
    async def get_record(self, record_id: str) -> dict | None: ...
    async def verify(self, order_id: str) -> dict: ...
    async def generate_dispute_report(
        self,
        order_id: str,
        reasoning: Optional[dict] = None,
        timestamp_token: Optional[dict] = None,
    ) -> bytes: ...
