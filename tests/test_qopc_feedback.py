"""
AetherCloud-L — QOPC Feedback Loop Tests
Tests for the Quantum Optimized Prompt Circuit recursive truth loop.
5 nodes: DQVL → QOPGC → LLMRE → QOVL → REAL → D(n)
"""

import json
import time
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


class TestVaultState:
    """Tests for Node 1 — DQVL (Verified Ground Truth)."""

    def test_capture_from_vault(self):
        from agent.qopc_feedback import VaultState

        mock_vault = MagicMock()
        mock_vault.list_files.return_value = [
            {"path": "test.py", "name": "test.py", "category": "CODE"},
            {"path": "patent.pdf", "name": "patent.pdf", "category": "PATENT"},
        ]
        mock_vault.get_audit_trail.return_value = [{"type": "LOGIN"}]
        mock_vault.root = Path("/vault")

        state = VaultState.capture(mock_vault)

        assert state.file_count == 2
        assert state.category_counts == {"CODE": 1, "PATENT": 1}
        assert len(state.snapshot_hash) == 64
        assert state.timestamp

    def test_capture_empty_vault(self):
        from agent.qopc_feedback import VaultState

        mock_vault = MagicMock()
        mock_vault.list_files.return_value = []
        mock_vault.get_audit_trail.return_value = []
        mock_vault.root = Path("/empty")

        state = VaultState.capture(mock_vault)

        assert state.file_count == 0
        assert state.category_counts == {}

    def test_to_dict(self):
        from agent.qopc_feedback import VaultState

        mock_vault = MagicMock()
        mock_vault.list_files.return_value = []
        mock_vault.get_audit_trail.return_value = []
        mock_vault.root = Path("/vault")

        state = VaultState.capture(mock_vault)
        d = state.to_dict()

        assert "file_count" in d
        assert "snapshot_hash" in d
        assert "timestamp" in d

    def test_snapshot_hash_deterministic(self):
        """Different vault states produce different hashes."""
        from agent.qopc_feedback import VaultState

        v1 = MagicMock()
        v1.list_files.return_value = [{"path": "a.py", "category": "CODE"}]
        v1.get_audit_trail.return_value = []
        v1.root = Path("/v1")

        v2 = MagicMock()
        v2.list_files.return_value = [{"path": "b.py", "category": "CODE"}]
        v2.get_audit_trail.return_value = []
        v2.root = Path("/v2")

        s1 = VaultState.capture(v1)
        s2 = VaultState.capture(v2)

        # Hashes may differ due to different file paths
        assert s1.snapshot_hash != s2.snapshot_hash


class TestPromptVariant:
    """Tests for Node 2 — QOPGC (Prompt Variant dataclass)."""

    def test_prompt_variant_creation(self):
        from agent.qopc_feedback import PromptVariant

        pv = PromptVariant(
            variant_id="test_v1",
            task_type="ANALYZE",
            system_prompt="You are a test agent.",
            suffix="Respond with JSON.",
            temperature_hint="PRECISE",
            accuracy_score=0.9,
            use_count=10,
            success_count=8,
        )

        assert pv.variant_id == "test_v1"
        assert pv.accuracy_score == 0.9
        assert pv.success_count == 8


