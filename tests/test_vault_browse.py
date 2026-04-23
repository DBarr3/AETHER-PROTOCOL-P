"""
Tests for /vault/browse endpoint and directory browsing helpers.
All filesystem interactions are mocked — no real paths touched.
"""

import sys as _sys
# test_uvt_routes.py installs a minimal api_server stub into sys.modules to
# avoid importing the real api_server (which lacked security/prompt_guard at
# that time). That stub exposes only `svc`, not `app`. Evict it so this
# module always binds to the real api_server.
if "api_server" in _sys.modules and not hasattr(_sys.modules["api_server"], "app"):
    del _sys.modules["api_server"]
del _sys

import os
import stat
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from pathlib import Path
from datetime import datetime

from httpx import AsyncClient, ASGITransport

# Import the app and helpers
import api_server
from api_server import (
    app,
    _format_size,
    _file_icon,
    _guess_category,
    _get_category_by_name,
    _get_folder_icon,
)


# ═══════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════

@pytest.fixture
def client():
    """Sync test client for the FastAPI app."""
    from starlette.testclient import TestClient
    with TestClient(app) as c:
        yield c


def _make_mock_stat(size=1024, mtime=1710886800.0, is_dir=False):
    """Create a mock stat result."""
    mock = MagicMock()
    mock.st_size = size
    mock.st_mtime = mtime
    mock.st_mode = stat.S_IFDIR if is_dir else stat.S_IFREG
    return mock


def _make_mock_path(name, is_dir=False, is_file=None, size=1024, children=None, exists=True):
    """Create a mock Path object."""
    mock = MagicMock(spec=Path)
    mock.name = name
    mock.stem = name.rsplit(".", 1)[0] if "." in name else name
    mock.suffix = "." + name.rsplit(".", 1)[1] if "." in name else ""
    mock.is_dir.return_value = is_dir
    mock.is_file.return_value = not is_dir if is_file is None else is_file
    mock.exists.return_value = exists
    mock.stat.return_value = _make_mock_stat(size=size, is_dir=is_dir)
    mock.__str__ = lambda self: f"/mock/{name}"
    if children is not None:
        mock.iterdir.return_value = iter(children)
    return mock


# ═══════════════════════════════════════════════════
# HELPER FUNCTION TESTS
# ═══════════════════════════════════════════════════

class TestFormatSize:
    def test_bytes(self):
        assert _format_size(100) == "100 B"

    def test_zero_bytes(self):
        assert _format_size(0) == "0 B"

    def test_kilobytes(self):
        result = _format_size(2048)
        assert "KB" in result

    def test_megabytes(self):
        result = _format_size(5 * 1024 * 1024)
        assert "MB" in result

    def test_gigabytes(self):
        result = _format_size(2 * 1024 * 1024 * 1024)
        assert "GB" in result

    def test_exact_1kb(self):
        result = _format_size(1024)
        assert "KB" in result


class TestGetCategoryByName:
    def test_patent_keyword(self):
        assert _get_category_by_name("USPTO_Filing.pdf", ".pdf") == "PATENT"

    def test_trading_keyword(self):
        assert _get_category_by_name("YM_Session.csv", ".csv") == "TRADING"

    def test_security_keyword(self):
        assert _get_category_by_name("api_key_backup.txt", ".txt") == "SECURITY"

    def test_python_file(self):
        assert _get_category_by_name("main.py", ".py") == "CODE"

    def test_json_config(self):
        assert _get_category_by_name("settings.json", ".json") == "CONFIG"

    def test_zip_archive(self):
        assert _get_category_by_name("backup.zip", ".zip") == "ARCHIVE"

    def test_unknown_extension(self):
        assert _get_category_by_name("file.xyz", ".xyz") == "PERSONAL"

    def test_name_keywords_take_precedence(self):
        # "patent" keyword should win over .py extension
        assert _get_category_by_name("patent_script.py", ".py") == "PATENT"

    def test_case_insensitive(self):
        assert _get_category_by_name("PATENT_FILING.PDF", ".pdf") == "PATENT"


class TestFileIcon:
    def test_python(self):
        assert _file_icon(".py") == "🐍"

    def test_pdf(self):
        assert _file_icon(".pdf") == "📄"

    def test_unknown(self):
        assert _file_icon(".xyz") == "📄"

    def test_case_insensitive(self):
        assert _file_icon(".PY") == "🐍"


