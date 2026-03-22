"""
AetherCloud-L — Hardened Claude Agent Tests
Tests for Protocol-L hardened Claude API wrapper with all API calls mocked.
Every response is SHA-256 hashed, quantum-bound, ECDSA signed, and verified.
"""

import hashlib
import json
import time
import pytest
from unittest.mock import patch, MagicMock, PropertyMock


def _make_mock_response(text: str) -> MagicMock:
    """Create a mock Claude API response."""
    mock_resp = MagicMock()
    mock_content = MagicMock()
    mock_content.text = text
    mock_resp.content = [mock_content]
    return mock_resp


class TestHardenedClaudeAgent:
    """Tests for HardenedClaudeAgent with mocked Anthropic API."""

    @pytest.fixture
    def mock_anthropic(self):
        with patch("agent.hardened_claude_agent.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_tsa(self):
        with patch("agent.hardened_claude_agent.RFC3161TimestampAuthority") as mock_cls:
            mock_tsa = MagicMock()
            mock_token = MagicMock()
            mock_token.to_dict.return_value = {
                "tsa_url": "http://test.tsa.com",
                "stamped_at": int(time.time()),
                "hash_algorithm": "sha-256",
                "message_imprint": "abc123",
            }
            mock_tsa.stamp.return_value = mock_token
            mock_cls.return_value = mock_tsa
            yield mock_tsa

    @pytest.fixture
    def agent(self, mock_anthropic, mock_tsa, tmp_path):
        from agent.hardened_claude_agent import HardenedClaudeAgent

        audit_dir = tmp_path / "audit"
        audit_dir.mkdir()

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-123"}), \
             patch("agent.hardened_claude_agent.DEFAULT_AUDIT_DIR", audit_dir):
            return HardenedClaudeAgent(
                api_key="test-key-123",
                session_token="test_session_abc",
                enable_rfc3161=True,
            )

    @pytest.fixture
    def agent_no_tsa(self, mock_anthropic, tmp_path):
        from agent.hardened_claude_agent import HardenedClaudeAgent

        audit_dir = tmp_path / "audit"
        audit_dir.mkdir()

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-123"}), \
             patch("agent.hardened_claude_agent.DEFAULT_AUDIT_DIR", audit_dir), \
             patch("agent.hardened_claude_agent.RFC3161TimestampAuthority", side_effect=Exception("No TSA")):
            return HardenedClaudeAgent(
                api_key="test-key-123",
                session_token="test_session_abc",
                enable_rfc3161=True,
            )

    # ─── Initialization tests ────────────────────────────────

    def test_agent_creation(self, agent):
        assert agent is not None
        assert agent.model is not None

    def test_agent_session_token_hashed(self, agent):
        expected = hashlib.sha256("test_session_abc".encode()).hexdigest()
        assert agent._session_token_hash == expected

    def test_agent_missing_api_key(self, mock_anthropic, mock_tsa, tmp_path):
        from agent.hardened_claude_agent import HardenedClaudeAgent
        with patch("agent.hardened_claude_agent.CLAUDE_API_KEY", None):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                HardenedClaudeAgent(api_key=None)

    def test_agent_no_tsa_still_works(self, agent_no_tsa):
        assert agent_no_tsa._tsa is None

    def test_initial_verification_stats(self, agent):
        assert agent._total_responses == 0
        assert agent._verified_responses == 0
        assert agent._tamper_detections == 0

    # ─── commit_response tests ───────────────────────────────

    def test_commit_response_returns_hardened(self, agent):
        hardened = agent._commit_response("test response", "test prompt")
        assert hardened.response_text == "test response"
        assert hardened.response_hash == hashlib.sha256(b"test response").hexdigest()
        assert hardened.prompt_hash == hashlib.sha256(b"test prompt").hexdigest()
        assert hardened.session_token_hash == agent._session_token_hash

    def test_commit_response_has_signature(self, agent):
        hardened = agent._commit_response("hello", "prompt")
        assert "r" in hardened.signature
        assert "s" in hardened.signature
        assert "pubkey" in hardened.signature

    def test_commit_response_has_seed_commitment(self, agent):
        hardened = agent._commit_response("hello", "prompt")
        assert "seed_hash" in hardened.seed_commitment
        assert "measurement_method" in hardened.seed_commitment
        assert hardened.seed_commitment["measurement_method"] in ("OS_URANDOM", "CSPRNG")

    def test_commit_response_increments_counter(self, agent):
        agent._commit_response("a", "b")
        agent._commit_response("c", "d")
        assert agent._total_responses == 2

    def test_commit_response_has_rfc3161(self, agent, mock_tsa):
        hardened = agent._commit_response("test", "prompt")
        assert hardened.rfc3161_token is not None
        assert hardened.rfc3161_token["tsa_url"] == "http://test.tsa.com"

    def test_commit_response_without_rfc3161(self, agent_no_tsa):
        hardened = agent_no_tsa._commit_response("test", "prompt")
        assert hardened.rfc3161_token is None

    def test_commit_response_to_dict(self, agent):
        hardened = agent._commit_response("test", "prompt")
        d = hardened.to_dict()
        assert "response_hash" in d
        assert "signature" in d
        assert "seed_commitment" in d
        # response_text should NOT be in to_dict (sensitive)
        assert "response_text" not in d

    # ─── verify_response tests ───────────────────────────────

    def test_verify_response_passes(self, agent):
        hardened = agent._commit_response("valid response", "prompt")
        assert agent._verify_response(hardened) is True
        assert agent._verified_responses == 1

    def test_verify_response_hash_mismatch(self, agent):
        from agent.hardened_claude_agent import HardenedResponse, ResponseTamperingError

        hardened = agent._commit_response("original", "prompt")
        # Create a tampered response with wrong hash
        tampered = HardenedResponse(
            response_text="tampered text",
            response_hash=hardened.response_hash,  # hash of "original", not "tampered text"
            model=hardened.model,
            prompt_hash=hardened.prompt_hash,
            session_token_hash=hardened.session_token_hash,
            quantum_seed_hash=hardened.quantum_seed_hash,
            signature=hardened.signature,
            seed_commitment=hardened.seed_commitment,
            timestamp=hardened.timestamp,
        )
        with pytest.raises(ResponseTamperingError, match="hash mismatch"):
            agent._verify_response(tampered)
        assert agent._tamper_detections == 1

    def test_verify_response_session_mismatch(self, agent):
        from agent.hardened_claude_agent import HardenedResponse, ResponseTamperingError

        hardened = agent._commit_response("test", "prompt")
        tampered = HardenedResponse(
            response_text="test",
            response_hash=hardened.response_hash,
            model=hardened.model,
            prompt_hash=hardened.prompt_hash,
            session_token_hash="wrong_session_hash_0000000000000000",
            quantum_seed_hash=hardened.quantum_seed_hash,
            signature=hardened.signature,
            seed_commitment=hardened.seed_commitment,
            timestamp=hardened.timestamp,
        )
        with pytest.raises(ResponseTamperingError, match="Session token mismatch"):
            agent._verify_response(tampered)

    def test_verify_response_signature_invalid(self, agent):
        from agent.hardened_claude_agent import HardenedResponse, ResponseTamperingError

        hardened = agent._commit_response("test", "prompt")
        bad_sig = dict(hardened.signature)
        bad_sig["r"] = "0" * 64  # invalid r value
        tampered = HardenedResponse(
            response_text="test",
            response_hash=hardened.response_hash,
            model=hardened.model,
            prompt_hash=hardened.prompt_hash,
            session_token_hash=hardened.session_token_hash,
            quantum_seed_hash=hardened.quantum_seed_hash,
            signature=bad_sig,
            seed_commitment=hardened.seed_commitment,
            timestamp=hardened.timestamp,
        )
        with pytest.raises(ResponseTamperingError, match="signature verification failed"):
            agent._verify_response(tampered)

    def test_verify_response_bad_seed_commitment(self, agent):
        from agent.hardened_claude_agent import HardenedResponse, ResponseTamperingError

        hardened = agent._commit_response("test", "prompt")
        tampered = HardenedResponse(
            response_text="test",
            response_hash=hardened.response_hash,
            model=hardened.model,
            prompt_hash=hardened.prompt_hash,
            session_token_hash=hardened.session_token_hash,
            quantum_seed_hash=hardened.quantum_seed_hash,
            signature=hardened.signature,
            seed_commitment={"invalid": "data"},
            timestamp=hardened.timestamp,
        )
        with pytest.raises(ResponseTamperingError, match="seed commitment invalid"):
            agent._verify_response(tampered)

    # ─── analyze_file tests ──────────────────────────────────

    def test_analyze_file_verified(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "suggested_name": "20260319_PATENT_test.pdf",
                "category": "PATENT",
                "suggested_directory": "patents",
                "confidence": 0.95,
                "reasoning": "Patent filing",
                "security_flag": False,
                "security_note": None,
            })
        )
        result = agent.analyze_file("patent_filing", ".pdf", "desktop")
        assert result["category"] == "PATENT"
        assert result["confidence"] == 0.95
        assert agent._verified_responses == 1

    def test_analyze_file_with_markdown_fences(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            '```json\n{"suggested_name": "test.py", "category": "CODE", '
            '"suggested_directory": "code", "confidence": 0.9, '
            '"reasoning": "Python file", "security_flag": false, '
            '"security_note": null}\n```'
        )
        result = agent.analyze_file("test", ".py", "projects")
        assert result["category"] == "CODE"

    def test_analyze_file_api_failure_uses_fallback(self, agent, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception("API error")
        result = agent.analyze_file("mycode", ".py", "projects")
        assert result["category"] == "CODE"
        assert result["confidence"] == 0.6
        assert "Rule-based" in result["reasoning"]

    def test_analyze_file_sends_correct_params(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
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
        call_kwargs = mock_anthropic.messages.create.call_args
        assert call_kwargs.kwargs["model"] == agent.model
        assert call_kwargs.kwargs["system"] == agent.system_prompt

    # ─── batch_analyze tests ─────────────────────────────────

    def test_batch_analyze_verified(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
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
            ])
        )
        files = [{"filename": "script", "extension": ".py", "directory": "src"}]
        results = agent.batch_analyze(files)
        assert len(results) == 1
        assert results[0]["category"] == "CODE"
        assert agent._verified_responses == 1

    def test_batch_analyze_empty_list(self, agent):
        results = agent.batch_analyze([])
        assert results == []

    def test_batch_analyze_fallback_on_error(self, agent, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception("API error")
        files = [{"filename": "test", "extension": ".py", "directory": "src"}]
        results = agent.batch_analyze(files)
        assert len(results) == 1
        assert results[0]["category"] == "CODE"

    # ─── chat tests ──────────────────────────────────────────

    def test_chat_verified(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            "I found 3 Python files in your vault."
        )
        result = agent.chat("find my python files", {"file_count": 10})
        assert "Python" in result
        assert agent._verified_responses == 1

    def test_chat_maintains_history(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response("ok")
        agent.chat("hello", {})
        agent.chat("followup", {})
        assert len(agent.conversation_history) == 4

    def test_chat_history_bounded(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response("ok")
        for i in range(30):
            agent.chat(f"msg {i}", {})
        assert len(agent.conversation_history) <= 40

    def test_chat_api_error(self, agent, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception("Timeout")
        result = agent.chat("test", {})
        assert "unavailable" in result.lower() or "Timeout" in result

    def test_chat_first_message_includes_context(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response("ok")
        agent.chat("hello", {"file_count": 42, "vault_stats": {"files": 42}})
        first_msg = agent.conversation_history[0]["content"]
        assert "42" in first_msg

    # ─── security analysis tests ─────────────────────────────

    def test_security_scan_verified(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "threat_level": "HIGH",
                "findings": ["15 failed logins in 60s"],
                "recommended_action": "Lock account",
            })
        )
        events = [{"type": "LOGIN_FAILURE"} for _ in range(15)]
        result = agent.analyze_security_pattern(events)
        assert result["threat_level"] == "HIGH"
        assert agent._verified_responses == 1

    def test_security_scan_no_events(self, agent):
        result = agent.analyze_security_pattern([])
        assert result["threat_level"] == "NONE"
        assert result["recommended_action"] == "No events to analyze"

    def test_security_scan_api_error(self, agent, mock_anthropic):
        mock_anthropic.messages.create.side_effect = Exception("API error")
        events = [{"type": "test"}]
        result = agent.analyze_security_pattern(events)
        assert result["threat_level"] == "UNKNOWN"

    # ─── verification report tests ───────────────────────────

    def test_verification_report_clean(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "suggested_name": "t.py",
                "category": "CODE",
                "suggested_directory": "code",
                "confidence": 0.8,
                "reasoning": "test",
                "security_flag": False,
                "security_note": None,
            })
        )
        agent.analyze_file("test", ".py", "src")
        report = agent.get_verification_report()
        assert report["total_responses"] == 1
        assert report["verified_responses"] == 1
        assert report["tamper_detections"] == 0
        assert report["integrity"] == "CLEAN"
        assert report["verification_rate"] == "1/1"

    def test_verification_report_initial(self, agent):
        report = agent.get_verification_report()
        assert report["total_responses"] == 0
        assert report["integrity"] == "CLEAN"
        assert report["verification_rate"] == "0/0"

    def test_verification_report_shows_model(self, agent):
        report = agent.get_verification_report()
        assert report["model"] == agent.model

    def test_verification_report_shows_session(self, agent):
        report = agent.get_verification_report()
        assert report["session_token_hash"] == agent._session_token_hash

    def test_verification_report_after_tamper(self, agent):
        from agent.hardened_claude_agent import HardenedResponse, ResponseTamperingError

        hardened = agent._commit_response("test", "prompt")
        tampered = HardenedResponse(
            response_text="TAMPERED",
            response_hash=hardened.response_hash,
            model=hardened.model,
            prompt_hash=hardened.prompt_hash,
            session_token_hash=hardened.session_token_hash,
            quantum_seed_hash=hardened.quantum_seed_hash,
            signature=hardened.signature,
            seed_commitment=hardened.seed_commitment,
            timestamp=hardened.timestamp,
        )
        with pytest.raises(ResponseTamperingError):
            agent._verify_response(tampered)

        report = agent.get_verification_report()
        assert report["tamper_detections"] == 1
        assert "COMPROMISED" in report["integrity"]

    # ─── reset and utility tests ─────────────────────────────

    def test_reset_conversation(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response("ok")
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

    # ─── rule-based fallback tests ───────────────────────────

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

    def test_fallback_valid_structure(self, agent):
        result = agent._rule_based_fallback("test", ".txt", "dir")
        assert "suggested_name" in result
        assert "category" in result
        assert "confidence" in result
        assert result["confidence"] == 0.6

    def test_fallback_config_detection(self, agent):
        result = agent._rule_based_fallback("settings", ".json", ".")
        assert result["category"] == "CONFIG"

    # ─── HardenedResponse immutability tests ─────────────────

    def test_hardened_response_frozen(self, agent):
        hardened = agent._commit_response("test", "prompt")
        with pytest.raises(AttributeError):
            hardened.response_text = "tampered"

    def test_hardened_response_hash_correct(self, agent):
        hardened = agent._commit_response("hello world", "prompt")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert hardened.response_hash == expected

    # ─── Audit log integration tests ─────────────────────────

    def test_commit_writes_to_audit_log(self, agent):
        agent._commit_response("test", "prompt")
        # Audit log should have at least one entry
        entries = agent._audit_log.read_all()
        assert len(entries) >= 1

    def test_commit_audit_entry_has_correct_type(self, agent):
        agent._commit_response("test response", "test prompt")
        entries = agent._audit_log.read_all()
        last = entries[-1]
        data = last.data if hasattr(last, 'data') else last.get('data', {})
        if isinstance(data, dict):
            trade_details = data.get("trade_details", {})
            assert trade_details.get("event_type") == "AI_RESPONSE_COMMITTED"

    # ─── Multiple verified responses ─────────────────────────

    def test_multiple_verified_responses(self, agent, mock_anthropic):
        mock_anthropic.messages.create.return_value = _make_mock_response(
            json.dumps({
                "suggested_name": "test.py",
                "category": "CODE",
                "suggested_directory": "code",
                "confidence": 0.9,
                "reasoning": "test",
                "security_flag": False,
                "security_note": None,
            })
        )
        for _ in range(5):
            agent.analyze_file("test", ".py", "src")

        report = agent.get_verification_report()
        assert report["total_responses"] == 5
        assert report["verified_responses"] == 5
        assert report["integrity"] == "CLEAN"

    # ─── Quantum seed independence ───────────────────────────

    def test_each_response_has_unique_seed(self, agent):
        h1 = agent._commit_response("response 1", "prompt 1")
        h2 = agent._commit_response("response 2", "prompt 2")
        assert h1.quantum_seed_hash != h2.quantum_seed_hash

    def test_each_response_has_unique_signature(self, agent):
        h1 = agent._commit_response("response 1", "prompt 1")
        h2 = agent._commit_response("response 2", "prompt 2")
        assert h1.signature["r"] != h2.signature["r"]


class TestHardenedAgentInit:
    """Tests for agent initialization edge cases."""

    def test_custom_model(self, tmp_path):
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir()

        with patch("agent.hardened_claude_agent.Anthropic"), \
             patch("agent.hardened_claude_agent.RFC3161TimestampAuthority"), \
             patch("agent.hardened_claude_agent.DEFAULT_AUDIT_DIR", audit_dir):
            from agent.hardened_claude_agent import HardenedClaudeAgent
            agent = HardenedClaudeAgent(
                api_key="key", model="claude-sonnet-4-20250514"
            )
            assert agent.model == "claude-sonnet-4-20250514"

    def test_custom_max_tokens(self, tmp_path):
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir()

        with patch("agent.hardened_claude_agent.Anthropic"), \
             patch("agent.hardened_claude_agent.RFC3161TimestampAuthority"), \
             patch("agent.hardened_claude_agent.DEFAULT_AUDIT_DIR", audit_dir):
            from agent.hardened_claude_agent import HardenedClaudeAgent
            agent = HardenedClaudeAgent(api_key="key", max_tokens=2048)
            assert agent.max_tokens == 2048

    def test_rfc3161_disabled(self, tmp_path):
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir()

        with patch("agent.hardened_claude_agent.Anthropic"), \
             patch("agent.hardened_claude_agent.DEFAULT_AUDIT_DIR", audit_dir):
            from agent.hardened_claude_agent import HardenedClaudeAgent
            agent = HardenedClaudeAgent(
                api_key="key", enable_rfc3161=False
            )
            assert agent._tsa is None

    def test_auto_generated_session_token(self, tmp_path):
        audit_dir = tmp_path / "audit"
        audit_dir.mkdir()

        with patch("agent.hardened_claude_agent.Anthropic"), \
             patch("agent.hardened_claude_agent.RFC3161TimestampAuthority"), \
             patch("agent.hardened_claude_agent.DEFAULT_AUDIT_DIR", audit_dir):
            from agent.hardened_claude_agent import HardenedClaudeAgent
            agent = HardenedClaudeAgent(api_key="key")
            assert len(agent._session_token_hash) == 64


class TestFileAgentHardenedIntegration:
    """Tests for file_agent.py integration with hardened agent."""

    @pytest.fixture
    def agent(self, populated_vault):
        """Create an agent with hardened Claude disabled (rule-based mode)."""
        with patch("agent.file_agent.AetherFileAgent._init_claude_agent"):
            a = AetherFileAgent(populated_vault)
            a._claude_available = False
            a._claude_agent = None
            a._hardened = False
        return a

    def test_is_hardened_false(self, agent):
        assert not agent.is_hardened

    def test_verification_report_not_hardened(self, agent):
        report = agent.get_verification_report()
        assert report["integrity"] == "NOT_HARDENED"

    def test_is_hardened_true_when_enabled(self, populated_vault):
        """When hardened agent is set, is_hardened should be True."""
        with patch("agent.file_agent.AetherFileAgent._init_claude_agent"):
            a = AetherFileAgent(populated_vault)
            a._claude_available = True
            a._hardened = True
            a._claude_agent = MagicMock()
            a._claude_agent.get_verification_report.return_value = {
                "integrity": "CLEAN",
                "total_responses": 5,
            }
        assert a.is_hardened
        report = a.get_verification_report()
        assert report["integrity"] == "CLEAN"


# Import needed for integration tests
from agent.file_agent import AetherFileAgent
