"""Type stubs for aether_protocol.state"""

class StateError(Exception): ...

class AccountSnapshot:
    capital: float
    equity: float
    open_positions: tuple
    risk_used: float
    risk_limit: float
    nonce: int
    timestamp: int
    def __init__(
        self,
        capital: float,
        equity: float,
        open_positions: tuple,
        risk_used: float,
        risk_limit: float,
        nonce: int,
        timestamp: int,
    ) -> None: ...
    def to_json(self) -> dict: ...
    def to_hash(self) -> str: ...
    @staticmethod
    def from_dict(data: dict) -> AccountSnapshot: ...

class QuantumStateSnapshot:
    account_snapshot: AccountSnapshot
    quantum_seed_commitment: str
    seed_measurement_method: str
    def __init__(
        self,
        account_snapshot: AccountSnapshot,
        quantum_seed_commitment: str,
        seed_measurement_method: str,
    ) -> None: ...
    def to_json(self) -> dict: ...
    def to_hash(self) -> str: ...
