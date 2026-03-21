"""
AetherCloud-L — Watcher Tests
Tests for unauthorized access detection.
"""

import time
import pytest
from pathlib import Path
from vault.watcher import VaultWatcher


class TestVaultWatcher:
    """Tests for VaultWatcher unauthorized access detection."""

    @pytest.fixture
    def watcher(self, vault_root, audit_dir):
        from aether_protocol.audit import AuditLog
        audit_log = AuditLog(str(audit_dir / "watcher_audit.jsonl"))
        return VaultWatcher(
            vault_root=str(vault_root),
            audit_log=audit_log,
        )

    @pytest.fixture
    def populated_watcher(self, watcher, vault_root):
        (vault_root / "existing.txt").write_text("hello")
        (vault_root / "data.csv").write_text("a,b\n1,2")
        return watcher

    def test_watcher_creation(self, watcher):
        assert watcher is not None
        assert not watcher.is_running

    def test_snapshot_state(self, populated_watcher, vault_root):
        state = populated_watcher._snapshot_state()
        assert "existing.txt" in state
        assert "data.csv" in state

    def test_detect_new_file(self, populated_watcher, vault_root):
        populated_watcher._known_state = populated_watcher._snapshot_state()
        (vault_root / "intruder.txt").write_text("hacked")
        changes = populated_watcher._check_changes()
        types = [c["type"] for c in changes]
        assert "FILE_CREATED" in types

    def test_detect_modified_file(self, populated_watcher, vault_root):
        populated_watcher._known_state = populated_watcher._snapshot_state()
        time.sleep(0.1)
        (vault_root / "existing.txt").write_text("modified content")
        changes = populated_watcher._check_changes()
        types = [c["type"] for c in changes]
        assert "FILE_MODIFIED" in types

    def test_detect_deleted_file(self, populated_watcher, vault_root):
        populated_watcher._known_state = populated_watcher._snapshot_state()
        (vault_root / "existing.txt").unlink()
        changes = populated_watcher._check_changes()
        types = [c["type"] for c in changes]
        assert "FILE_DELETED" in types

    def test_no_changes_detected(self, populated_watcher):
        populated_watcher._known_state = populated_watcher._snapshot_state()
        changes = populated_watcher._check_changes()
        assert len(changes) == 0

    def test_mark_authorized(self, watcher):
        watcher.mark_authorized("op_123")
        assert "op_123" in watcher._authorized_ops

    def test_clear_authorized(self, watcher):
        watcher.mark_authorized("op_123")
        watcher.clear_authorized("op_123")
        assert "op_123" not in watcher._authorized_ops

    def test_on_file_accessed_logs(self, populated_watcher):
        populated_watcher.on_file_accessed("existing.txt")
        # Should not raise

    def test_on_file_modified_logs(self, populated_watcher):
        populated_watcher.on_file_modified("existing.txt")
        # Should not raise

    def test_alert_callback(self, vault_root, audit_dir):
        from aether_protocol.audit import AuditLog
        alerts = []
        audit_log = AuditLog(str(audit_dir / "alert_audit.jsonl"))
        watcher = VaultWatcher(
            vault_root=str(vault_root),
            audit_log=audit_log,
            on_alert=lambda a: alerts.append(a),
        )
        (vault_root / "test.txt").write_text("x")
        watcher.on_file_accessed("test.txt")
        assert len(alerts) == 1
        assert alerts[0]["type"] == "UNAUTHORIZED_ACCESS"

    def test_start_stop(self, populated_watcher):
        populated_watcher.start()
        assert populated_watcher.is_running
        populated_watcher.stop()
        assert not populated_watcher.is_running

    def test_multiple_changes(self, populated_watcher, vault_root):
        populated_watcher._known_state = populated_watcher._snapshot_state()
        (vault_root / "new1.txt").write_text("a")
        (vault_root / "new2.txt").write_text("b")
        (vault_root / "existing.txt").unlink()
        changes = populated_watcher._check_changes()
        assert len(changes) == 3

    def test_file_event_handler(self, populated_watcher):
        populated_watcher.on_file_event("created", "new_file.txt")
        # Should log without error
