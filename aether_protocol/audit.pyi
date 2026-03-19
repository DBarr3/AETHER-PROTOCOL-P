"""Type stubs for aether_protocol.audit"""

from pathlib import Path
from typing import Any, Dict, List, Optional

# Phase label constants
PHASE_COMMITMENT: str
PHASE_EXECUTION: str
PHASE_SETTLEMENT: str

class AuditError(Exception): ...

class AuditEntry:
    timestamp: int
    phase: str
    order_id: str
    data: dict
    signature: dict
    quantum_proof: dict
    def __init__(
        self,
        timestamp: int,
        phase: str,
        order_id: str,
        data: dict,
        signature: dict,
        quantum_proof: dict,
    ) -> None: ...
    def to_json(self) -> dict: ...
    @staticmethod
    def from_dict(d: dict) -> AuditEntry: ...

class AuditLog:
    def __init__(
        self,
        log_path: str | Path,
        max_file_size_mb: int = 100,
    ) -> None: ...
    @property
    def path(self) -> Path: ...
    def append_commitment(self, commitment: dict, signature: dict) -> None: ...
    def append_execution(self, execution: dict, signature: dict) -> None: ...
    def append_settlement(self, settlement: dict, signature: dict) -> None: ...
    def read_all(self) -> List[AuditEntry]: ...
    def read_by_order_id(self, order_id: str) -> List[AuditEntry]: ...
    def get_trade_flow(self, order_id: str) -> dict: ...
    def query(
        self,
        record_type: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        seed_method: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]: ...
    def get_by_id(self, record_id: str) -> dict | None: ...
    def list_archives(self) -> list[str]: ...
