"""
AetherCloud-L — User Context Scorer Tests
Tests for the UserContextScorer, blended QOPC scoring,
and context injection into agent prompts.

Aether Systems LLC — Patent Pending
"""

import pytest
from unittest.mock import patch, MagicMock


# ─── UserContextScorer Tests ─────────────────────────────

class TestUserContextScorer:
    """Test the UserContextScorer intent signal parsing and scoring."""

    def test_no_context_returns_neutral(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("")
        assert scorer.score_response("anything at all") == 0.5

    def test_whitespace_only_returns_neutral(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("   \n  ")
        assert scorer.score_response("some response") == 0.5

    def test_has_context_false_when_empty(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("")
        assert scorer.has_context is False

    def test_has_context_true_when_set(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("organize by date")
        assert scorer.has_context is True

    def test_never_delete_violation(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("never delete files without asking")
        score = scorer.score_response("I have deleted the old files")
        assert score < 0.5

    def test_never_delete_alignment(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("never delete files without asking")
        score = scorer.score_response(
            "I organized your files into folders. "
            "All files are safe and accounted for."
        )
        assert score > 0.5

    def test_dont_delete_variant(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("don't delete anything")
        assert "never_delete" in scorer.active_signals

    def test_ask_before_action_alignment(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("always ask before making changes")
        score = scorer.score_response("Shall I rename these files?")
        assert score > 0.5

    def test_ask_before_action_violation(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("always ask before making changes")
        score = scorer.score_response("I have renamed all the files")
        assert score < 0.5

    def test_prefer_clean_alignment(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("keep everything organized and clean")
        score = scorer.score_response(
            "Files have been sorted and organized into categories"
        )
        assert score > 0.5

    def test_date_prefix_alignment(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("always use date prefix YYYYMMDD")
        score = scorer.score_response(
            "Renamed to 20260320_PATENT_Filing.pdf"
        )
        assert score > 0.5

    def test_date_prefix_no_match(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("always use date prefix YYYYMMDD")
        score = scorer.score_response(
            "Renamed to PATENT_Filing.pdf"
        )
        # No date found — no alignment, no violation either
        # depends on implementation, but should not be > 0.5
        assert score <= 0.5

    def test_multiple_signals_detected(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer(
            "clean format, never delete, ask before"
        )
        signals = scorer.active_signals
        assert "never_delete" in signals
        assert "ask_before_action" in signals
        assert "prefer_clean" in signals

    def test_update_context_changes_signals(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("")
        assert scorer.has_context is False
        assert len(scorer.active_signals) == 0

        scorer.update_context("never delete anything, always ask")
        assert scorer.has_context is True
        assert "never_delete" in scorer.active_signals
        assert "ask_before_action" in scorer.active_signals

    def test_action_taken_parameter(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer("never delete files")
        # Response is benign but action indicates deletion
        score = scorer.score_response(
            "Processing complete.",
            action_taken="deleted 5 files"
        )
        assert score < 0.5

    def test_score_is_bounded(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer(
            "never delete, always ask, keep clean, use date prefix YYYYMMDD"
        )
        score = scorer.score_response(
            "I deleted everything without asking"
        )
        assert 0.0 <= score <= 1.0

    def test_perfect_alignment_score(self):
        from agent.qopc_feedback import UserContextScorer
        scorer = UserContextScorer(
            "keep everything organized and clean"
        )
        score = scorer.score_response(
            "All files have been organized and sorted into clean categories"
        )
        assert score >= 0.5


# ─── Blended Score Tests ─────────────────────────────────

class TestBlendedScoring:
    """Test blended scoring in OutcomeObserver (70% outcome + 30% context)."""

    def test_accepted_with_zero_context_score(self):
        from agent.qopc_feedback import OutcomeObserver, ReasoningCycle
        observer = OutcomeObserver()
        cycle = ReasoningCycle(
            cycle_id="test_blend_1",
            task_type="ANALYZE",
            query="test",
        )
        observer.register_cycle(cycle)
        result = observer.record_outcome(
            "test_blend_1", "ACCEPTED", context_score=0.0
        )
        assert result is not None
        # ACCEPTED base = 1.0, context = 0.0
        # blended = 1.0 * 0.7 + 0.0 * 0.3 = 0.7
        assert result.outcome_score == 0.7

    def test_accepted_with_full_context_alignment(self):
        from agent.qopc_feedback import OutcomeObserver, ReasoningCycle
        observer = OutcomeObserver()
        cycle = ReasoningCycle(
            cycle_id="test_blend_2",
            task_type="ANALYZE",
            query="test",
        )
        observer.register_cycle(cycle)
        result = observer.record_outcome(
            "test_blend_2", "ACCEPTED", context_score=1.0
        )
        assert result is not None
        # ACCEPTED base = 1.0, context = 1.0
        # blended = 1.0 * 0.7 + 1.0 * 0.3 = 1.0
        assert result.outcome_score == 1.0

    def test_rejected_with_good_context_still_low(self):
        from agent.qopc_feedback import OutcomeObserver, ReasoningCycle
        observer = OutcomeObserver()
        cycle = ReasoningCycle(
            cycle_id="test_blend_3",
            task_type="CHAT",
            query="test",
        )
        observer.register_cycle(cycle)
        result = observer.record_outcome(
            "test_blend_3", "REJECTED", context_score=1.0
        )
        assert result is not None
        # REJECTED base = 0.0, context = 1.0
        # blended = 0.0 * 0.7 + 1.0 * 0.3 = 0.3
        assert result.outcome_score == 0.3

    def test_default_context_score_is_neutral(self):
        from agent.qopc_feedback import OutcomeObserver, ReasoningCycle
        observer = OutcomeObserver()
        cycle = ReasoningCycle(
            cycle_id="test_blend_4",
            task_type="ANALYZE",
            query="test",
        )
        observer.register_cycle(cycle)
        result = observer.record_outcome(
            "test_blend_4", "ACCEPTED"
        )
        assert result is not None
        # ACCEPTED base = 1.0, context default = 0.5
        # blended = 1.0 * 0.7 + 0.5 * 0.3 = 0.85
        assert result.outcome_score == 0.85

    def test_corrected_with_neutral_context(self):
        from agent.qopc_feedback import OutcomeObserver, ReasoningCycle
        observer = OutcomeObserver()
        cycle = ReasoningCycle(
            cycle_id="test_blend_5",
            task_type="ANALYZE",
            query="test",
        )
        observer.register_cycle(cycle)
        result = observer.record_outcome(
            "test_blend_5", "CORRECTED", context_score=0.5
        )
        assert result is not None
        # CORRECTED base = 0.3, context = 0.5
        # blended = 0.3 * 0.7 + 0.5 * 0.3 = 0.21 + 0.15 = 0.36
        assert result.outcome_score == 0.36


# ─── QOPCLoop Context Integration Tests ─────────────────

class TestQOPCLoopContext:
    """Test that QOPCLoop passes context_score through."""

    def test_loop_record_outcome_with_context(self):
        from agent.qopc_feedback import QOPCLoop
        loop = QOPCLoop()

        # We need a mock vault
        mock_vault = MagicMock()
        mock_vault.list_files.return_value = []
        mock_vault.get_audit_trail.return_value = []

        cycle, variant = loop.begin_cycle(mock_vault, "CHAT", "test query")
        delta = loop.record_outcome(
            cycle.cycle_id, "ACCEPTED", context_score=0.0
        )
        assert delta is not None

    def test_loop_stats_include_context(self):
        from agent.qopc_feedback import QOPCLoop
        loop = QOPCLoop()
        stats = loop.get_loop_stats()
        assert "context_scoring" in stats
        assert "has_context" in stats["context_scoring"]
        assert "active_signals" in stats["context_scoring"]

    def test_loop_context_scorer_update(self):
        from agent.qopc_feedback import QOPCLoop
        loop = QOPCLoop()
        loop.context_scorer.update_context("never delete files")
        stats = loop.get_loop_stats()
        assert stats["context_scoring"]["has_context"] is True
        assert "never_delete" in stats["context_scoring"]["active_signals"]


# ─── Agent Context Injection Tests ───────────────────────

class TestAgentContextInjection:
    """Test that user context is injected into the agent's system prompt."""

    @patch("agent.hardened_claude_agent.Anthropic")
    @patch("agent.hardened_claude_agent.AuditLog")
    @patch("agent.hardened_claude_agent.get_quantum_seed", return_value=(42, "OS_URANDOM"))
    def test_set_user_context_injects_into_prompt(self, mock_seed, mock_audit, mock_anthropic):
        from agent.hardened_claude_agent import HardenedClaudeAgent
        agent = HardenedClaudeAgent(api_key="test-key")
        agent.set_user_context("never delete, always ask")
        assert "never delete, always ask" in agent._active_system_prompt
        assert "USER PREFERENCES" in agent._active_system_prompt

    @patch("agent.hardened_claude_agent.Anthropic")
    @patch("agent.hardened_claude_agent.AuditLog")
    @patch("agent.hardened_claude_agent.get_quantum_seed", return_value=(42, "OS_URANDOM"))
    def test_clear_context_restores_base_prompt(self, mock_seed, mock_audit, mock_anthropic):
        from agent.hardened_claude_agent import HardenedClaudeAgent
        agent = HardenedClaudeAgent(api_key="test-key")
        agent.set_user_context("some context")
        assert "USER PREFERENCES" in agent._active_system_prompt

        agent.set_user_context("")
        assert "USER PREFERENCES" not in agent._active_system_prompt
        assert agent._active_system_prompt == agent.system_prompt

    @patch("agent.hardened_claude_agent.Anthropic")
    @patch("agent.hardened_claude_agent.AuditLog")
    @patch("agent.hardened_claude_agent.get_quantum_seed", return_value=(42, "OS_URANDOM"))
    def test_qopc_stats_include_context_info(self, mock_seed, mock_audit, mock_anthropic):
        from agent.hardened_claude_agent import HardenedClaudeAgent
        agent = HardenedClaudeAgent(api_key="test-key")
        agent.set_user_context("keep everything clean")
        stats = agent.get_qopc_stats()
        assert stats.get("enabled") is True
        assert "context_scoring" in stats
        assert stats["context_scoring"]["has_context"] is True

    @patch("agent.hardened_claude_agent.Anthropic")
    @patch("agent.hardened_claude_agent.AuditLog")
    @patch("agent.hardened_claude_agent.get_quantum_seed", return_value=(42, "OS_URANDOM"))
    def test_context_scorer_on_agent(self, mock_seed, mock_audit, mock_anthropic):
        from agent.hardened_claude_agent import HardenedClaudeAgent
        agent = HardenedClaudeAgent(api_key="test-key")
        agent.set_user_context("never delete, always ask before changes")
        assert agent._context_scorer.has_context is True
        signals = agent._context_scorer.active_signals
        assert "never_delete" in signals
        assert "ask_before_action" in signals


# ─── API Endpoint Tests ──────────────────────────────────

class TestContextEndpoints:
    """Test /agent/context POST and GET endpoints."""

    @pytest.fixture
    def client(self):
        """Create a test client for the FastAPI app."""
        import importlib
        # Patch heavy imports before importing api_server
        with patch("agent.file_agent.AetherFileAgent"), \
             patch("vault.watcher.VaultWatcher"), \
             patch("aether_protocol.audit.AuditLog"):
            from api_server import app
            from fastapi.testclient import TestClient
            return TestClient(app)

    def test_context_post_requires_auth(self, client):
        resp = client.post(
            "/agent/context",
            json={"context": "test context"},
        )
        assert resp.status_code == 401

    def test_context_get_requires_auth(self, client):
        resp = client.get("/agent/context")
        assert resp.status_code == 401