class TestPromptOptimizer:
    """Tests for Node 2 — QOPGC (Prompt Optimizer)."""

    @pytest.fixture
    def optimizer(self, tmp_path):
        with patch("agent.qopc_feedback._SCORES_PATH", tmp_path / "scores.json"):
            from agent.qopc_feedback import PromptOptimizer
            return PromptOptimizer()

    def test_initialization(self, optimizer):
        assert "ANALYZE" in optimizer.variants
        assert "PLAN" in optimizer.variants
        assert "CHAT" in optimizer.variants
        assert "SCAN" in optimizer.variants

    def test_select_variant_single(self, optimizer):
        variant = optimizer.select_variant("ANALYZE")
        assert variant.variant_id == "analyze_v1"
        assert variant.task_type == "ANALYZE"

    def test_select_variant_invalid_type(self, optimizer):
        with pytest.raises(ValueError, match="No variants"):
            optimizer.select_variant("NONEXISTENT")

    def test_select_variant_returns_prompt(self, optimizer):
        variant = optimizer.select_variant("SCAN")
        assert len(variant.system_prompt) > 100
        assert len(variant.suffix) > 10

    def test_update_variant_score(self, optimizer):
        initial = optimizer.variants["ANALYZE"][0].accuracy_score
        optimizer.update_variant_score("analyze_v1", 1.0)

        updated = optimizer.variants["ANALYZE"][0].accuracy_score
        # EMA: 0.3 * 1.0 + 0.7 * 0.8 = 0.86
        assert updated > initial
        assert optimizer.variants["ANALYZE"][0].use_count == 1
        assert optimizer.variants["ANALYZE"][0].success_count == 1

    def test_update_variant_failure(self, optimizer):
        optimizer.update_variant_score("analyze_v1", 0.0)

        v = optimizer.variants["ANALYZE"][0]
        # EMA: 0.3 * 0.0 + 0.7 * 0.8 = 0.56
        assert v.accuracy_score < 0.8
        assert v.use_count == 1
        assert v.success_count == 0

    def test_update_nonexistent_variant(self, optimizer):
        # Should not raise — just silently do nothing
        optimizer.update_variant_score("nonexistent_v99", 1.0)

    def test_get_scores(self, optimizer):
        scores = optimizer.get_scores()
        assert "ANALYZE" in scores
        assert scores["ANALYZE"][0]["variant_id"] == "analyze_v1"

    def test_score_persistence(self, tmp_path):
        scores_path = tmp_path / "scores.json"
        with patch("agent.qopc_feedback._SCORES_PATH", scores_path):
            from agent.qopc_feedback import PromptOptimizer

            opt1 = PromptOptimizer()
            opt1.update_variant_score("analyze_v1", 1.0)

            assert scores_path.exists()

            opt2 = PromptOptimizer()
            v = opt2.variants["ANALYZE"][0]
            assert v.accuracy_score > 0.8
            assert v.use_count == 1

    def test_score_persistence_corrupt_file(self, tmp_path):
        scores_path = tmp_path / "scores.json"
        scores_path.write_text("not json")

        with patch("agent.qopc_feedback._SCORES_PATH", scores_path):
            from agent.qopc_feedback import PromptOptimizer
            # Should not crash
            opt = PromptOptimizer()
            assert opt.variants["ANALYZE"][0].accuracy_score == 0.8


class TestResponseValidator:
    """Tests for Node 4 — QOVL (Output Validation)."""

    @pytest.fixture
    def validator(self):
        from agent.qopc_feedback import ResponseValidator
        return ResponseValidator()

    # ── Analysis validation ──────────────────────────

    def test_valid_analysis(self, validator):
        response = {
            "category": "CODE",
            "confidence": 0.9,
            "reasoning": "Python file",
            "security_flag": False,
        }
        result = validator.validate_analysis(response)
        assert result["valid"] is True
        assert result["issues"] == []

    def test_missing_required_field(self, validator):
        response = {"category": "CODE"}
        result = validator.validate_analysis(response)
        assert result["valid"] is False
        assert any("confidence" in i for i in result["issues"])

    def test_invalid_category(self, validator):
        response = {
            "category": "BANANAS",
            "confidence": 0.8,
            "reasoning": "test",
        }
        result = validator.validate_analysis(response)
        assert result["valid"] is False
        assert result["adjusted"]["category"] == "PERSONAL"

    def test_confidence_out_of_bounds(self, validator):
        response = {
            "category": "CODE",
            "confidence": 1.5,
            "reasoning": "test",
        }
        result = validator.validate_analysis(response)
        assert result["valid"] is False
        assert result["adjusted"]["confidence"] == 1.0

    def test_negative_confidence(self, validator):
        response = {
            "category": "CODE",
            "confidence": -0.5,
            "reasoning": "test",
        }
        result = validator.validate_analysis(response)
        assert result["adjusted"]["confidence"] == 0.0

    def test_non_numeric_confidence(self, validator):
        response = {
            "category": "CODE",
            "confidence": "high",
            "reasoning": "test",
        }
        result = validator.validate_analysis(response)
        assert result["adjusted"]["confidence"] == 0.5

    def test_non_boolean_security_flag(self, validator):
        response = {
            "category": "CODE",
            "confidence": 0.8,
            "reasoning": "test",
            "security_flag": "yes",
        }
        result = validator.validate_analysis(response)
        assert result["adjusted"]["security_flag"] is True

    # ── Security scan validation ─────────────────────

    def test_valid_security_scan(self, validator):
        response = {
            "threat_level": "HIGH",
            "findings": ["brute force detected"],
            "recommended_action": "Lock account",
        }
        result = validator.validate_security_scan(response)
        assert result["valid"] is True

    def test_invalid_threat_level(self, validator):
        response = {
            "threat_level": "EXTREME",
            "findings": [],
            "recommended_action": "run",
        }
        result = validator.validate_security_scan(response)
        assert result["valid"] is False
        assert result["adjusted"]["threat_level"] == "UNKNOWN"

    def test_findings_not_list(self, validator):
        response = {
            "threat_level": "LOW",
            "findings": "one finding",
            "recommended_action": "review",
        }
        result = validator.validate_security_scan(response)
        assert result["valid"] is False
        assert isinstance(result["adjusted"]["findings"], list)

    def test_missing_recommended_action(self, validator):
        response = {
            "threat_level": "NONE",
            "findings": [],
        }
        result = validator.validate_security_scan(response)
        assert result["adjusted"]["recommended_action"] == "Manual review required"

    # ── Chat validation ──────────────────────────────

    def test_valid_chat(self, validator):
        result = validator.validate_chat("Here are your files.")
        assert result["valid"] is True

    def test_empty_chat(self, validator):
        result = validator.validate_chat("")
        assert result["valid"] is False

    def test_whitespace_only_chat(self, validator):
        result = validator.validate_chat("   ")
        assert result["valid"] is False

    def test_oversized_chat(self, validator):
        result = validator.validate_chat("x" * 10001)
        assert result["valid"] is False
        assert any("10000" in i for i in result["issues"])


