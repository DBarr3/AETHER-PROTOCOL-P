"""Type stubs for aether_protocol.dispute_report"""

from typing import Optional

class DisputeReportError(Exception): ...

class DisputeReportGenerator:
    def __init__(self, title_prefix: str = "AETHER-PROTOCOL-L") -> None: ...
    def generate(
        self,
        order_id: str,
        flow: dict,
        verification: dict,
        reasoning: Optional[dict] = None,
        timestamp_token: Optional[dict] = None,
    ) -> bytes: ...
