"""
AetherCloud-L — Suggestion Engine Tests
Tests for proactive file suggestions.
"""

import time
import pytest
from agent.suggest import SuggestionEngine


class TestSuggestionEngine:
    """Tests for SuggestionEngine."""

    def test_engine_creation(self, suggestion_engine):
        assert suggestion_engine is not None

    def test_naming_suggestions(self, suggestion_engine):
        files = [
            {"name": "messy file.py", "path": "messy file.py", "size": 100, "is_dir": False},
        ]
        suggestions = suggestion_engine.get_suggestions(files)
        naming = [s for s in suggestions if s["type"] == "naming"]
        assert len(naming) > 0

    def test_no_naming_suggestion_for_conventioned(self, suggestion_engine):
        files = [
            {"name": "20260319_CODE_Script.py", "path": "20260319_CODE_Script.py",
             "size": 100, "is_dir": False},
        ]
        suggestions = suggestion_engine.get_suggestions(files)
        naming = [s for s in suggestions if s["type"] == "naming"]
        assert len(naming) == 0

    def test_duplicate_detection(self, suggestion_engine):
        files = [
            {"name": "a.txt", "path": "a.txt", "size": 5000, "is_dir": False},
            {"name": "b.txt", "path": "b.txt", "size": 5000, "is_dir": False},
        ]
        suggestions = suggestion_engine.get_suggestions(files)
        dups = [s for s in suggestions if s["type"] == "duplicate"]
        assert len(dups) > 0

    def test_no_duplicate_for_tiny_files(self, suggestion_engine):
        files = [
            {"name": "a.txt", "path": "a.txt", "size": 10, "is_dir": False},
            {"name": "b.txt", "path": "b.txt", "size": 10, "is_dir": False},
        ]
        suggestions = suggestion_engine.get_suggestions(files)
        dups = [s for s in suggestions if s["type"] == "duplicate"]
        assert len(dups) == 0

    def test_stale_file_detection(self, suggestion_engine):
        old_time = time.time() - (100 * 86400)  # 100 days ago
        files = [
            {"name": "old.txt", "path": "old.txt", "size": 100,
             "modified": old_time, "is_dir": False},
        ]
        suggestions = suggestion_engine.get_suggestions(files)
        stale = [s for s in suggestions if s["type"] == "stale"]
        assert len(stale) > 0

    def test_no_stale_for_recent(self, suggestion_engine):
        files = [
            {"name": "new.txt", "path": "new.txt", "size": 100,
             "modified": time.time(), "is_dir": False},
        ]
        suggestions = suggestion_engine.get_suggestions(files)
        stale = [s for s in suggestions if s["type"] == "stale"]
        assert len(stale) == 0

    def test_sensitive_file_detection(self, suggestion_engine):
        files = [
            {"name": ".env", "path": ".env", "size": 100, "is_dir": False},
            {"name": "credentials.json", "path": "credentials.json",
             "size": 200, "is_dir": False},
        ]
        suggestions = suggestion_engine.get_suggestions(files)
        sensitive = [s for s in suggestions if s["type"] == "security"]
        assert len(sensitive) == 2

    def test_sensitive_pem_key(self, suggestion_engine):
        files = [
            {"name": "server.pem", "path": "server.pem", "size": 100, "is_dir": False},
        ]
        suggestions = suggestion_engine.get_suggestions(files)
        sensitive = [s for s in suggestions if s["type"] == "security"]
        assert len(sensitive) > 0

    def test_dismiss_suggestion(self, suggestion_engine):
        files = [
            {"name": "messy.py", "path": "messy.py", "size": 100, "is_dir": False},
        ]
        suggestions = suggestion_engine.get_suggestions(files)
        assert len(suggestions) > 0
        for s in suggestions:
            suggestion_engine.dismiss(s["id"])
        suggestions2 = suggestion_engine.get_suggestions(files)
        assert len(suggestions2) == 0

    def test_directories_skipped(self, suggestion_engine):
        files = [
            {"name": "subdir", "path": "subdir", "size": 0, "is_dir": True},
        ]
        suggestions = suggestion_engine.get_suggestions(files)
        assert len(suggestions) == 0

    def test_severity_levels(self, suggestion_engine):
        files = [
            {"name": ".env", "path": ".env", "size": 100, "is_dir": False},
            {"name": "messy.py", "path": "messy.py", "size": 100, "is_dir": False},
        ]
        suggestions = suggestion_engine.get_suggestions(files)
        severities = {s["severity"] for s in suggestions}
        assert "high" in severities  # .env
        assert "low" in severities  # naming