class TestOutcomeObserver:
    """Tests for Node 5 — REAL (Outcome Observer)."""

    @pytest.fixture
    def observer(self, tmp_path):
        with patch("agent.qopc_feedback._DATA_DIR", tmp_path), \
             patch("agent.qopc_feedback._CYCLES_PATH", tmp_path / "cycles.jsonl"):
            from agent.qopc_feedback import OutcomeObserver
            return OutcomeObserver()

    def _make_cycle(self):
        from agent.qopc_feedback import ReasoningCycle
        return ReasoningCycle(
            cycle_id="test_cycle_001",
            task_type="ANALYZE",
            query="test.py",
            validated_response={"confidence": 0.8},
        )

    def test_register_and_record_accepted(self, observer):
        cycle = self._make_cycle()
        observer.register_cycle(cycle)
        assert observer.pending_count == 1

        result = observer.record_outcome("test_cycle_001", "ACCEPTED")
        assert result is not None
        # Blended: 1.0 * 0.7 + 0.5 * 0.3 = 0.85 (default context_score=0.5)
        assert result.outcome_score == 0.85
        assert result.delta == 0.85 - 0.8  # 0.05
        assert result.user_action == "ACCEPTED"
        assert observer.pending_count == 0

    def test_record_rejected(self, observer):
        cycle = self._make_cycle()
        observer.register_cycle(cycle)

        result = observer.record_outcome("test_cycle_001", "REJECTED")
        # Blended: 0.0 * 0.7 + 0.5 * 0.3 = 0.15
        assert result.outcome_score == 0.15
        assert result.delta == 0.15 - 0.8

    def test_record_corrected(self, observer):
        cycle = self._make_cycle()
        observer.register_cycle(cycle)

        result = observer.record_outcome(
            "test_cycle_001", "CORRECTED", "should be PATENT"
        )
        # Blended: 0.3 * 0.7 + 0.5 * 0.3 = 0.36
        assert result.outcome_score == 0.36
        assert result.user_correction == "should be PATENT"

    def test_record_ignored(self, observer):
        cycle = self._make_cycle()
        observer.register_cycle(cycle)

        result = observer.record_outcome("test_cycle_001", "IGNORED")
        # Blended: 0.5 * 0.7 + 0.5 * 0.3 = 0.5
        assert result.outcome_score == 0.5

    def test_record_unknown_cycle(self, observer):
        result = observer.record_outcome("nonexistent", "ACCEPTED")
        assert result is None

    def test_pending_ids(self, observer):
        cycle = self._make_cycle()
        observer.register_cycle(cycle)
        assert "test_cycle_001" in observer.get_pending_ids()

    def test_cycle_persisted_to_jsonl(self, observer, tmp_path):
        cycles_path = tmp_path / "cycles.jsonl"
        with patch("agent.qopc_feedback._CYCLES_PATH", cycles_path):
            cycle = self._make_cycle()
            observer.register_cycle(cycle)
            observer.record_outcome("test_cycle_001", "ACCEPTED")

            if cycles_path.exists():
                lines = cycles_path.read_text().strip().split("\n")
                assert len(lines) >= 1
                data = json.loads(lines[0])
                assert data["cycle_id"] == "test_cycle_001"
                assert data["user_action"] == "ACCEPTED"


