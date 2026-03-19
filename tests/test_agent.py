"""
AetherCloud-L — Agent Tests
Tests for AI file agent (rule-based fallback mode).
Claude-specific tests are in test_claude_agent.py.
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from agent.file_agent import AetherFileAgent


class TestAetherFileAgent:
    """Tests for AetherFileAgent."""

    @pytest.fixture
    def agent(self, populated_vault):
        """Create an agent with Claude disabled (rule-based mode)."""
        with patch("agent.file_agent.AetherFileAgent._init_claude_agent"):
            a = AetherFileAgent(populated_vault)
            a._claude_available = False
            a._claude_agent = None
        return a

    def test_agent_creation(self, agent):
        assert agent is not None

    def test_is_claude_available_false(self, agent):
        assert not agent.is_claude_available

    def test_rule_based_analysis_python(self, agent):
        result = agent._rule_based_analysis("/vault/script.py")
        assert result["category"] == "code"
        assert result["confidence"] == 0.7

    def test_rule_based_analysis_pdf(self, agent):
        result = agent._rule_based_analysis("/vault/document.pdf")
        assert result["category"] == "document"

    def test_rule_based_analysis_patent(self, agent):
        result = agent._rule_based_analysis("/vault/patent_filing.pdf")
        assert result["category"] == "patent"

    def test_rule_based_analysis_trading(self, agent):
        result = agent._rule_based_analysis("/vault/trade_log.csv")
        assert result["category"] == "trading"

    def test_rule_based_analysis_legal(self, agent):
        result = agent._rule_based_analysis("/vault/contract_nda.docx")
        assert result["category"] == "legal"

    def test_rule_based_analysis_backup(self, agent):
        result = agent._rule_based_analysis("/vault/backup_desktop.zip")
        assert result["category"] == "backup"

    def test_rule_based_analysis_config(self, agent):
        result = agent._rule_based_analysis("/vault/settings.yaml")
        assert result["category"] == "config"

    def test_rule_based_analysis_log(self, agent):
        result = agent._rule_based_analysis("/vault/debug.log")
        assert result["category"] == "log"

    def test_rule_based_analysis_security(self, agent):
        result = agent._rule_based_analysis("/vault/auth_keys.json")
        assert result["category"] == "security"

    def test_analyze_file_fallback(self, agent):
        """When Claude is unavailable, falls back to rule-based."""
        result = agent.analyze_file("/vault/script.py")
        assert "category" in result
        assert "suggested_name" in result
        assert "confidence" in result

    def test_organize_vault_dry_run(self, agent):
        suggestions = agent.organize_vault(dry_run=True)
        assert isinstance(suggestions, list)

    def test_organize_vault_returns_suggestions(self, agent):
        suggestions = agent.organize_vault(dry_run=True)
        for s in suggestions:
            assert "current_name" in s
            assert "suggested_name" in s
            assert "category" in s

    def test_chat_list_files(self, agent):
        response = agent.chat("list all files")
        assert "Found" in response or "No matching" in response

    def test_chat_show_python(self, agent):
        response = agent.chat("show python files")
        assert isinstance(response, str)

    def test_chat_status(self, agent):
        response = agent.chat("status")
        assert "Vault" in response or "Files" in response

    def test_chat_organize(self, agent):
        response = agent.chat("organize my vault")
        assert isinstance(response, str)

    def test_chat_audit(self, agent):
        response = agent.chat("audit trail")
        assert isinstance(response, str)

    def test_chat_unknown(self, agent):
        response = agent.chat("quantum entanglement theories")
        assert isinstance(response, str)

    def test_chat_security_scan(self, agent):
        response = agent.chat("security scan")
        assert isinstance(response, str)
        assert "Threat" in response or "scan" in response.lower()

    def test_suggest_name(self, agent):
        name = agent.suggest_name("/vault/script.py")
        assert isinstance(name, str)
        assert name.endswith(".py")

    def test_security_scan(self, agent):
        result = agent.security_scan()
        assert "threat_level" in result
        assert "findings" in result
        assert "recommended_action" in result

    def test_security_scan_no_threats(self, agent):
        result = agent.security_scan()
        assert result["threat_level"] in {"NONE", "LOW", "MEDIUM", "HIGH"}

    def test_reset_conversation_no_claude(self, agent):
        agent.reset_conversation()  # Should not raise

    def test_rule_based_chat_help(self, agent):
        response = agent._rule_based_chat("help me please")
        assert "I can help with" in response

    def test_rule_based_security_scan_empty(self, agent):
        result = agent._rule_based_security_scan([])
        assert result["threat_level"] == "NONE"

    def test_rule_based_security_scan_high(self, agent):
        events = []
        for i in range(12):
            events.append({
                "data": {
                    "trade_details": {
                        "event_type": "UNAUTHORIZED_ACCESS",
                        "path": f"file_{i}.txt",
                    }
                }
            })
        result = agent._rule_based_security_scan(events)
        assert result["threat_level"] == "HIGH"

    def test_rule_based_security_scan_medium(self, agent):
        events = []
        for i in range(4):
            events.append({
                "data": {
                    "trade_details": {
                        "event_type": "UNAUTHORIZED_ACCESS",
                        "path": f"file_{i}.txt",
                    }
                }
            })
        result = agent._rule_based_security_scan(events)
        assert result["threat_level"] == "MEDIUM"
