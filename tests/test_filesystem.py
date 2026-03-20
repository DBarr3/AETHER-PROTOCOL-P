#!/usr/bin/env python3
"""
AetherCloud-L — Real Filesystem Wiring Tests
Tests for /vault/scan endpoint, file helpers, and API data transformation.

Aether Systems LLC — Patent Pending
"""

import os
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

# Import the helpers and endpoint under test
from api_server import (
    _file_icon,
    _format_size,
    _guess_category,
    _get_category_by_name,
    _get_folder_icon,
    _commitment_hash,
    app,
)

from fastapi.testclient import TestClient

client = TestClient(app, raise_server_exceptions=False)


# ═══════════════════════════════════════════════════
# TestFileHelpers — unit tests for helper functions
# ═══════════════════════════════════════════════════
class TestFileHelpers:
    """Tests for _file_icon, _format_size, _guess_category, _get_category_by_name, _get_folder_icon."""

    # ── _file_icon ──
    def test_file_icon_python(self):
        assert _file_icon(".py") == "🐍"

    def test_file_icon_js(self):
        assert _file_icon(".js") == "📜"

    def test_file_icon_pdf(self):
        assert _file_icon(".pdf") == "📄"

    def test_file_icon_unknown(self):
        assert _file_icon(".xyz") == "📄"

    def test_file_icon_case_insensitive(self):
        assert _file_icon(".PY") == "🐍"
        assert _file_icon(".Pdf") == "📄"

    # ── _format_size ──
    def test_format_size_bytes(self):
        assert _format_size(500) == "500 B"

    def test_format_size_zero(self):
        assert _format_size(0) == "0 B"

    def test_format_size_kb(self):
        result = _format_size(2048)
        assert "KB" in result

    def test_format_size_mb(self):
        result = _format_size(5 * 1024 * 1024)
        assert "MB" in result

    def test_format_size_gb(self):
        result = _format_size(2 * 1024 ** 3)
        assert "GB" in result

    # ── _guess_category ──
    def test_guess_category_python(self):
        assert _guess_category(".py") == "CODE"

    def test_guess_category_pdf(self):
        assert _guess_category(".pdf") == "PATENT"

    def test_guess_category_xlsx(self):
        assert _guess_category(".xlsx") == "FINANCE"

    def test_guess_category_unknown(self):
        assert _guess_category(".xyz") == "PERSONAL"

    # ── _get_category_by_name ──
    def test_category_by_name_patent(self):
        assert _get_category_by_name("patent_filing_2026.pdf", ".pdf") == "PATENT"

    def test_category_by_name_trading(self):
        assert _get_category_by_name("spy_options_data.csv", ".csv") == "TRADING"

    def test_category_by_name_security(self):
        assert _get_category_by_name("api_key_backup.txt", ".txt") == "SECURITY"

    def test_category_by_name_falls_to_ext(self):
        assert _get_category_by_name("report.xlsx", ".xlsx") == "FINANCE"

    def test_category_by_name_extra_ext(self):
        assert _get_category_by_name("build.sh", ".sh") == "CODE"

    # ── _get_folder_icon ──
    def test_folder_icon_code(self):
        assert _get_folder_icon("src") == "💻"

    def test_folder_icon_patent(self):
        assert _get_folder_icon("patent_filings") == "📋"

    def test_folder_icon_finance(self):
        assert _get_folder_icon("trading_data") == "📈"

    def test_folder_icon_security(self):
        assert _get_folder_icon("vault_keys") == "🛡"

    def test_folder_icon_default(self):
        assert _get_folder_icon("random_stuff") == "📁"

    # ── _commitment_hash ──
    def test_commitment_hash_returns_string(self):
        h = _commitment_hash({"key": "value"})
        assert isinstance(h, str)
        assert len(h) == 16

    def test_commitment_hash_deterministic(self):
        a = _commitment_hash("test data")
        b = _commitment_hash("test data")
        assert a == b

    def test_commitment_hash_different_input(self):
        a = _commitment_hash("input_a")
        b = _commitment_hash("input_b")
        assert a != b


