"""
AetherCloud-L — Dashboard Tests
Tests for Textual TUI dashboard.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestDashboardCreation:
    """Tests for AetherDashboard initialization."""

    def test_dashboard_import(self):
        from ui.dashboard import AetherDashboard
        assert AetherDashboard is not None

    def test_dashboard_creation(self):
        from ui.dashboard import AetherDashboard
        app = AetherDashboard()
        assert app is not None

    def test_dashboard_with_vault(self):
        from ui.dashboard import AetherDashboard
        mock_vault = MagicMock()
        app = AetherDashboard(vault=mock_vault)
        assert app._vault is mock_vault

    def test_dashboard_with_agent(self):
        from ui.dashboard import AetherDashboard
        mock_agent = MagicMock()
        app = AetherDashboard(agent=mock_agent)
        assert app._agent is mock_agent

    def test_dashboard_with_watcher(self):
        from ui.dashboard import AetherDashboard
        mock_watcher = MagicMock()
        app = AetherDashboard(watcher=mock_watcher)
        assert app._watcher is mock_watcher

    def test_dashboard_title(self):
        from ui.dashboard import AetherDashboard
        assert AetherDashboard.TITLE == "AetherCloud-L Dashboard"

    def test_dashboard_bindings(self):
        from ui.dashboard import AetherDashboard
        binding_keys = [b.key for b in AetherDashboard.BINDINGS]
        assert "q" in binding_keys
        assert "r" in binding_keys
        assert "s" in binding_keys
        assert "o" in binding_keys

    def test_dashboard_css_defined(self):
        from ui.dashboard import AetherDashboard, DASHBOARD_CSS
        assert len(DASHBOARD_CSS) > 100
        assert "#file-panel" in DASHBOARD_CSS
        assert "#audit-panel" in DASHBOARD_CSS
        assert "#agent-panel" in DASHBOARD_CSS

    def test_launch_dashboard_function_exists(self):
        from ui.dashboard import launch_dashboard
        assert callable(launch_dashboard)


class TestDashboardRefresh:
    """Tests for dashboard refresh methods."""

    def test_refresh_tree_no_vault(self):
        from ui.dashboard import AetherDashboard
        app = AetherDashboard(vault=None)
        # Should not raise when vault is None
        app.refresh_tree()

    def test_refresh_audit_no_vault(self):
        from ui.dashboard import AetherDashboard
        app = AetherDashboard(vault=None)
        # Should not raise when vault is None
        app.refresh_audit()

    def test_action_scan_no_agent(self):
        from ui.dashboard import AetherDashboard
        app = AetherDashboard(agent=None)
        # Should not raise when agent is None
        app.action_scan()

    def test_action_organize_no_agent(self):
        from ui.dashboard import AetherDashboard
        app = AetherDashboard(agent=None)
        # Should not raise when agent is None
        app.action_organize()
