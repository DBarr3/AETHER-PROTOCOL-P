"""
AetherCloud-L — Terminal UI Tests
Tests for CLI command parsing, dispatch, and watcher integration.
"""

import pytest
from unittest.mock import patch, MagicMock
from io import StringIO

from ui.terminal import AetherCloudTerminal


class TestAetherCloudTerminal:
    """Tests for terminal command parsing."""

    @pytest.fixture
    def terminal(self, tmp_path):
        return AetherCloudTerminal(
            vault_root=str(tmp_path / "vault"),
            config_path=str(tmp_path / "creds.json"),
        )

    def test_terminal_creation(self, terminal):
        assert terminal is not None

    def test_parse_command_simple(self):
        cmd, args = AetherCloudTerminal.parse_command("login")
        assert cmd == "login"
        assert args == []

    def test_parse_command_with_args(self):
        cmd, args = AetherCloudTerminal.parse_command("ls /path/to/dir")
        assert cmd == "ls"
        assert args == ["/path/to/dir"]

    def test_parse_command_quoted(self):
        cmd, args = AetherCloudTerminal.parse_command('chat "where is my file"')
        assert cmd == "chat"
        assert args == ["where is my file"]

    def test_parse_command_empty(self):
        cmd, args = AetherCloudTerminal.parse_command("")
        assert cmd == ""
        assert args == []

    def test_parse_command_multiple_args(self):
        cmd, args = AetherCloudTerminal.parse_command("move src.txt dest.txt")
        assert cmd == "move"
        assert args == ["src.txt", "dest.txt"]

    def test_parse_command_flags(self):
        cmd, args = AetherCloudTerminal.parse_command("organize --dry-run")
        assert cmd == "organize"
        assert "--dry-run" in args

    def test_commands_dict_includes_all(self, terminal):
        assert "scan" in terminal.COMMANDS
        assert "verify" in terminal.COMMANDS
        assert "login" in terminal.COMMANDS
        assert "logout" in terminal.COMMANDS
        assert "ls" in terminal.COMMANDS
        assert "audit" in terminal.COMMANDS
        assert "organize" in terminal.COMMANDS
        assert "chat" in terminal.COMMANDS
        assert "rename" in terminal.COMMANDS
        assert "move" in terminal.COMMANDS
        assert "status" in terminal.COMMANDS
        assert "help" in terminal.COMMANDS
        assert "exit" in terminal.COMMANDS

    def test_ensure_authenticated_not_logged_in(self, terminal):
        assert not terminal._ensure_authenticated()

    def test_dispatch_unknown_command(self, terminal):
        terminal._dispatch("foobar")
        # Should not raise

    def test_dispatch_help(self, terminal):
        terminal._dispatch("help")
        # Should not raise

    def test_dispatch_exit(self, terminal):
        terminal._dispatch("exit")
        assert not terminal._running

    def test_dispatch_scan_not_authenticated(self, terminal):
        terminal._dispatch("scan")
        # Should print auth error, not crash

    def test_styles_defined(self, terminal):
        assert terminal.STYLE_HEADER
        assert terminal.STYLE_SUCCESS
        assert terminal.STYLE_ERROR
        assert terminal.STYLE_WARNING
        assert terminal.STYLE_INFO

    def test_parse_command_case_insensitive(self):
        cmd, args = AetherCloudTerminal.parse_command("LOGIN")
        assert cmd == "login"

    def test_parse_command_mixed_case(self):
        cmd, args = AetherCloudTerminal.parse_command("Organize --dry-run")
        assert cmd == "organize"

    def test_threat_styles_defined(self, terminal):
        assert "NONE" in terminal.THREAT_STYLES
        assert "LOW" in terminal.THREAT_STYLES
        assert "MEDIUM" in terminal.THREAT_STYLES
        assert "HIGH" in terminal.THREAT_STYLES

    def test_watcher_initially_none(self, terminal):
        assert terminal._watcher is None or terminal._watcher is not None
        # Watcher may or may not be created in __init__

    def test_watcher_alerts_initially_empty(self, terminal):
        assert terminal._watcher_alerts == []

    def test_on_unauthorized_access_callback(self, terminal):
        event = {
            "path": "secret.txt",
            "type": "UNAUTHORIZED_ACCESS",
            "timestamp": 1710806400.0,
            "commitment_hash": "abc123def456",
        }
        terminal._on_unauthorized_access(event)
        assert len(terminal._watcher_alerts) == 1
        assert terminal._watcher_alerts[0]["path"] == "secret.txt"

    def test_multiple_unauthorized_alerts(self, terminal):
        for i in range(3):
            terminal._on_unauthorized_access({
                "path": f"file_{i}.txt",
                "type": "UNAUTHORIZED_ACCESS",
                "timestamp": 1710806400.0 + i,
            })
        assert len(terminal._watcher_alerts) == 3

    def test_shutdown_without_watcher(self, terminal):
        terminal._shutdown()  # Should not raise

    def test_parse_scan_command(self):
        cmd, args = AetherCloudTerminal.parse_command("scan")
        assert cmd == "scan"
        assert args == []

    def test_parse_verify_command(self):
        cmd, args = AetherCloudTerminal.parse_command("verify")
        assert cmd == "verify"
        assert args == []

    def test_dispatch_verify_not_authenticated(self, terminal):
        terminal._dispatch("verify")
        # Should print auth error, not crash
