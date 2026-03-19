"""
AetherCloud-L — Intent Analyzer Tests
Tests for file intent classification.
"""

import pytest
from agent.intent import IntentAnalyzer


class TestIntentAnalyzer:
    """Tests for IntentAnalyzer."""

    def test_analyzer_creation(self, intent_analyzer):
        assert intent_analyzer is not None

    def test_critical_patent(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/patent_filing.pdf")
        assert result["intent"] == "critical"
        assert result["suggested_action"] == "protect"

    def test_critical_legal(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/legal_contract.docx")
        assert result["intent"] == "critical"

    def test_critical_nda(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/nda_signed.pdf")
        assert result["intent"] == "critical"

    def test_temporary_tmp(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/cache_data.tmp")
        assert result["intent"] == "temporary"
        assert result["suggested_action"] == "flag_for_cleanup"

    def test_temporary_temp(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/temp_output.txt")
        assert result["intent"] == "temporary"

    def test_wip_draft(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/draft_proposal.docx")
        assert result["intent"] == "work_in_progress"

    def test_wip_todo(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/todo_list.txt")
        assert result["intent"] == "work_in_progress"

    def test_archive_final(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/report_final.pdf")
        assert result["intent"] == "archive"

    def test_archive_approved(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/budget_approved.xlsx")
        assert result["intent"] == "archive"

    def test_configuration_json(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/settings.json")
        assert result["intent"] == "configuration"

    def test_configuration_yaml(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/config.yaml")
        assert result["intent"] == "configuration"

    def test_configuration_env(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/.env")
        assert result["intent"] == "configuration"

    def test_backup_bak(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/data.bak")
        assert result["intent"] == "backup"

    def test_default_reference(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/readme.md")
        assert result["intent"] == "reference"
        assert result["confidence"] == 0.5

    def test_batch_analyze(self, intent_analyzer):
        paths = ["/vault/patent.pdf", "/vault/script.py", "/vault/temp.tmp"]
        results = intent_analyzer.batch_analyze(paths)
        assert len(results) == 3
        assert all("intent" in r for r in results)
        assert all("path" in r for r in results)

    def test_result_has_all_fields(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/file.txt")
        assert "intent" in result
        assert "confidence" in result
        assert "reasoning" in result
        assert "suggested_action" in result

    def test_confidence_range(self, intent_analyzer):
        result = intent_analyzer.analyze("/vault/file.txt")
        assert 0.0 <= result["confidence"] <= 1.0
