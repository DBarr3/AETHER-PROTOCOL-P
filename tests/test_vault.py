"""
AetherCloud-L — Vault Tests
Tests for file operations and audit logging.
"""

import pytest
import time
from pathlib import Path


class TestAetherVault:
    """Tests for AetherVault file operations."""

    def test_vault_root_created(self, vault_instance, vault_root):
        assert vault_root.exists()

    def test_list_files_empty(self, vault_instance):
        files = vault_instance.list_files()
        assert isinstance(files, list)

    def test_list_files_with_content(self, populated_vault, vault_root):
        files = populated_vault.list_files()
        names = [f["name"] for f in files]
        assert "document.pdf" in names
        assert "script.py" in names

    def test_list_files_recursive(self, populated_vault):
        files = populated_vault.list_files(recursive=True)
        names = [f["name"] for f in files]
        assert "nested.txt" in names

    def test_list_files_subdirectory(self, populated_vault):
        files = populated_vault.list_files(path="subdir")
        names = [f["name"] for f in files]
        assert "nested.txt" in names

    def test_read_file_metadata(self, populated_vault):
        result = populated_vault.read_file("document.pdf")
        assert result["name"] == "document.pdf"
        assert result["size"] > 0
        assert result["file_hash"]
        assert result["commitment_hash"]

    def test_read_file_hash_is_sha256(self, populated_vault):
        result = populated_vault.read_file("script.py")
        assert len(result["file_hash"]) == 64

    def test_read_nonexistent_file(self, vault_instance):
        with pytest.raises(FileNotFoundError):
            vault_instance.read_file("nonexistent.txt")

    def test_read_directory_raises(self, populated_vault):
        with pytest.raises(IsADirectoryError):
            populated_vault.read_file("subdir")

    def test_move_file(self, populated_vault, vault_root):
        result = populated_vault.move_file("document.pdf", "subdir/document.pdf")
        assert result["moved"] is True
        assert result["commitment_hash"]
        assert (vault_root / "subdir" / "document.pdf").exists()
        assert not (vault_root / "document.pdf").exists()

    def test_move_nonexistent_file(self, vault_instance):
        with pytest.raises(FileNotFoundError):
            vault_instance.move_file("nope.txt", "dest.txt")

    def test_move_with_reason(self, populated_vault):
        result = populated_vault.move_file(
            "data.csv", "subdir/data.csv", reason="agent_suggested"
        )
        assert result["reason"] == "agent_suggested"

    def test_rename_file(self, populated_vault, vault_root):
        result = populated_vault.rename_file("script.py", "main_script.py")
        assert result["renamed"] is True
        assert (vault_root / "main_script.py").exists()
        assert not (vault_root / "script.py").exists()

    def test_rename_nonexistent(self, vault_instance):
        with pytest.raises(FileNotFoundError):
            vault_instance.rename_file("nope.txt", "new.txt")

    def test_rename_with_reason(self, populated_vault):
        result = populated_vault.rename_file(
            "data.csv", "new_data.csv", reason="auto_organized"
        )
        assert result["reason"] == "auto_organized"

    def test_delete_file(self, populated_vault, vault_root):
        result = populated_vault.delete_file("debug.log")
        assert result["deleted"] is True
        assert not (vault_root / "debug.log").exists()

    def test_delete_nonexistent(self, vault_instance):
        with pytest.raises(FileNotFoundError):
            vault_instance.delete_file("nope.txt")

    def test_delete_directory(self, populated_vault, vault_root):
        result = populated_vault.delete_file("subdir")
        assert result["deleted"] is True
        assert not (vault_root / "subdir").exists()

    def test_get_audit_trail(self, populated_vault):
        populated_vault.list_files()
        trail = populated_vault.get_audit_trail()
        assert isinstance(trail, list)

    def test_get_stats(self, populated_vault):
        stats = populated_vault.get_stats()
        assert stats["file_count"] > 0
        assert stats["total_size_bytes"] > 0
        assert "vault_root" in stats

    def test_path_traversal_blocked(self, vault_instance):
        with pytest.raises(ValueError):
            vault_instance._resolve_path("../../etc/passwd")

    def test_commitment_hash_format(self, populated_vault):
        result = populated_vault.read_file("document.pdf")
        assert len(result["commitment_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in result["commitment_hash"])

    def test_list_files_returns_metadata(self, populated_vault):
        files = populated_vault.list_files()
        for f in files:
            assert "name" in f
            assert "path" in f
            assert "size" in f or f.get("is_dir")
            assert "modified" in f

    def test_move_creates_parent_dirs(self, populated_vault, vault_root):
        result = populated_vault.move_file(
            "document.pdf", "new_dir/deep/document.pdf"
        )
        assert result["moved"] is True
        assert (vault_root / "new_dir" / "deep" / "document.pdf").exists()
