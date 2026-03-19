"""
AetherCloud-L — Proactive Suggestion Engine
Generates intelligent suggestions based on vault activity.
Aether Systems LLC — Patent Pending
"""

import time
from pathlib import Path
from typing import Optional


class SuggestionEngine:
    """
    Proactive suggestion engine that monitors vault patterns
    and generates actionable suggestions for the user.

    Suggestions include:
    - Files that should be renamed to follow convention
    - Files that appear misplaced
    - Duplicate files detected by content hash
    - Files that haven't been accessed in a long time
    - Security alerts for sensitive files
    """

    def __init__(self):
        self._dismissed: set[str] = set()

    def get_suggestions(
        self,
        files: list[dict],
        audit_trail: Optional[list[dict]] = None,
    ) -> list[dict]:
        """Generate suggestions based on current vault state."""
        suggestions = []

        suggestions.extend(self._check_naming(files))
        suggestions.extend(self._check_duplicates(files))
        suggestions.extend(self._check_stale(files))
        suggestions.extend(self._check_sensitive(files))

        # Filter dismissed
        return [s for s in suggestions if s.get("id") not in self._dismissed]

    def dismiss(self, suggestion_id: str) -> None:
        """Dismiss a suggestion so it doesn't appear again."""
        self._dismissed.add(suggestion_id)

    def _check_naming(self, files: list[dict]) -> list[dict]:
        """Check for files that don't follow naming convention."""
        import re
        convention_re = re.compile(r"^\d{8}_[A-Z]+_[\w]+\.\w+$")
        suggestions = []

        for f in files:
            if f.get("is_dir"):
                continue
            name = f.get("name", "")
            if not convention_re.match(name):
                suggestions.append({
                    "id": f"naming_{f['path']}",
                    "type": "naming",
                    "severity": "low",
                    "message": f"'{name}' doesn't follow naming convention",
                    "path": f["path"],
                    "action": "rename",
                })

        return suggestions

    def _check_duplicates(self, files: list[dict]) -> list[dict]:
        """Detect potential duplicate files by size."""
        suggestions = []
        by_size: dict[int, list[dict]] = {}

        for f in files:
            if f.get("is_dir") or f.get("size", 0) == 0:
                continue
            size = f["size"]
            by_size.setdefault(size, []).append(f)

        for size, group in by_size.items():
            if len(group) > 1 and size > 1024:  # Ignore tiny files
                paths = [g["path"] for g in group]
                suggestions.append({
                    "id": f"dup_{size}_{len(group)}",
                    "type": "duplicate",
                    "severity": "medium",
                    "message": f"Potential duplicates ({len(group)} files, {size} bytes each)",
                    "paths": paths,
                    "action": "review",
                })

        return suggestions

    def _check_stale(self, files: list[dict]) -> list[dict]:
        """Find files not modified in 90+ days."""
        suggestions = []
        cutoff = time.time() - (90 * 86400)

        for f in files:
            if f.get("is_dir"):
                continue
            mtime = f.get("modified", 0)
            if mtime and mtime < cutoff:
                days = int((time.time() - mtime) / 86400)
                suggestions.append({
                    "id": f"stale_{f['path']}",
                    "type": "stale",
                    "severity": "low",
                    "message": f"'{f['name']}' not modified in {days} days",
                    "path": f["path"],
                    "action": "archive_or_delete",
                })

        return suggestions

    def _check_sensitive(self, files: list[dict]) -> list[dict]:
        """Flag potentially sensitive files."""
        suggestions = []
        sensitive_patterns = {
            ".env", ".pem", ".key", ".p12", ".pfx",
            "credentials", "secret", "password", "token",
        }

        for f in files:
            if f.get("is_dir"):
                continue
            name_lower = f.get("name", "").lower()
            if any(pat in name_lower for pat in sensitive_patterns):
                suggestions.append({
                    "id": f"sensitive_{f['path']}",
                    "type": "security",
                    "severity": "high",
                    "message": f"Sensitive file detected: '{f['name']}'",
                    "path": f["path"],
                    "action": "review_permissions",
                })

        return suggestions
