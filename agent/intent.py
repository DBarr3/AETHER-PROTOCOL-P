"""
AetherCloud-L — File Intent Analyzer
Understands file purpose from name, extension, and context.
Aether Systems LLC — Patent Pending
"""

from pathlib import Path
from typing import Optional


class IntentAnalyzer:
    """
    Analyzes file intent — what the file IS and what it's FOR.
    Used by the file agent to make intelligent decisions about
    organization, naming, and access patterns.
    """

    # Intent categories with descriptions
    INTENTS = {
        "work_in_progress": "Actively being edited or developed",
        "reference": "Read-only reference material",
        "archive": "Completed work, stored for records",
        "temporary": "Short-lived file, safe to auto-clean",
        "critical": "Important file requiring extra protection",
        "shared": "Intended for sharing with others",
        "backup": "Backup copy of another file",
        "configuration": "System or application configuration",
    }

    # Patterns that suggest specific intents
    _WIP_PATTERNS = {"draft", "wip", "todo", "temp", "scratch", "test"}
    _ARCHIVE_PATTERNS = {"final", "approved", "signed", "v1", "archive", "old"}
    _CRITICAL_PATTERNS = {"patent", "legal", "contract", "nda", "key", "secret"}
    _TEMP_PATTERNS = {"tmp", "temp", "cache", "~", ".swp", ".swo"}

    def analyze(self, path: str, metadata: Optional[dict] = None) -> dict:
        """
        Analyze file intent and return intent classification.

        Returns:
            {
                "intent": str,
                "confidence": float,
                "reasoning": str,
                "suggested_action": str
            }
        """
        p = Path(path)
        name_lower = p.name.lower()
        ext = p.suffix.lower()

        # Check patterns in order of specificity
        if any(pat in name_lower for pat in self._CRITICAL_PATTERNS):
            return {
                "intent": "critical",
                "confidence": 0.9,
                "reasoning": "Filename contains critical-category keywords",
                "suggested_action": "protect",
            }

        if any(pat in name_lower or pat == ext for pat in self._TEMP_PATTERNS):
            return {
                "intent": "temporary",
                "confidence": 0.85,
                "reasoning": "Filename suggests temporary/transient file",
                "suggested_action": "flag_for_cleanup",
            }

        if any(pat in name_lower for pat in self._WIP_PATTERNS):
            return {
                "intent": "work_in_progress",
                "confidence": 0.8,
                "reasoning": "Filename suggests active work in progress",
                "suggested_action": "keep_accessible",
            }

        if any(pat in name_lower for pat in self._ARCHIVE_PATTERNS):
            return {
                "intent": "archive",
                "confidence": 0.75,
                "reasoning": "Filename suggests completed/archived content",
                "suggested_action": "move_to_archive",
            }

        config_exts = {".json", ".yaml", ".yml", ".toml", ".ini", ".env", ".cfg"}
        if ext in config_exts or name_lower in config_exts:
            return {
                "intent": "configuration",
                "confidence": 0.8,
                "reasoning": "File extension indicates configuration file",
                "suggested_action": "protect",
            }

        if ext in {".bak", ".backup", ".old"}:
            return {
                "intent": "backup",
                "confidence": 0.9,
                "reasoning": "File extension indicates backup copy",
                "suggested_action": "verify_original_exists",
            }

        # Default
        return {
            "intent": "reference",
            "confidence": 0.5,
            "reasoning": "No strong intent signals detected",
            "suggested_action": "organize",
        }

    def batch_analyze(self, paths: list[str]) -> list[dict]:
        """Analyze multiple files and return intent classifications."""
        return [{"path": p, **self.analyze(p)} for p in paths]
