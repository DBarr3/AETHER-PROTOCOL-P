"""
AetherCloud-L — Claude Agent Tests
Tests for Claude API sub-agent with all API calls mocked.
"""

import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock


def _make_mock_response(text: str) -> MagicMock:
    """Create a mock TokenAccountant AnthropicResponse."""
    mock_resp = MagicMock()
    mock_resp.text = text
    return mock_resp


class TestAetherClaudeAgent:
    """Tests for AetherClaudeAgent with mocked Anthropic API."""

    @pytest.fixture
    def mock_anthropic(self):
        """Red Team #2 C1: agent now routes through token_accountant
        instead of anthropic.Anthropic. Fixture patches the new path."""
        with patch("agent.claude_agent.token_accountant.call_sync") as mock_call:
            yield mock_call

    @pytest.fixture
    def agent(self, mock_anthropic):
        from agent.claude_agent import AetherClaudeAgent
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-123"}):
            return AetherClaudeAgent(api_key="test-key-123")

    # ─── analyze_file tests ─────────────────────────────

    def test_analyze_file_returns_valid_structure(self, agent, mock_anthropic):
        mock_anthropic.return_value = _make_mock_response(
            json.dumps({
                "suggested_name": "20260319_PATENT_test.pdf",
                "category": "PATENT",
                "suggested_directory": "patents",
                "confidence": 0.95,
                "reasoning": "Contains patent in filename",
                "security_flag": False,
                "security_note": None,
            })
        )
        result = agent.analyze_file("patent_filing", ".pdf", "desktop")
        assert result["category"] == "PATENT"
        assert result["confidence"] == 0.95
        assert "suggested_name" in result

    def test_analyze_file_with_markdown_fences(self, agent, mock_anthropic):
        mock_anthropic.return_value = _make_mock_response(
            '```json\n{"suggested_name": "test.py", "category": "CODE", '
            '"suggested_directory": "code", "confidence": 0.9, '
            '"reasoning": "Python file", "security_flag": false, '
            '"security_note": null}\n```'
        )
        result = agent.analyze_file("test", ".py", "projects")
        assert result["category"] == "CODE"

    def test_analyze_file_api_failure_uses_fallback(self, agent, mock_anthropic):
        mock_anthropic.side_effect = Exception("API error")
        result = agent.analyze_file("mycode", ".py", "projects")
        assert result["category"] == "CODE"
        assert result["confidence"] == 0.6
        assert "Rule-based" in result["reasoning"]

    def test_analyze_file_sends_correct_params(self, agent, mock_anthropic):
        mock_anthropic.return_value = _make_mock_response(
            json.dumps({
                "suggested_name": "test.py",
                "category": "CODE",
                "suggested_directory": "code",
                "confidence": 0.8,
                "reasoning": "test",
                "security_flag": False,
                "security_note": None,
            })
        )
        agent.analyze_file("script", ".py", "src")
        call_kwargs = mock_anthropic.call_args
        # After Red Team #2 C1 fix, the router passes a ModelRegistry
        # short key (e.g. "sonnet") to token_accountant.call_sync, not the
        # full model id. Assert on the resolved short key.
        assert call_kwargs.kwargs["model"] == agent._model_key
        assert call_kwargs.kwargs["system"] == agent.system_prompt

    # ─── batch_analyze tests ────────────────────────────

    def test_batch_analyze_returns_results(self, agent, mock_anthropic):
        mock_anthropic.return_value = _make_mock_response(
            json.dumps([
                {
                    "index": 1,
                    "suggested_name": "20260319_CODE_script.py",
                    "category": "CODE",
                    "suggested_directory": "code",
                    "confidence": 0.9,
                    "reasoning": "Python script",
                    "security_flag": False,
                    "security_note": None,
                },
                {
                    "index": 2,
                    "suggested_name": "20260319_LEGAL_contract.pdf",
                    "category": "LEGAL",
                    "suggested_directory": "legal",
                    "confidence": 0.95,
                    "reasoning": "Legal document",
                    "security_flag": False,
                    "security_note": None,
                },
            ])
        )
        files = [
            {"filename": "script", "extension": ".py", "directory": "src"},
            {"filename": "contract", "extension": ".pdf", "directory": "docs"},
        ]
        results = agent.batch_analyze(files)
        assert len(results) == 2
        assert results[0]["category"] == "CODE"
        assert results[1]["category"] == "LEGAL"

    def test_batch_analyze_empty_list(self, agent):
        results = agent.batch_analyze([])
        assert results == []

    def test_batch_analyze_fallback_on_error(self, agent, mock_anthropic):
        mock_anthropic.side_effect = Exception("API error")
        files = [{"filename": "test", "extension": ".py", "directory": "src"}]
        results = agent.batch_analyze(files)
        assert len(results) == 1
        assert results[0]["category"] == "CODE"

    # ─── chat tests ─────────────────────────────────────

    def test_chat_returns_response(self, agent, mock_anthropic):
        mock_anthropic.return_value = _make_mock_response(
            "I found 3 Python files in your vault."
        )
        result = agent.chat("find my python files", {"file_count": 10})
        assert "Python" in result

    def test_chat_maintains_history(self, agent, mock_anthropic):
        mock_anthropic.return_value = _make_mock_response("Found it.")
        agent.chat("find my patent", {})
        agent.chat("what about the other one", {})
        assert len(agent.conversation_history) == 4  # 2 user + 2 assistant

    def test_chat_history_bounded(self, agent, mock_anthropic):
        mock_anthropic.return_value = _make_mock_response("ok")
        for i in range(30):
            agent.chat(f"message {i}", {})
        assert len(agent.conversation_history) <= 40

    def test_chat_api_error_returns_message(self, agent, mock_anthropic):
        mock_anthropic.side_effect = Exception("Timeout")
        result = agent.chat("test", {})
        assert "unavailable" in result.lower() or "Timeout" in result

    def test_chat_first_message_includes_context(self, agent, mock_anthropic):
        mock_anthropic.return_value = _make_mock_response("ok")
        agent.chat("hello", {"file_count": 42, "vault_stats": {"files": 42}})
        first_msg = agent.conversation_history[0]["content"]
        assert "42" in first_msg

    # ─── security analysis tests ────────────────────────

    def test_security_scan_high_threat(self, agent, mock_anthropic):
        mock_anthropic.return_value = _make_mock_response(
            json.dumps({
                "threat_level": "HIGH",
                "findings": ["15 failed logins in 60s"],
                "recommended_action": "Lock account",
            })
        )
        events = [{"type": "LOGIN_FAILURE"} for _ in range(15)]
        result = agent.analyze_security_pattern(events)
        assert result["threat_level"] == "HIGH"

    def test_security_scan_no_events(self, agent):
        result = agent.analyze_security_pattern([])
        assert result["threat_level"] == "NONE"
        assert result["recommended_action"] == "No events to analyze"

    def test_security_scan_api_error(self, agent, mock_anthropic):
        mock_anthropic.side_effect = Exception("API error")
        events = [{"type": "test"}]
        result = agent.analyze_security_pattern(events)
        assert result["threat_level"] == "UNKNOWN"

    # ─── reset and utility tests ────────────────────────

    def test_reset_conversation(self, agent, mock_anthropic):
        mock_anthropic.return_value = _make_mock_response("ok")
        agent.chat("hello", {})
        assert len(agent.conversation_history) > 0
        agent.reset_conversation()
        assert len(agent.conversation_history) == 0

    def test_strip_markdown_fences(self, agent):
        raw = '```json\n{"key": "value"}\n```'
        assert agent._strip_markdown_fences(raw) == '{"key": "value"}'

    def test_strip_markdown_fences_no_fences(self, agent):
        raw = '{"key": "value"}'
        assert agent._strip_markdown_fences(raw) == raw

    # ─── rule-based fallback tests ──────────────────────

    def test_fallback_patent_detection(self, agent):
        result = agent._rule_based_fallback("USPTO_patent_filing", ".pdf", "desktop")
        assert result["category"] == "PATENT"

    def test_fallback_code_detection(self, agent):
        result = agent._rule_based_fallback("my_script", ".py", "projects")
        assert result["category"] == "CODE"

    def test_fallback_trading_detection(self, agent):
        result = agent._rule_based_fallback("trade_log", ".csv", "data")
        assert result["category"] == "TRADING"

    def test_fallback_security_detection(self, agent):
        result = agent._rule_based_fallback("password_store", ".json", "config")
        assert result["category"] == "SECURITY"

    def test_fallback_legal_detection(self, agent):
        result = agent._rule_based_fallback("contract_signed", ".docx", "legal")
        assert result["category"] == "LEGAL"

    def test_fallback_backup_detection(self, agent):
        result = agent._rule_based_fallback("backup_daily", ".zip", "archives")
        assert result["category"] == "BACKUP"

    def test_fallback_unknown_extension(self, agent):
        result = agent._rule_based_fallback("random_file", ".xyz", "misc")
        assert result["category"] == "PERSONAL"

    def test_fallback_returns_valid_structure(self, agent):
        result = agent._rule_based_fallback("test", ".txt", "dir")
        assert "suggested_name" in result
        assert "category" in result
        assert "suggested_directory" in result
        assert "confidence" in result
        assert "reasoning" in result
        assert "security_flag" in result
        assert result["confidence"] == 0.6

    def test_fallback_suggested_name_format(self, agent):
        result = agent._rule_based_fallback("my_file", ".py", "src")
        name = result["suggested_name"]
        assert name.endswith(".py")
        assert "_CODE_" in name

    def test_fallback_config_detection(self, agent):
        result = agent._rule_based_fallback("settings", ".json", ".")
        assert result["category"] == "CONFIG"


class TestAetherClaudeAgentInit:
    """Tests for agent initialization."""

    def test_missing_api_key_raises(self):
        from agent.claude_agent import AetherClaudeAgent
        with patch("agent.claude_agent.CLAUDE_API_KEY", None):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                AetherClaudeAgent(api_key=None)

    @patch("agent.claude_agent.token_accountant.call_sync")
    def test_custom_model(self, mock_call):
        from agent.claude_agent import AetherClaudeAgent
        agent = AetherClaudeAgent(api_key="key", model="claude-sonnet-4-20250514")
        assert agent.model == "claude-sonnet-4-20250514"
        # Red Team #2 C1: the raw id resolves to the ModelRegistry short key.
        assert agent._model_key == "sonnet"

    @patch("agent.claude_agent.token_accountant.call_sync")
    def test_custom_max_tokens(self, mock_call):
        from agent.claude_agent import AetherClaudeAgent
        agent = AetherClaudeAgent(api_key="key", max_tokens=2048)
        assert agent.max_tokens == 2048
