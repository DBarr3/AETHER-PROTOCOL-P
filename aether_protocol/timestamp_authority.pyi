"""Type stubs for aether_protocol.timestamp_authority"""

from typing import Optional

class TimestampToken:
    tsa_url: str
    token_bytes: bytes
    token_hex: str
    stamped_at: int
    hash_algorithm: str
    message_imprint: str
    def __init__(
        self,
        tsa_url: str,
        token_bytes: bytes,
        token_hex: str,
        stamped_at: int,
        hash_algorithm: str,
        message_imprint: str,
    ) -> None: ...
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> TimestampToken: ...

class TimestampError(Exception): ...

class RFC3161TimestampAuthority:
    DEFAULT_TSA_URL: str
    FALLBACK_TSA_URL: str
    def __init__(
        self,
        tsa_url: Optional[str] = None,
        fallback_url: Optional[str] = None,
        timeout: int = 10,
    ) -> None: ...
    def stamp(self, data: bytes) -> TimestampToken: ...
    def verify(self, data: bytes, token: TimestampToken) -> bool: ...
