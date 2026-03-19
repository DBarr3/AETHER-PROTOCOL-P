"""
AetherCloud-L — Vault Watcher
Monitors vault for unauthorized file system events.
Aether Systems LLC — Patent Pending
"""

import hashlib
import json
import os
import time
import threading
from pathlib import Path
from typing import Optional, Callable

from aether_protocol.audit import AuditLog
from aether_protocol.quantum_crypto import QuantumSeedCommitment
from config.settings import DEFAULT_AUDIT_DIR


class VaultWatcher:
    """
    Monitors the vault root directory for any file system events —
    including events that did NOT go through AetherCloud-L.

    If a file is accessed, modified, or deleted directly (bypassing
    the agent), the watcher detects it and creates an UNAUTHORIZED_ACCESS
    audit entry via Protocol-L.

    This is the hacker detection layer.
    """

    def __init__(
        self,
        vault_root: str,
        audit_log: Optional[AuditLog] = None,
        authorized_tokens: Optional[set] = None,
        on_alert: Optional[Callable[[dict], None]] = None,
    ):
        self._root = Path(vault_root).resolve()
        audit_dir = DEFAULT_AUDIT_DIR
        audit_dir.mkdir(parents=True, exist_ok=True)
        self._audit_log = audit_log or AuditLog(
            str(audit_dir / "watcher_audit.jsonl")
        )
        self._authorized_tokens = authorized_tokens or set()
        self._on_alert = on_alert
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._observer = None
        self._known_state: dict[str, float] = {}
        self._authorized_ops: set[str] = set()

    def mark_authorized(self, operation_id: str) -> None:
        """Mark an operation as authorized (called by AetherVault before ops)."""
        self._authorized_ops.add(operation_id)

    def clear_authorized(self, operation_id: str) -> None:
        """Clear an authorized operation after completion."""
        self._authorized_ops.discard(operation_id)

    def _log_event(self, event_type: str, details: dict) -> str:
        """Log a watcher event via Protocol-L."""
        event_data = {
            "event_type": event_type,
            "watcher": True,
            "timestamp": time.time(),
            **details,
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
            "order_id": f"watcher_{event_type.lower()}_{commitment_hash[:12]}",
            "trade_details": event_data,
            "quantum_seed_commitment": seed_commitment.seed_hash,
            "seed_measurement_method": "OS_URANDOM",
            "timestamp": time.time(),
        }
        signature = {"commitment_hash": commitment_hash}

        try:
            self._audit_log.append_commitment(audit_entry, signature)
        except Exception:
            pass

        return commitment_hash

    def _snapshot_state(self) -> dict[str, float]:
        """Capture current state of all files in vault."""
        state = {}
        if self._root.exists():
            for f in self._root.rglob("*"):
                if f.is_file():
                    try:
                        state[str(f.relative_to(self._root))] = f.stat().st_mtime
                    except OSError:
                        pass
        return state

    def _check_changes(self) -> list[dict]:
        """Compare current state to known state and detect unauthorized changes."""
        alerts = []
        current = self._snapshot_state()

        # Detect new files
        for path, mtime in current.items():
            if path not in self._known_state:
                alert = {
                    "type": "UNAUTHORIZED_CREATE",
                    "path": path,
                    "mtime": mtime,
                }
                alerts.append(alert)
            elif mtime != self._known_state[path]:
                alert = {
                    "type": "UNAUTHORIZED_MODIFY",
                    "path": path,
                    "old_mtime": self._known_state[path],
                    "new_mtime": mtime,
                }
                alerts.append(alert)

        # Detect deleted files
        for path in self._known_state:
            if path not in current:
                alert = {
                    "type": "UNAUTHORIZED_DELETE",
                    "path": path,
                }
                alerts.append(alert)

        self._known_state = current
        return alerts

    def start(self) -> None:
        """Start monitoring in background thread using polling."""
        if self._running:
            return

        self._known_state = self._snapshot_state()
        self._running = True

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class _Handler(FileSystemEventHandler):
                def __init__(self, watcher: "VaultWatcher"):
                    self._watcher = watcher

                def on_any_event(self, event):
                    if event.is_directory:
                        return
                    path = event.src_path
                    try:
                        rel = str(Path(path).relative_to(self._watcher._root))
                    except ValueError:
                        return
                    self._watcher.on_file_event(event.event_type, rel)

            handler = _Handler(self)
            self._observer = Observer()
            self._observer.schedule(handler, str(self._root), recursive=True)
            self._observer.daemon = True
            self._observer.start()
        except ImportError:
            # Fallback to polling if watchdog not installed
            self._thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._thread.start()

    def _poll_loop(self) -> None:
        """Polling fallback when watchdog is not available."""
        while self._running:
            time.sleep(5)
            alerts = self._check_changes()
            for alert in alerts:
                self._log_event(alert["type"], alert)
                if self._on_alert:
                    self._on_alert(alert)

    def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def on_file_event(self, event_type: str, rel_path: str) -> None:
        """Handle a detected file event."""
        alert = {
            "type": f"DETECTED_{event_type.upper()}",
            "path": rel_path,
            "timestamp": time.time(),
        }
        self._log_event(alert["type"], alert)
        if self._on_alert:
            self._on_alert(alert)

    def on_file_accessed(self, path: str) -> None:
        """Triggered on any file access outside AetherCloud-L."""
        commitment_hash = self._log_event("UNAUTHORIZED_ACCESS", {
            "path": path,
            "severity": "HIGH",
        })
        alert = {
            "type": "UNAUTHORIZED_ACCESS",
            "path": path,
            "commitment_hash": commitment_hash,
        }
        if self._on_alert:
            self._on_alert(alert)

    def on_file_modified(self, path: str) -> None:
        """Triggered on any file modification outside AetherCloud-L."""
        commitment_hash = self._log_event("UNAUTHORIZED_MODIFY", {
            "path": path,
            "severity": "CRITICAL",
        })
        alert = {
            "type": "UNAUTHORIZED_MODIFY",
            "path": path,
            "commitment_hash": commitment_hash,
        }
        if self._on_alert:
            self._on_alert(alert)

    @property
    def is_running(self) -> bool:
        return self._running