# ═══════════════════════════════════════════════════
# TestVaultScan — /vault/scan endpoint with real filesystem (tmp_path)
# ═══════════════════════════════════════════════════
class TestVaultScan:
    """Tests for POST /vault/scan using real filesystem via tmp_path."""

    def test_scan_empty_directory(self, tmp_path):
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["vault_path"] == str(tmp_path)
        assert data["folder_count"] == 0
        assert data["file_count"] == 0
        assert data["folders"] == []

    def test_scan_with_files_at_root(self, tmp_path):
        (tmp_path / "readme.md").write_text("hello")
        (tmp_path / "main.py").write_text("print('hi')")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["file_count"] == 2
        # Root files get wrapped in a "root files" folder
        root_folder = [f for f in data["folders"] if f["id"] == "_root_files"]
        assert len(root_folder) == 1
        assert root_folder[0]["count"] == 2

    def test_scan_with_subdirectories(self, tmp_path):
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        (code_dir / "app.py").write_text("import os")
        (code_dir / "util.js").write_text("export default {}")

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "guide.pdf").write_bytes(b"%PDF-1.4")

        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["folder_count"] == 2
        assert data["file_count"] == 3

        folder_names = [f["name"] for f in data["folders"]]
        assert "code" in folder_names
        assert "docs" in folder_names

    def test_scan_hidden_files_excluded(self, tmp_path):
        (tmp_path / ".hidden_file").write_text("secret")
        (tmp_path / "visible.txt").write_text("hello")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        assert data["file_count"] == 1

    def test_scan_hidden_folders_excluded(self, tmp_path):
        hidden = tmp_path / ".git"
        hidden.mkdir()
        (hidden / "config").write_text("core")
        visible = tmp_path / "src"
        visible.mkdir()
        (visible / "main.py").write_text("pass")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        folder_names = [f["name"] for f in data["folders"]]
        assert ".git" not in folder_names
        assert "src" in folder_names

    def test_scan_dollar_prefixed_excluded(self, tmp_path):
        recycle = tmp_path / "$Recycle.Bin"
        recycle.mkdir()
        (recycle / "junk.txt").write_text("trash")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        folder_names = [f["name"] for f in data["folders"]]
        assert "$Recycle.Bin" not in folder_names

    def test_scan_nonexistent_path(self):
        resp = client.post("/vault/scan", json={"vault_path": "/nonexistent/path/xyz"})
        assert resp.status_code == 404

    def test_scan_file_instead_of_directory(self, tmp_path):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        resp = client.post("/vault/scan", json={"vault_path": str(file_path)})
        assert resp.status_code == 400

    def test_scan_folder_capped_at_12(self, tmp_path):
        for i in range(15):
            d = tmp_path / f"folder_{i:02d}"
            d.mkdir()
            (d / "file.txt").write_text(f"content {i}")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        assert data["folder_count"] <= 12

    def test_scan_files_per_folder_capped_at_8(self, tmp_path):
        big_dir = tmp_path / "many_files"
        big_dir.mkdir()
        for i in range(15):
            (big_dir / f"file_{i:02d}.txt").write_text(f"data {i}")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        folder = [f for f in data["folders"] if f["name"] == "many_files"][0]
        assert len(folder["files"]) <= 8
        assert folder["count"] == 15  # count reflects real total

    def test_scan_file_metadata_correct(self, tmp_path):
        test_dir = tmp_path / "project"
        test_dir.mkdir()
        py_file = test_dir / "main.py"
        py_file.write_text("print('hello world')")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        folder = [f for f in data["folders"] if f["name"] == "project"][0]
        file_entry = folder["files"][0]
        assert file_entry["name"] == "main.py"
        assert file_entry["extension"] == ".py"
        assert file_entry["icon"] == "🐍"
        assert file_entry["category"] == "CODE"
        assert "path" in file_entry
        assert "size" in file_entry

    def test_scan_returns_scanned_at(self, tmp_path):
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        assert "scanned_at" in data
        # Should be a valid ISO datetime
        datetime.fromisoformat(data["scanned_at"])

    def test_scan_folder_icons_assigned(self, tmp_path):
        (tmp_path / "patents").mkdir()
        (tmp_path / "src").mkdir()
        (tmp_path / "trading").mkdir()
        for d in ["patents", "src", "trading"]:
            (tmp_path / d / "dummy.txt").write_text("x")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        icon_map = {f["name"]: f["icon"] for f in data["folders"]}
        assert icon_map["patents"] == "📋"
        assert icon_map["src"] == "💻"
        assert icon_map["trading"] == "📈"

    def test_scan_mixed_root_and_folders(self, tmp_path):
        (tmp_path / "notes.txt").write_text("some notes")
        sub = tmp_path / "code"
        sub.mkdir()
        (sub / "app.js").write_text("console.log('hi')")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        # Should have root files folder + code folder
        ids = [f["id"] for f in data["folders"]]
        assert "_root_files" in ids
        assert "code" in ids


# ═══════════════════════════════════════════════════
# TestTransformAPIData — verify data shape and contract
# ═══════════════════════════════════════════════════
class TestTransformAPIData:
    """Tests that /vault/scan response conforms to the expected data contract."""

    def test_response_has_required_keys(self, tmp_path):
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        required = ["vault_path", "vault_name", "folder_count", "file_count", "folders", "scanned_at"]
        for key in required:
            assert key in data, f"Missing key: {key}"

    def test_folder_entry_has_required_keys(self, tmp_path):
        sub = tmp_path / "test_folder"
        sub.mkdir()
        (sub / "a.txt").write_text("data")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        folder = data["folders"][0]
        for key in ["id", "name", "path", "count", "file_count", "files", "icon", "modified"]:
            assert key in folder, f"Missing folder key: {key}"

    def test_file_entry_has_required_keys(self, tmp_path):
        sub = tmp_path / "data"
        sub.mkdir()
        (sub / "report.csv").write_text("col1,col2\n1,2")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        file_entry = data["folders"][0]["files"][0]
        for key in ["name", "extension", "size", "size_bytes", "icon", "category", "path"]:
            assert key in file_entry, f"Missing file key: {key}"

    def test_vault_name_matches_directory(self, tmp_path):
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        assert data["vault_name"] == tmp_path.name

    def test_count_and_file_count_match(self, tmp_path):
        sub = tmp_path / "folder"
        sub.mkdir()
        for i in range(5):
            (sub / f"f{i}.txt").write_text(f"data{i}")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        folder = data["folders"][0]
        assert folder["count"] == folder["file_count"]

    def test_folders_sorted_alphabetically(self, tmp_path):
        for name in ["zebra", "alpha", "mango"]:
            d = tmp_path / name
            d.mkdir()
            (d / "f.txt").write_text("x")
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        names = [f["name"] for f in data["folders"]]
        assert names == sorted(names)

    def test_size_bytes_is_integer(self, tmp_path):
        sub = tmp_path / "files"
        sub.mkdir()
        (sub / "data.json").write_text('{"key": "value"}')
        resp = client.post("/vault/scan", json={"vault_path": str(tmp_path)})
        data = resp.json()
        file_entry = data["folders"][0]["files"][0]
        assert isinstance(file_entry["size_bytes"], int)