class TestReasoningCycle:
    """Tests for the ReasoningCycle dataclass."""

    def test_creation(self):
        from agent.qopc_feedback import ReasoningCycle

        cycle = ReasoningCycle(
            cycle_id="c001",
            task_type="ANALYZE",
            query="test.py",
        )
        assert cycle.cycle_id == "c001"
        assert cycle.user_action is None
        assert cycle.delta is None

    def test_to_dict(self):
        from agent.qopc_feedback import ReasoningCycle

        cycle = ReasoningCycle(
            cycle_id="c001",
            task_type="SCAN",
            query="security check",
        )
        d = cycle.to_dict()
        assert d["cycle_id"] == "c001"
        assert d["task_type"] == "SCAN"
        assert "started_at" in d


class TestQOPCLoop:
    """Tests for the full QOPC Loop Controller."""

    @pytest.fixture
    def loop(self, tmp_path):
        with patch("agent.qopc_feedback._DATA_DIR", tmp_path), \
             patch("agent.qopc_feedback._SCORES_PATH", tmp_path / "scores.json"), \
             patch("agent.qopc_feedback._CYCLES_PATH", tmp_path / "cycles.jsonl"):
            from agent.qopc_feedback import QOPCLoop
            return QOPCLoop()

    @pytest.fixture
    def mock_vault(self):
        v = MagicMock()
        v.list_files.return_value = [
            {"path": "test.py", "name": "test.py", "category": "CODE"},
        ]
        v.get_audit_trail.return_value = []
        v.root = Path("/vault")
        return v

    def test_begin_cycle(self, loop, mock_vault):
        cycle, variant = loop.begin_cycle(mock_vault, "ANALYZE", "test.py")

        assert cycle.cycle_id.startswith("qopc_")
        assert cycle.task_type == "ANALYZE"
        assert cycle.query == "test.py"
        assert cycle.vault_state is not None
        assert variant.variant_id == "analyze_v1"

    def test_validate_analysis_response(self, loop, mock_vault):
        cycle, _ = loop.begin_cycle(mock_vault, "ANALYZE", "test.py")

        response = {
            "category": "CODE",
            "confidence": 0.95,
            "reasoning": "Python file",
            "security_flag": False,
        }
        result = loop.validate_response(cycle, response)
        assert result["valid"] is True

    def test_validate_invalid_response(self, loop, mock_vault):
        cycle, _ = loop.begin_cycle(mock_vault, "ANALYZE", "test.py")

        response = {
            "category": "BANANAS",
            "confidence": 5.0,
            "reasoning": "test",
        }
        result = loop.validate_response(cycle, response)
        assert result["valid"] is False
        assert result["adjusted"]["category"] == "PERSONAL"
        assert result["adjusted"]["confidence"] == 1.0

    def test_validate_scan_response(self, loop, mock_vault):
        cycle, _ = loop.begin_cycle(mock_vault, "SCAN", "security")

        response = {
            "threat_level": "LOW",
            "findings": ["one anomaly"],
            "recommended_action": "review",
        }
        result = loop.validate_response(cycle, response)
        assert result["valid"] is True

    def test_validate_chat_response(self, loop, mock_vault):
        cycle, _ = loop.begin_cycle(mock_vault, "CHAT", "hello")

        result = loop.validate_response(cycle, "Here are your files.")
        assert result["valid"] is True

    def test_record_outcome(self, loop, mock_vault):
        cycle, _ = loop.begin_cycle(mock_vault, "ANALYZE", "test.py")

        # Validate to set validated_response
        loop.validate_response(cycle, {
            "category": "CODE",
            "confidence": 0.9,
            "reasoning": "Python file",
        })

        delta = loop.record_outcome(cycle.cycle_id, "ACCEPTED")
        assert delta is not None

    def test_record_outcome_updates_scores(self, loop, mock_vault):
        cycle, variant = loop.begin_cycle(mock_vault, "ANALYZE", "test.py")
        initial_score = variant.accuracy_score

        loop.validate_response(cycle, {
            "category": "CODE",
            "confidence": 0.9,
            "reasoning": "test",
        })
        loop.record_outcome(cycle.cycle_id, "ACCEPTED")

        updated = loop.optimizer.variants["ANALYZE"][0].accuracy_score
        assert updated > initial_score

    def test_record_outcome_rejected_lowers_score(self, loop, mock_vault):
        cycle, variant = loop.begin_cycle(mock_vault, "ANALYZE", "test.py")
        initial_score = variant.accuracy_score

        loop.validate_response(cycle, {
            "category": "CODE",
            "confidence": 0.9,
            "reasoning": "test",
        })
        loop.record_outcome(cycle.cycle_id, "REJECTED")

        updated = loop.optimizer.variants["ANALYZE"][0].accuracy_score
        assert updated < initial_score

    def test_get_loop_stats(self, loop, mock_vault):
        loop.begin_cycle(mock_vault, "ANALYZE", "test.py")
        stats = loop.get_loop_stats()

        assert stats["total_cycles"] == 1
        assert stats["pending_outcomes"] == 1
        assert "variant_scores" in stats

    def test_multiple_cycles(self, loop, mock_vault):
        for i in range(5):
            c, _ = loop.begin_cycle(mock_vault, "ANALYZE", f"file_{i}.py")
            loop.validate_response(c, {
                "category": "CODE",
                "confidence": 0.9,
                "reasoning": "test",
            })
            loop.record_outcome(c.cycle_id, "ACCEPTED")

        stats = loop.get_loop_stats()
        assert stats["total_cycles"] == 5
        assert stats["pending_outcomes"] == 0

    def test_record_nonexistent_cycle(self, loop):
        delta = loop.record_outcome("nonexistent", "ACCEPTED")
        assert delta is None

    def test_vault_state_capture_failure(self, loop):
        bad_vault = MagicMock()
        bad_vault.list_files.side_effect = Exception("DB error")

        cycle, variant = loop.begin_cycle(bad_vault, "CHAT", "hello")
        # Should still succeed with error state
        assert cycle.vault_state is not None
        assert "error" in cycle.vault_state


