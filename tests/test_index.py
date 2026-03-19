"""
AetherCloud-L — Index Tests
Tests for searchable file index.
"""

import pytest
from vault.index import VaultIndex


class TestVaultIndex:
    """Tests for VaultIndex search functionality."""

    def test_index_creation(self, vault_index):
        assert vault_index is not None

    def test_upsert_and_get(self, vault_index):
        vault_index.upsert(
            path="test.py",
            name="test.py",
            extension=".py",
            size=1024,
            content_hash="abc123",
            modified=1710806400.0,
        )
        result = vault_index.get("test.py")
        assert result is not None
        assert result["name"] == "test.py"
        assert result["size"] == 1024

    def test_upsert_update(self, vault_index):
        vault_index.upsert("f.txt", "f.txt", ".txt", 100, "h1", 1.0)
        vault_index.upsert("f.txt", "f.txt", ".txt", 200, "h2", 2.0)
        result = vault_index.get("f.txt")
        assert result["size"] == 200
        assert result["content_hash"] == "h2"

    def test_remove(self, vault_index):
        vault_index.upsert("del.txt", "del.txt", ".txt", 50, "h", 1.0)
        vault_index.remove("del.txt")
        assert vault_index.get("del.txt") is None

    def test_search_by_query(self, vault_index):
        vault_index.upsert("script.py", "script.py", ".py", 512, "h1", 1.0)
        vault_index.upsert("data.csv", "data.csv", ".csv", 256, "h2", 2.0)
        results = vault_index.search(query="script")
        assert len(results) == 1
        assert results[0]["name"] == "script.py"

    def test_search_by_extension(self, vault_index):
        vault_index.upsert("a.py", "a.py", ".py", 100, "h1", 1.0)
        vault_index.upsert("b.py", "b.py", ".py", 200, "h2", 2.0)
        vault_index.upsert("c.txt", "c.txt", ".txt", 300, "h3", 3.0)
        results = vault_index.search(extension=".py")
        assert len(results) == 2

    def test_search_by_category(self, vault_index):
        vault_index.upsert("a.py", "a.py", ".py", 100, "h1", 1.0, category="code")
        vault_index.upsert("b.pdf", "b.pdf", ".pdf", 200, "h2", 2.0, category="patent")
        results = vault_index.search(category="code")
        assert len(results) == 1

    def test_search_no_results(self, vault_index):
        results = vault_index.search(query="nonexistent")
        assert len(results) == 0

    def test_search_limit(self, vault_index):
        for i in range(20):
            vault_index.upsert(f"f{i}.txt", f"f{i}.txt", ".txt", i, f"h{i}", float(i))
        results = vault_index.search(limit=5)
        assert len(results) == 5

    def test_count(self, vault_index):
        assert vault_index.count() == 0
        vault_index.upsert("a.txt", "a.txt", ".txt", 10, "h", 1.0)
        assert vault_index.count() == 1

    def test_reindex(self, vault_index, vault_root):
        (vault_root / "file1.txt").write_text("hello")
        (vault_root / "file2.py").write_text("print(1)")
        count = vault_index.reindex(str(vault_root))
        assert count == 2
        assert vault_index.count() == 2

    def test_get_nonexistent(self, vault_index):
        assert vault_index.get("nope.txt") is None

    def test_search_with_tags(self, vault_index):
        vault_index.upsert(
            "tagged.py", "tagged.py", ".py", 100, "h", 1.0,
            tags="important,review"
        )
        results = vault_index.search(query="important")
        assert len(results) == 1

    def test_close(self, vault_index):
        vault_index.close()
        # Should not raise
