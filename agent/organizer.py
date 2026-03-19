"""
AetherCloud-L — File Organizer
Naming and location specialist with consistent conventions.
Aether Systems LLC — Patent Pending
"""

import re
import time
from pathlib import Path
from typing import Optional


class FileOrganizer:
    """
    Naming and location specialist.
    Enforces consistent naming conventions across the vault.

    Default naming convention:
      YYYYMMDD_CATEGORY_Description.ext

    Examples:
      20260319_PATENT_AetherQCQ_Filing2.pdf
      20260318_CODE_QiskitSelector_v2.py
      20260315_BACKUP_AetherSystems_Desktop.zip

    Categories (expandable):
      PATENT, CODE, BACKUP, LEGAL, FINANCE,
      TRADING, SECURITY, PERSONAL, ARCHIVE
    """

    NAMING_PATTERN = "{date}_{category}_{description}{ext}"

    CATEGORIES = frozenset({
        "patent", "code", "backup", "legal",
        "finance", "trading", "security",
        "personal", "archive", "config", "log",
    })

    # Standard convention pattern
    _CONVENTION_RE = re.compile(
        r"^\d{8}_[A-Z]+_[\w]+\.\w+$"
    )

    def __init__(self):
        self._corrections: dict[str, str] = {}

    def is_conventioned(self, filename: str) -> bool:
        """Check if a filename follows the naming convention."""
        return bool(self._CONVENTION_RE.match(filename))

    def suggest_rename(
        self,
        path: str,
        category: Optional[str] = None,
    ) -> str:
        """Return suggested name in standard format."""
        p = Path(path)
        ext = p.suffix
        stem = p.stem

        # If already follows convention, keep it
        if self.is_conventioned(p.name):
            return p.name

        # Detect category from extension if not provided
        if category is None:
            category = self._detect_category(p)

        # Clean up the description
        description = self._clean_description(stem)

        # Format date
        date_str = time.strftime("%Y%m%d")

        return self.NAMING_PATTERN.format(
            date=date_str,
            category=category.upper(),
            description=description,
            ext=ext,
        )

    def suggest_location(
        self,
        path: str,
        vault_structure: Optional[dict] = None,
    ) -> str:
        """Return suggested folder path based on category."""
        p = Path(path)
        category = self._detect_category(p)
        return category

    def batch_rename(
        self,
        paths: list[str],
        dry_run: bool = True,
    ) -> list[dict]:
        """Rename multiple files following convention."""
        results = []
        for path in paths:
            p = Path(path)
            suggested = self.suggest_rename(path)
            result = {
                "original": p.name,
                "suggested": suggested,
                "path": path,
                "needs_rename": p.name != suggested,
                "applied": False,
            }

            if not dry_run and result["needs_rename"]:
                try:
                    new_path = p.parent / suggested
                    p.rename(new_path)
                    result["applied"] = True
                except OSError as e:
                    result["error"] = str(e)

            results.append(result)
        return results

    def record_correction(self, original: str, corrected: str) -> None:
        """Record a user correction to improve future suggestions."""
        self._corrections[original] = corrected

    def _detect_category(self, path: Path) -> str:
        """Detect category from file extension and name."""
        ext = path.suffix.lower()
        name = path.stem.lower()

        ext_map = {
            ".py": "code", ".js": "code", ".ts": "code", ".java": "code",
            ".c": "code", ".cpp": "code", ".rs": "code", ".go": "code",
            ".html": "code", ".css": "code",
            ".pdf": "document", ".doc": "document", ".docx": "document",
            ".xlsx": "finance", ".xls": "finance", ".csv": "finance",
            ".zip": "archive", ".tar": "archive", ".gz": "archive",
            ".json": "config", ".yaml": "config", ".yml": "config",
            ".log": "log", ".bak": "backup",
        }

        # Keyword overrides
        if any(k in name for k in ["patent", "filing", "intellectual_property"]):
            return "patent"
        if any(k in name for k in ["trade", "stock", "futures"]):
            return "trading"
        if any(k in name for k in ["legal", "contract", "nda"]):
            return "legal"
        if any(k in name for k in ["backup", "bak"]):
            return "backup"
        if any(k in name for k in ["security", "auth"]):
            return "security"

        return ext_map.get(ext, "personal")

    def _clean_description(self, stem: str) -> str:
        """Clean a filename stem into a description for the convention."""
        # Remove leading date patterns if present
        cleaned = re.sub(r"^\d{4}[-_]?\d{2}[-_]?\d{2}[-_]?", "", stem)
        # Remove category-like prefixes
        for cat in self.CATEGORIES:
            cleaned = re.sub(rf"^{cat}[-_]?", "", cleaned, flags=re.IGNORECASE)
        # Replace non-alphanumeric with underscore
        cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", cleaned)
        # Remove leading/trailing underscores
        cleaned = cleaned.strip("_")
        # CamelCase it
        parts = [p.capitalize() for p in cleaned.split("_") if p]
        result = "_".join(parts) if parts else "Unnamed"
        return result
