"""
AetherCloud-L — Organizer Tests
Tests for naming conventions and file organization.
"""

import time
import pytest
from pathlib import Path

from agent.organizer import FileOrganizer


class TestFileOrganizer:
    """Tests for FileOrganizer naming conventions."""

    def test_organizer_creation(self, organizer):
        assert organizer is not None

    def test_is_conventioned_valid(self, organizer):
        assert organizer.is_conventioned("20260319_CODE_Script.py")

    def test_is_conventioned_invalid(self, organizer):
        assert not organizer.is_conventioned("my_script.py")

    def test_suggest_rename_python(self, organizer):
        result = organizer.suggest_rename("/path/to/script.py")
        assert result.endswith(".py")
        assert "_CODE_" in result

    def test_suggest_rename_pdf(self, organizer):
        result = organizer.suggest_rename("/path/to/document.pdf")
        assert result.endswith(".pdf")

    def test_suggest_rename_patent(self, organizer):
        result = organizer.suggest_rename("/path/to/patent_filing.pdf")
        assert "_PATENT_" in result

    def test_suggest_rename_trading(self, organizer):
        result = organizer.suggest_rename("/path/to/trade_log.csv")
        assert "_TRADING_" in result

    def test_suggest_rename_legal(self, organizer):
        result = organizer.suggest_rename("/path/to/contract_nda.docx")
        assert "_LEGAL_" in result

    def test_suggest_rename_backup(self, organizer):
        result = organizer.suggest_rename("/path/to/backup_files.zip")
        assert "_BACKUP_" in result

    def test_suggest_rename_config(self, organizer):
        result = organizer.suggest_rename("/path/to/settings.yaml")
        assert "_CONFIG_" in result

    def test_suggest_rename_already_conventioned(self, organizer):
        name = "20260319_CODE_Script.py"
        result = organizer.suggest_rename(f"/path/{name}")
        assert result == name

    def test_suggest_rename_with_category_override(self, organizer):
        result = organizer.suggest_rename("/path/to/file.txt", category="security")
        assert "_SECURITY_" in result

    def test_suggest_rename_date_format(self, organizer):
        result = organizer.suggest_rename("/path/to/script.py")
        date_part = result.split("_")[0]
        assert len(date_part) == 8
        assert date_part.isdigit()

    def test_suggest_location(self, organizer):
        loc = organizer.suggest_location("/path/to/script.py")
        assert loc == "code"

    def test_suggest_location_patent(self, organizer):
        loc = organizer.suggest_location("/path/to/patent_filing.pdf")
        assert loc == "patent"

    def test_batch_rename_dry_run(self, organizer, tmp_path):
        (tmp_path / "file1.py").write_text("x")
        (tmp_path / "file2.csv").write_text("y")
        results = organizer.batch_rename(
            [str(tmp_path / "file1.py"), str(tmp_path / "file2.csv")],
            dry_run=True,
        )
        assert len(results) == 2
        for r in results:
            assert "original" in r
            assert "suggested" in r
            assert r["applied"] is False

    def test_batch_rename_live(self, organizer, tmp_path):
        f = tmp_path / "messy_file.py"
        f.write_text("content")
        results = organizer.batch_rename([str(f)], dry_run=False)
        assert results[0]["applied"] is True

    def test_record_correction(self, organizer):
        organizer.record_correction("old_name.py", "better_name.py")
        assert organizer._corrections["old_name.py"] == "better_name.py"

    def test_clean_description(self, organizer):
        result = organizer._clean_description("my-messy file_name (copy)")
        assert isinstance(result, str)
        assert " " not in result

    def test_detect_category_archive(self, organizer):
        cat = organizer._detect_category(Path("/path/to/files.zip"))
        assert cat == "archive"

    def test_detect_category_log(self, organizer):
        cat = organizer._detect_category(Path("/path/to/app.log"))
        assert cat == "log"

    def test_categories_is_frozenset(self, organizer):
        assert isinstance(FileOrganizer.CATEGORIES, frozenset)
