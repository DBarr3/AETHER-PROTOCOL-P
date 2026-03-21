"""
AetherCloud-L — Vault Watcher
Monitors vault for unauthorized file system events.
Every file event is Protocol-L committed with source tagging
(AETHERCLOUD vs EXTERNAL) and severity classification.

Aether Systems LLC — Patent Pending
"""

import hashlib
import json
import logging
import os
import time
import threading
from pathlib import Path
from typing import Optional, Callable

from aether_protocol.audit import AuditLog
from aether_protocol.quantum_crypto import QuantumSeedCommitment
from config.settings import DEFAULT_AUDIT_DIR

logger = logging.getLogger("aethercloud.watcher")

# ── Sensitive file patterns ─────────────────────────
_SENSITIVE_EXTENSIONS = frozenset({
    ".env", ".pem", ".key", ".crt", ".pfx", ".p12",
    ".gpg", ".asc", ".keystore", ".jks",
})
_SENSITIVE_NAMES = frozenset({
    "credentials.json", ".env", ".env.local", ".env.production",
    "id_rsa", "id_ed25519", "authorized_keys",
    "secrets.yaml", "secrets.json", "vault.json",
})


def _is_sensitive_file(path: str) -> bool:
    """Check if a file path looks like it contains secrets."""
    p = Path(path)
    if p.suffix.lower() in _SENSITIVE_EXTENSIONS:
        return True
    if p.name.lower() in _SENSITIVE_NAMES:
        return True
    return False