class TestGetFolderIcon:
    def test_code_folder(self):
        assert _get_folder_icon("src") == "💻"

    def test_patent_folder(self):
        assert _get_folder_icon("patents") == "📋"

    def test_trading_folder(self):
        assert _get_folder_icon("trading_data") == "📈"

    def test_security_folder(self):
        assert _get_folder_icon("security") == "🛡"

    def test_backup_folder(self):
        assert _get_folder_icon("backup") == "💾"

    def test_download_folder(self):
        assert _get_folder_icon("Downloads") == "📥"

    def test_desktop_folder(self):
        assert _get_folder_icon("Desktop") == "🖥"

    def test_generic_folder(self):
        assert _get_folder_icon("stuff") == "📁"

    def test_photo_folder(self):
        assert _get_folder_icon("Photos") == "🖼"

    def test_document_folder(self):
        assert _get_folder_icon("Documents") == "📝"


# ═══════════════════════════════════════════════════
# ENDPOINT TESTS
# ═══════════════════════════════════════════════════

class TestVaultBrowseEndpoint:
    def test_nonexistent_path(self, client):
        resp = client.get("/vault/browse?path=/nonexistent/path/12345")
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]
        assert data["folders"] == []
        assert data["files"] == []
        assert data["stats"]["total_files"] == 0

    @patch("api_server.Path")
    def test_not_a_directory(self, mock_path_cls, client):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.is_dir.return_value = False
        mock_path_cls.return_value = mock_path
        resp = client.get("/vault/browse?path=/some/file.txt")
        data = resp.json()
        assert data["error"] == "Path is not a directory"

    @patch("api_server.Path")
    def test_valid_directory_with_files(self, mock_path_cls, client):
        # Create mock directory contents
        file1 = _make_mock_path("report.pdf", is_dir=False, size=500000)
        file2 = _make_mock_path("data.csv", is_dir=False, size=2048)
        folder1 = _make_mock_path("src", is_dir=True, children=[
            _make_mock_path("a.py"), _make_mock_path("b.py"),
        ])

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        mock_dir.iterdir.return_value = iter([file1, file2, folder1])
        mock_path_cls.return_value = mock_dir

        resp = client.get("/vault/browse?path=/test/dir")
        data = resp.json()
        assert "error" not in data
        assert data["stats"]["total_folders"] == 1
        assert data["stats"]["total_files"] == 2

    @patch("api_server.Path")
    def test_hidden_files_excluded(self, mock_path_cls, client):
        hidden = _make_mock_path(".hidden_file", is_dir=False)
        system = _make_mock_path("$Recycle.Bin", is_dir=True, children=[])
        normal = _make_mock_path("readme.txt", is_dir=False, size=100)

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        mock_dir.iterdir.return_value = iter([hidden, system, normal])
        mock_path_cls.return_value = mock_dir

        resp = client.get("/vault/browse?path=/test/dir")
        data = resp.json()
        # Only normal file should be included
        assert data["stats"]["total_files"] == 1
        assert data["stats"]["total_folders"] == 0

    @patch("api_server.Path")
    def test_empty_directory(self, mock_path_cls, client):
        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        mock_dir.iterdir.return_value = iter([])
        mock_path_cls.return_value = mock_dir

        resp = client.get("/vault/browse?path=/empty/dir")
        data = resp.json()
        assert data["folders"] == []
        assert data["files"] == []
        assert data["stats"]["total_files"] == 0
        assert data["stats"]["total_folders"] == 0

    @patch("api_server.Path")
    def test_permission_denied(self, mock_path_cls, client):
        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        mock_dir.iterdir.side_effect = PermissionError("Access denied")
        mock_path_cls.return_value = mock_dir

        resp = client.get("/vault/browse?path=/protected/dir")
        data = resp.json()
        assert "Permission denied" in data["error"]

    @patch("api_server.Path")
    def test_folders_sorted_alphabetically(self, mock_path_cls, client):
        folders = [
            _make_mock_path("zebra", is_dir=True, children=[]),
            _make_mock_path("alpha", is_dir=True, children=[]),
            _make_mock_path("middle", is_dir=True, children=[]),
        ]

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        mock_dir.iterdir.return_value = iter(folders)
        mock_path_cls.return_value = mock_dir

        resp = client.get("/vault/browse?path=/test")
        data = resp.json()
        names = [f["name"] for f in data["folders"]]
        assert names == ["alpha", "middle", "zebra"]

    @patch("api_server.Path")
    def test_files_sorted_by_size_desc(self, mock_path_cls, client):
        files = [
            _make_mock_path("small.txt", is_dir=False, size=100),
            _make_mock_path("big.zip", is_dir=False, size=999999),
            _make_mock_path("medium.pdf", is_dir=False, size=50000),
        ]

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        mock_dir.iterdir.return_value = iter(files)
        mock_path_cls.return_value = mock_dir

        resp = client.get("/vault/browse?path=/test")
        data = resp.json()
        sizes = [f["size_bytes"] for f in data["files"]]
        assert sizes == sorted(sizes, reverse=True)

    @patch("api_server.Path")
    def test_folder_cap_at_12(self, mock_path_cls, client):
        folders = [
            _make_mock_path(f"folder_{i:02d}", is_dir=True, children=[])
            for i in range(20)
        ]

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        mock_dir.iterdir.return_value = iter(folders)
        mock_path_cls.return_value = mock_dir

        resp = client.get("/vault/browse?path=/test")
        data = resp.json()
        assert len(data["folders"]) <= 12
        assert data["stats"]["total_folders"] == 20
        assert data["stats"]["displayed_folders"] == 12

    @patch("api_server.Path")
    def test_file_cap_at_8(self, mock_path_cls, client):
        files = [
            _make_mock_path(f"file_{i:02d}.txt", is_dir=False, size=100 * (i + 1))
            for i in range(15)
        ]

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        mock_dir.iterdir.return_value = iter(files)
        mock_path_cls.return_value = mock_dir

        resp = client.get("/vault/browse?path=/test")
        data = resp.json()
        assert len(data["files"]) <= 8
        assert data["stats"]["total_files"] == 15
        assert data["stats"]["displayed_files"] == 8

    def test_default_path_fallback(self, client):
        """When no path param given, uses AETHER_VAULT_ROOT or default."""
        resp = client.get("/vault/browse")
        # Should not error — uses default vault root
        assert resp.status_code == 200

    @patch("api_server.Path")
    def test_file_metadata_fields(self, mock_path_cls, client):
        file1 = _make_mock_path("test.py", is_dir=False, size=4096)

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        mock_dir.iterdir.return_value = iter([file1])
        mock_path_cls.return_value = mock_dir

        resp = client.get("/vault/browse?path=/test")
        data = resp.json()
        assert len(data["files"]) == 1
        f = data["files"][0]
        assert "name" in f
        assert "size" in f
        assert "size_bytes" in f
        assert "extension" in f
        assert "category" in f
        assert "icon" in f
        assert "modified" in f

    @patch("api_server.Path")
    def test_folder_metadata_fields(self, mock_path_cls, client):
        folder1 = _make_mock_path("docs", is_dir=True, children=[
            _make_mock_path("a.txt"),
        ])

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        mock_dir.iterdir.return_value = iter([folder1])
        mock_path_cls.return_value = mock_dir

        resp = client.get("/vault/browse?path=/test")
        data = resp.json()
        assert len(data["folders"]) == 1
        f = data["folders"][0]
        assert "id" in f
        assert "name" in f
        assert "file_count" in f
        assert "icon" in f
        assert "modified" in f

    @patch("api_server.Path")
    def test_individual_file_permission_error_skipped(self, mock_path_cls, client):
        """If a single file throws PermissionError, it's skipped but others still appear."""
        good_file = _make_mock_path("good.txt", is_dir=False, size=100)
        bad_file = MagicMock(spec=Path)
        bad_file.name = "protected.txt"
        bad_file.stat.side_effect = PermissionError("no access")

        mock_dir = MagicMock()
        mock_dir.exists.return_value = True
        mock_dir.is_dir.return_value = True
        mock_dir.iterdir.return_value = iter([bad_file, good_file])
        mock_path_cls.return_value = mock_dir

        resp = client.get("/vault/browse?path=/test")
        data = resp.json()
        assert data["stats"]["total_files"] == 1
