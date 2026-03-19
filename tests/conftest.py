"""
AetherCloud-L — Test Configuration
Shared fixtures for all test modules.
"""

import os
import sys
import json
import time
import tempfile
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth.session import SessionManager
from auth.login import AetherCloudAuth
from vault.filebase import AetherVault
from vault.index import VaultIndex
from agent.organizer import FileOrganizer
from agent.intent import IntentAnalyzer
from agent.suggest import SuggestionEngine


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for tests."""
    return tmp_path


@pytest.fixture
def vault_root(tmp_path):
    """Provide a temporary vault root directory."""
    root = tmp_path / "vault"
    root.mkdir()
    return root


@pytest.fixture
def audit_dir(tmp_path):
    """Provide a temporary audit directory."""
    d = tmp_path / "audit"
    d.mkdir()
    return d


@pytest.fixture
def session_manager():
    """Provide a SessionManager with short timeout for testing."""
    return SessionManager(timeout_seconds=3600)


@pytest.fixture
def credentials_file(tmp_path):
    """Provide a temporary credentials file."""
    cred_file = tmp_path / "credentials.json"
    return cred_file


@pytest.fixture
def auth_instance(credentials_file, audit_dir):
    """Provide an AetherCloudAuth instance for testing."""
    from aether_protocol.audit import AuditLog
    audit_log = AuditLog(str(audit_dir / "test_audit.jsonl"))
    auth = AetherCloudAuth(
        config_path=str(credentials_file),
        audit_log=audit_log,
    )
    return auth


@pytest.fixture
def registered_auth(auth_instance):
    """Provide an auth instance with a registered user."""
    auth_instance.register_user("testuser", "SecureP@ss123")
    return auth_instance


@pytest.fixture
def vault_instance(vault_root, audit_dir):
    """Provide an AetherVault instance for testing."""
    from aether_protocol.audit import AuditLog
    audit_log = AuditLog(str(audit_dir / "vault_audit.jsonl"))
    return AetherVault(
        vault_root=str(vault_root),
        session_token="test_session_token_abc123",
        audit_log=audit_log,
    )


@pytest.fixture
def populated_vault(vault_instance, vault_root):
    """Provide a vault with some test files."""
    (vault_root / "document.pdf").write_bytes(b"fake pdf content")
    (vault_root / "script.py").write_text("print('hello')")
    (vault_root / "data.csv").write_text("col1,col2\n1,2\n3,4")
    subdir = vault_root / "subdir"
    subdir.mkdir()
    (subdir / "nested.txt").write_text("nested file content")
    (vault_root / "patent_filing.pdf").write_bytes(b"patent document")
    (vault_root / "backup_desktop.zip").write_bytes(b"PK" + b"\x00" * 20)
    (vault_root / "trade_log.csv").write_text("time,symbol,qty\n")
    (vault_root / "contract_nda.docx").write_bytes(b"docx content")
    (vault_root / "config.yaml").write_text("key: value\n")
    (vault_root / "debug.log").write_text("2026-03-19 ERROR something\n")
    return vault_instance


@pytest.fixture
def vault_index(tmp_path):
    """Provide a VaultIndex instance."""
    return VaultIndex(str(tmp_path / "test_index.db"))


@pytest.fixture
def organizer():
    """Provide a FileOrganizer instance."""
    return FileOrganizer()


@pytest.fixture
def intent_analyzer():
    """Provide an IntentAnalyzer instance."""
    return IntentAnalyzer()


@pytest.fixture
def suggestion_engine():
    """Provide a SuggestionEngine instance."""
    return SuggestionEngine()