class VaultWatcher:
    """
    Monitors the vault root directory for any file system events —
    including events that did NOT go through AetherCloud-L.

    If a file is accessed, modified, or deleted directly (bypassing
    the agent), the watcher detects it and creates an UNAUTHORIZED_ACCESS
    audit entry via Protocol-L.

    Source tagging:
      - AETHERCLOUD: operations registered via mark_authorized()
      - EXTERNAL: all other filesystem events (potential intrusion)

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

        # AetherCloud write registry — paths currently being written by our code
        self._aether_write_registry: set[str] = set()

        # Event counters
        self._total_events = 0
        self._external_events = 0

    # ── Authorization API ────────────────────────────

    def mark_authorized(self, operation_id: str) -> None:
        """Mark an operation as authorized (called by AetherVault before ops)."""
        self._authorized_ops.add(operation_id)

    def clear_authorized(self, operation_id: str) -> None:
        """Clear an authorized operation after completion."""
        self._authorized_ops.discard(operation_id)

    def register_aether_write(self, rel_path: str) -> None:
        """Register that AetherCloud is about to write to this path."""
        self._aether_write_registry.add(rel_path)

    def unregister_aether_write(self, rel_path: str) -> None:
        """Unregister after AetherCloud write completes."""
        self._aether_write_registry.discard(rel_path)

    # ── Source Classification ────────────────────────

    def _classify_source(self, rel_path: str) -> str:
        """Determine if a file event came from AetherCloud or external."""
        if rel_path in self._aether_write_registry:
            return "AETHERCLOUD"
        return "EXTERNAL"

    def _classify_severity(self, event_type: str, rel_path: str, source: str) -> str:
        """Assign severity based on event type, path, and source."""
        is_sensitive = _is_sensitive_file(rel_path)

        if source == "EXTERNAL":
            if "DELETE" in event_type:
                return "CRITICAL"
            if "MODIFY" in event_type:
                return "CRITICAL" if is_sensitive else "HIGH"
            if "ACCESS" in event_type or "READ" in event_type:
                return "HIGH" if is_sensitive else "MEDIUM"
            if "CREATE" in event_type:
                return "HIGH"
            return "MEDIUM"
        else:
            # AetherCloud operations are lower severity
            if is_sensitive:
                return "MEDIUM"
            return "LOW"

    # ── Protocol-L Commit ────────────────────────────

    def _commit_file_event(
        self, event_type: str, rel_path: str, source: str,
        severity: str, extra: Optional[dict] = None,
    ) -> str:
        """Create a full Protocol-L commitment for a file event."""
        event_data = {
            "event_type": event_type,
            "source": source,
            "path": rel_path,
            "severity": severity,
            "sensitive_file": _is_sensitive_file(rel_path),
            "vault_root": str(self._root),
            "watcher": True,
            "timestamp": time.time(),
        }
        if extra:
            event_data.update(extra)

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
        except Exception as e:
            logger.warning("Failed to commit file event: %s", e)

        self._total_events += 1
        if source == "EXTERNAL":
            self._external_events += 1

        return commitment_hash

    def _log_event(self, event_type: str, details: dict) -> str:
        """Log a watcher event via Protocol-L (backward-compatible wrapper)."""
        rel_path = details.get("path", "")
        source = self._classify_source(rel_path)
        severity = self._classify_severity(event_type, rel_path, source)
        return self._commit_file_event(event_type, rel_path, source, severity, details)

    # ── State Snapshot ───────────────────────────────

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
        """Compare current state to known state and detect changes."""
        alerts = []
        current = self._snapshot_state()

        # Detect new files
        for path, mtime in current.items():
            if path not in self._known_state:
                source = self._classify_source(path)
                severity = self._classify_severity("FILE_CREATED", path, source)
                alert = {
                    "type": "FILE_CREATED",
                    "path": path,
                    "mtime": mtime,
                    "source": source,
                    "severity": severity,
                }
                alerts.append(alert)
            elif mtime != self._known_state[path]:
                source = self._classify_source(path)
                severity = self._classify_severity("FILE_MODIFIED", path, source)
                alert = {
                    "type": "FILE_MODIFIED",
                    "path": path,
                    "old_mtime": self._known_state[path],
                    "new_mtime": mtime,
                    "source": source,
                    "severity": severity,
                }
                alerts.append(alert)

        # Detect deleted files
        for path in self._known_state:
            if path not in current:
                source = self._classify_source(path)
                severity = self._classify_severity("FILE_DELETED", path, source)
                alert = {
                    "type": "FILE_DELETED",
                    "path": path,
                    "source": source,
                    "severity": severity,
                }
                alerts.append(alert)

        self._known_state = current
        return alerts

    # ── Start / Stop ─────────────────────────────────

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
            logger.info("VaultWatcher started (watchdog mode)")
        except ImportError:
            # Fallback to polling if watchdog not installed
            self._thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._thread.start()
            logger.info("VaultWatcher started (polling mode)")

    def _poll_loop(self) -> None:
        """Polling fallback when watchdog is not available."""
        while self._running:
            time.sleep(5)
            alerts = self._check_changes()
            for alert in alerts:
                self._commit_file_event(
                    alert["type"], alert["path"],
                    alert.get("source", "EXTERNAL"),
                    alert.get("severity", "MEDIUM"),
                    alert,
                )
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
        logger.info("VaultWatcher stopped")

    # ── Event Handlers ───────────────────────────────

    def on_file_event(self, event_type: str, rel_path: str) -> None:
        """Handle a detected file event (from watchdog)."""
        mapped_type = f"DETECTED_{event_type.upper()}"
        source = self._classify_source(rel_path)
        severity = self._classify_severity(mapped_type, rel_path, source)

        self._commit_file_event(mapped_type, rel_path, source, severity, {
            "timestamp": time.time(),
        })

        alert = {
            "type": mapped_type,
            "path": rel_path,
            "source": source,
            "severity": severity,
            "timestamp": time.time(),
        }
        if self._on_alert:
            self._on_alert(alert)

    def on_file_accessed(self, path: str) -> None:
        """Triggered on any file access outside AetherCloud-L."""
        source = self._classify_source(path)
        severity = self._classify_severity("UNAUTHORIZED_ACCESS", path, source)
        commitment_hash = self._commit_file_event(
            "UNAUTHORIZED_ACCESS", path, source, severity,
        )
        alert = {
            "type": "UNAUTHORIZED_ACCESS",
            "path": path,
            "source": source,
            "severity": severity,
            "commitment_hash": commitment_hash,
        }
        if self._on_alert:
            self._on_alert(alert)

    def on_file_modified(self, path: str) -> None:
        """Triggered on any file modification outside AetherCloud-L."""
        source = self._classify_source(path)
        severity = self._classify_severity("UNAUTHORIZED_MODIFY", path, source)
        commitment_hash = self._commit_file_event(
            "UNAUTHORIZED_MODIFY", path, source, severity,
        )
        alert = {
            "type": "UNAUTHORIZED_MODIFY",
            "path": path,
            "source": source,
            "severity": severity,
            "commitment_hash": commitment_hash,
        }
        if self._on_alert:
            self._on_alert(alert)

    # ── Properties ───────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def total_events(self) -> int:
        return self._total_events

    @property
    def external_events(self) -> int:
        return self._external_events
