"""
AetherCloud-L — Agent Tests
Tests for AI file agent (with mocked Ollama).
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from agent.file_agent import AetherFileAgent


class TestAetherFileAgent:
    """Tests for AetherFileAgent."""

    @pytest.fixture
    def agent(self, populated_vault):
        return AetherFileAgent(populated_vault, model="qwen2.5:7b")

    def test_agent_creation(self, agent):
        assert agent is not None

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
        """When Ollama is unavailable, falls back to rule-based."""
        result = agent.analyze_file("/vault/script.py")
        assert "category" in result
        assert "suggested_name" in result
        assert "confidence" in result

    @patch("agent.file_agent.AetherFileAgent._query_ollama")
    def test_analyze_file_with_ai(self, mock_ollama, agent):
        mock_ollama.return_value = '{"suggested_name": "main.py", "category": "code", "reasoning": "Python script"}'
        result = agent.analyze_file("/vault/script.py")
        assert result["category"] == "code"
        assert result["confidence"] == 0.85

    @patch("agent.file_agent.AetherFileAgent._query_ollama")
    def test_analyze_file_ai_invalid_json(self, mock_ollama, agent):
        mock_ollama.return_value = "not json"
        result = agent.analyze_file("/vault/script.py")
        assert result["confidence"] == 0.7  # Falls back to rule-based

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

    def test_suggest_name(self, agent):
        name = agent.suggest_name("/vault/script.py")
        assert isinstance(name, str)
        assert name.endswith(".py")

    def test_query_ollama_failure(self, agent):
        """Ollama unavailable returns empty string."""
        # Use a bad URL to force connection failure
        agent._ollama_url = "http://127.0.0.1:1"
        result = agent._query_ollama("test prompt")
        assert result == ""