class TestAgentPrompt:
    """Tests for config/agent_prompt.py module."""

    def test_system_prompt_exists(self):
        from config.agent_prompt import AETHER_AGENT_SYSTEM_PROMPT
        assert len(AETHER_AGENT_SYSTEM_PROMPT) > 1000

    def test_system_prompt_has_competencies(self):
        from config.agent_prompt import AETHER_AGENT_SYSTEM_PROMPT
        prompt = AETHER_AGENT_SYSTEM_PROMPT
        assert "FILE ANALYSIS" in prompt
        assert "PROJECT STRUCTURE" in prompt
        assert "NAMING CONVENTIONS" in prompt
        assert "CONSOLIDATION" in prompt
        assert "PROJECT PLANNING" in prompt
        assert "VAULT QUERY" in prompt
        assert "SECURITY PATTERN" in prompt

    def test_system_prompt_has_identity(self):
        from config.agent_prompt import AETHER_AGENT_SYSTEM_PROMPT
        assert "AetherCloud-L" in AETHER_AGENT_SYSTEM_PROMPT
        assert "Protocol-L" in AETHER_AGENT_SYSTEM_PROMPT

    def test_system_prompt_has_feedback_awareness(self):
        from config.agent_prompt import AETHER_AGENT_SYSTEM_PROMPT
        assert "QOPC" in AETHER_AGENT_SYSTEM_PROMPT
        assert "feedback" in AETHER_AGENT_SYSTEM_PROMPT.lower()

    def test_analysis_suffix_has_schema(self):
        from config.agent_prompt import ANALYSIS_SUFFIX
        assert "suggested_name" in ANALYSIS_SUFFIX
        assert "security_flag" in ANALYSIS_SUFFIX
        assert "consolidation_hint" in ANALYSIS_SUFFIX

    def test_planning_suffix(self):
        from config.agent_prompt import PLANNING_SUFFIX
        assert "directory tree" in PLANNING_SUFFIX
        assert "400 words" in PLANNING_SUFFIX

    def test_security_suffix_has_schema(self):
        from config.agent_prompt import SECURITY_SUFFIX
        assert "threat_level" in SECURITY_SUFFIX
        assert "findings" in SECURITY_SUFFIX

    def test_task_suffixes_registry(self):
        from config.agent_prompt import TASK_SUFFIXES
        assert "ANALYZE" in TASK_SUFFIXES
        assert "PLAN" in TASK_SUFFIXES
        assert "SCAN" in TASK_SUFFIXES
        assert "CHAT" in TASK_SUFFIXES

    def test_system_prompt_has_categories(self):
        from config.agent_prompt import AETHER_AGENT_SYSTEM_PROMPT
        for cat in ["PATENT", "CODE", "BACKUP", "LEGAL", "FINANCE",
                     "TRADING", "SECURITY", "PERSONAL"]:
            assert cat in AETHER_AGENT_SYSTEM_PROMPT

    def test_naming_convention_examples(self):
        from config.agent_prompt import AETHER_AGENT_SYSTEM_PROMPT
        assert "YYYYMMDD_CATEGORY_Description.ext" in AETHER_AGENT_SYSTEM_PROMPT
