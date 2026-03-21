"""
AetherCloud-L — Read Detector (st_atime Polling)
Detects file reads that did NOT go through AetherCloud-L.
Polls st_atime on vault files and fires READ_DETECTED events
when access times change without an authorized operation.

Aether Systems LLC — Patent Pending
"""

import hashlib
import json
import os
import time
import threading
import logging
from pathlib import Path
from typing import Optional, Callable

from aether_protocol.audit import AuditLog
from aether_protocol.quantum_crypto import QuantumSeedCommitment
from config.settings import DEFAULT_AUDIT_DIR

logger = logging.getLogger("aethercloud.read_detector")


class ReadDetector:
    """
    Polls st_atime on all files in the vault root.
    When a file's atime changes AND the read was NOT authorized
    by AetherCloud-L, fires a READ_DETECTED event with full
    Protocol-L commitment.

    The detector maintains a registry of authorized reads.
    Call mark_authorized_read(path) BEFORE performing any
    AetherCloud-controlled read, then clear_authorized_read(path)
    after completion.
    """

    def __init__(
        self,
        vault_root: str,
        audit_log: Optional[AuditLog] = None,
        poll_interval: float = 10.0,  # seconds between polls
        on_read_detected: Optional[Callable[[dict], None]] = None,
    ):
        self._root = Path(vault_root).resolve()
        audit_dir = DEFAULT_AUDIT_DIR
        audit_dir.mkdir(parents=True, exist_ok=True)
        self._audit_log = audit_log or AuditLog(
            str(audit_dir / "read_detector_audit.jsonl")
        )
        self._poll_interval = poll_interval
        self._on_read_detected = on_read_detected
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # atime snapshot: {relative_path_str: last_known_atime}
        self._atime_state: dict[str, float] = {}

        # Authorized reads: paths that AetherCloud is currently reading
        self._authorized_reads: set[str] = set()

        # Stats
        self._total_detections = 0
        self._last_poll_time: Optional[float] = None

    def mark_authorized_read(self, rel_path: str) -> None:
        """Mark a file as being read by AetherCloud (suppresses detection)."""
        self._authorized_reads.add(rel_path)

    def clear_authorized_read(self, rel_path: str) -> None:
        """Clear authorized read flag after AetherCloud finishes reading."""
        self._authorized_reads.discard(rel_path)

    def _snapshot_atimes(self) -> dict[str, float]:
        """Capture current st_atime for all files in the vault."""
        state = {}
        if not self._root.exists():
            return state
        for f in self._root.rglob("*"):
            if f.is_file():
                try:
                    state[str(f.relative_to(self._root))] = f.stat().st_atime
                except OSError:
                    pass
        return state

    def _commit_read_event(self, rel_path: str, old_atime: float, new_atime: float) -> str:
        """Create a Protocol-L commitment for a detected read."""
        event_data = {
            "event_type": "READ_DETECTED",
            "source": "EXTERNAL",
            "path": rel_path,
            "old_atime": old_atime,
            "new_atime": new_atime,
            "delta_seconds": round(new_atime - old_atime, 3),
            "vault_root": str(self._root),
            "timestamp": time.time(),
            "severity": "MEDIUM",
        }

        commitment_hash = hashlib.sha256(
            json.dumps(event_data, sort_keys=True, default=str).encode()
        ).hexdigest()

        seed = os.urandom(32)
        seed_hash = hashlib.sha256(seed).hexdigest()
        now = int(time.time())
        seed_commitment = QuantumSeedCommitment(
            seed_hash, now, "OS_URANDOM", now, now + 3600
        )

        audit_entry = {
            "order_id": f"read_{commitment_hash[:12]}",
            "trade_details": event_data,
            "quantum_seed_commitment": seed_commitment.seed_hash,
            "seed_measurement_method": "OS_URANDOM",
            "timestamp": time.time(),
        }
        signature = {"commitment_hash": commitment_hash}

        try:
            self._audit_log.append_commitment(audit_entry, signature)
        except Exception as e:
            logger.warning("Failed to commit read event: %s", e)

        return commitment_hash

    def _check_reads(self) -> list[dict]:
        """Compare current atimes to snapshot and detect external reads."""
        detections = []
        current = self._snapshot_atimes()

        for path, atime in current.items():
            old_atime = self._atime_state.get(path)
            if old_atime is not None and atime != old_atime:
                # atime changed — was it authorized?
                if path not in self._authorized_reads:
                    commitment_hash = self._commit_read_event(path, old_atime, atime)
                    detection = {
                        "type": "READ_DETECTED",
                        "source": "EXTERNAL",
                        "path": path,
                        "old_atime": old_atime,
                        "new_atime": atime,
                        "commitment_hash": commitment_hash,
                        "timestamp": time.time(),
                    }
                    detections.append(detection)
                    self._total_detections += 1
                    logger.info(
                        "External read detected: %s (atime delta: %.1fs)",
                        path, atime - old_atime
                    )

        self._atime_state = current
        self._last_poll_time = time.time()
        return detections

    def start(self) -> None:
        """Start the read detector polling loop in a background thread."""
        if self._running:
            return

        # Take initial snapshot
        self._atime_state = self._snapshot_atimes()
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("ReadDetector started (interval=%.1fs, files=%d)",
                     self._poll_interval, len(self._atime_state))

    def _poll_loop(self) -> None:
        """Background polling loop."""
        while self._running:
            time.sleep(self._poll_interval)
            try:
                detections = self._check_reads()
                for det in detections:
                    if self._on_read_detected:
                        self._on_read_detected(det)
            except Exception as e:
                logger.error("ReadDetector poll error: %s", e)

    def stop(self) -> None:
        """Stop the read detector."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("ReadDetector stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def total_detections(self) -> int:
        return self._total_detections

    @property
    def monitored_files(self) -> int:
        return len(self._atime_state)

    @property
    def last_poll_time(self) -> Optional[float]:
        return self._last_poll_time
