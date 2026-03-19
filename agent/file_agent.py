"""
AetherCloud-L — AI File Agent
Understands file intent and manages the vault intelligently.
Uses local Ollama (Qwen) so no file contents leave the machine.
Aether Systems LLC — Patent Pending
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

from config.settings import DEFAULT_OLLAMA_MODEL, OLLAMA_BASE_URL


class AetherFileAgent:
    """
    AI agent that understands file intent and manages the vault intelligently.

    The agent can:
    - Analyze file names and contents to understand what they are
    - Suggest better names and locations
    - Auto-organize on request
    - Learn from user corrections
    - Answer questions about the vault

    Every agent action is logged via Protocol-L so the agent's decisions
    are auditable and cannot be disputed retroactively.

    Uses local Ollama (Qwen) for file analysis so no file contents
    leave the machine.
    """

    def __init__(
        self,
        vault: "AetherVault",
        model: str = DEFAULT_OLLAMA_MODEL,
        ollama_url: str = OLLAMA_BASE_URL,
    ):
        self._vault = vault
        self._model = model
        self._ollama_url = ollama_url
        self._organizer = None  # Lazy import to avoid circular

    @property
    def organizer(self):
        if self._organizer is None:
            from agent.organizer import FileOrganizer
            self._organizer = FileOrganizer()
        return self._organizer

    def _query_ollama(self, prompt: str) -> str:
        """Query local Ollama instance. Returns empty string on failure."""
        try:
            import requests
            response = requests.post(
                f"{self._ollama_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=30,
            )
            if response.status_code == 200:
                return response.json().get("response", "")
        except Exception:
            pass
        return ""

    def _rule_based_analysis(self, path: str) -> dict:
        """Rule-based file analysis fallback when Ollama is unavailable."""
        p = Path(path)
        name = p.stem
        ext = p.suffix.lower()
        parent = p.parent.name if p.parent != p else ""

        # Category detection by extension
        ext_categories = {
            ".py": "code", ".js": "code", ".ts": "code", ".java": "code",
            ".c": "code", ".cpp": "code", ".rs": "code", ".go": "code",
            ".html": "code", ".css": "code", ".jsx": "code", ".tsx": "code",
            ".pdf": "document", ".doc": "document", ".docx": "document",
            ".txt": "document", ".md": "document", ".rtf": "document",
            ".xlsx": "finance", ".xls": "finance", ".csv": "finance",
            ".png": "media", ".jpg": "media", ".jpeg": "media",
            ".gif": "media", ".mp4": "media", ".mp3": "media",
            ".zip": "archive", ".tar": "archive", ".gz": "archive",
            ".rar": "archive", ".7z": "archive",
            ".json": "config", ".yaml": "config", ".yml": "config",
            ".toml": "config", ".ini": "config", ".env": "config",
            ".log": "log", ".bak": "backup",
        }

        # Keyword-based category overrides
        name_lower = name.lower()
        if any(k in name_lower for k in ["patent", "filing", "intellectual_property"]):
            category = "patent"
        elif any(k in name_lower for k in ["trade", "stock", "futures"]):
            category = "trading"
        elif any(k in name_lower for k in ["legal", "contract", "nda"]):
            category = "legal"
        elif any(k in name_lower for k in ["backup", "bak"]):
            category = "backup"
        elif any(k in name_lower for k in ["security", "auth"]):
            category = "security"
        else:
            category = ext_categories.get(ext, "personal")

        # Suggested location
        suggested_location = category

        return {
            "current_name": p.name,
            "suggested_name": self.organizer.suggest_rename(path, category),
            "current_location": str(p.parent),
            "suggested_location": suggested_location,
            "category": category,
            "confidence": 0.7,
            "reasoning": f"Rule-based: extension={ext}, keywords detected in name",
        }

    def analyze_file(self, path: str) -> dict:
        """
        Analyze a file and return category, suggested name/location.
        Uses Ollama for AI analysis, falls back to rule-based.
        """
        p = Path(path)

        # Try AI analysis first
        prompt = (
            f"Analyze this filename and suggest a better name and category.\n"
            f"Filename: {p.name}\n"
            f"Extension: {p.suffix}\n"
            f"Directory: {p.parent}\n\n"
            f"Respond in JSON format with fields: "
            f"suggested_name, category, reasoning\n"
            f"Categories: patent, code, backup, legal, finance, trading, "
            f"security, personal, archive, config, log"
        )

        ai_response = self._query_ollama(prompt)
        if ai_response:
            try:
                data = json.loads(ai_response)
                return {
                    "current_name": p.name,
                    "suggested_name": data.get("suggested_name", p.name),
                    "current_location": str(p.parent),
                    "suggested_location": data.get("category", "personal"),
                    "category": data.get("category", "personal"),
                    "confidence": 0.85,
                    "reasoning": data.get("reasoning", "AI analysis"),
                }
            except (json.JSONDecodeError, KeyError):
                pass

        return self._rule_based_analysis(path)

    def organize_vault(self, dry_run: bool = True) -> list[dict]:
        """
        Scan the entire vault and suggest organization changes.
        dry_run=True: return suggestions only
        dry_run=False: execute moves/renames
        """
        files = self._vault.list_files(recursive=True)
        suggestions = []

        for file_info in files:
            if file_info.get("is_dir"):
                continue

            path = file_info["path"]
            analysis = self.analyze_file(
                str(self._vault.root / path)
            )

            current_name = file_info["name"]
            suggested_name = analysis.get("suggested_name", current_name)
            suggested_location = analysis.get("suggested_location", "")

            if suggested_name != current_name or suggested_location:
                suggestion = {
                    "path": path,
                    "current_name": current_name,
                    "suggested_name": suggested_name,
                    "suggested_location": suggested_location,
                    "category": analysis.get("category"),
                    "confidence": analysis.get("confidence", 0.0),
                    "action": "pending",
                }

                if not dry_run and analysis.get("confidence", 0) >= 0.7:
                    try:
                        if suggested_location and suggested_location != str(
                            Path(path).parent
                        ):
                            dest = f"{suggested_location}/{suggested_name}"
                            self._vault.move_file(
                                path, dest, reason="agent_suggested"
                            )
                            suggestion["action"] = "moved"
                        elif suggested_name != current_name:
                            self._vault.rename_file(
                                path, suggested_name, reason="agent_suggested"
                            )
                            suggestion["action"] = "renamed"
                    except Exception as e:
                        suggestion["action"] = f"error: {e}"

                suggestions.append(suggestion)

        return suggestions

    def chat(self, query: str) -> str:
        """
        Natural language interface to the vault.
        Examples:
          "Where is my patent filing?"
          "Show me all Python files"
          "What was accessed last week?"
          "Organize my downloads folder"
        """
        query_lower = query.lower()

        # Handle common queries with rule-based responses
        if any(k in query_lower for k in ["list", "show", "find", "where"]):
            files = self._vault.list_files(recursive=True)
            # Filter by keywords in query
            keywords = [
                w for w in query_lower.split()
                if w not in {"list", "show", "find", "where", "is", "my",
                             "all", "the", "me", "files"}
            ]
            if keywords:
                filtered = [
                    f for f in files
                    if any(k in f["name"].lower() or k in f["path"].lower()
                           for k in keywords)
                ]
            else:
                filtered = files

            if not filtered:
                return "No matching files found."

            lines = [f"Found {len(filtered)} file(s):"]
            for f in filtered[:20]:
                size_kb = f.get("size", 0) / 1024
                lines.append(f"  {f['path']} ({size_kb:.1f} KB)")
            if len(filtered) > 20:
                lines.append(f"  ... and {len(filtered) - 20} more")
            return "\n".join(lines)

        elif "organize" in query_lower:
            suggestions = self.organize_vault(dry_run=True)
            if not suggestions:
                return "Vault is already well-organized."
            lines = [f"Organization suggestions ({len(suggestions)}):"]
            for s in suggestions[:10]:
                lines.append(
                    f"  {s['current_name']} → {s['suggested_name']} "
                    f"[{s['category']}] ({s['confidence']:.0%})"
                )
            return "\n".join(lines)

        elif any(k in query_lower for k in ["audit", "access", "who"]):
            trail = self._vault.get_audit_trail(limit=10)
            if not trail:
                return "No audit entries found."
            lines = ["Recent audit entries:"]
            for entry in trail[:10]:
                data = entry.get("data", {}).get("trade_details", {})
                lines.append(
                    f"  [{data.get('event_type', '?')}] "
                    f"{data.get('path', data.get('username', '?'))} "
                    f"@ {data.get('timestamp', '?')}"
                )
            return "\n".join(lines)

        elif "stat" in query_lower or "status" in query_lower:
            stats = self._vault.get_stats()
            return (
                f"Vault: {stats['vault_root']}\n"
                f"Files: {stats['file_count']}\n"
                f"Size: {stats['total_size_mb']} MB"
            )

        # Fallback: try Ollama
        ai_response = self._query_ollama(
            f"The user asked about their file vault: {query}\n"
            f"Respond helpfully in 1-2 sentences."
        )
        if ai_response:
            return ai_response

        return (
            "I can help with: listing files, organizing, checking audit trails, "
            "and vault status. Try 'show all python files' or 'organize my vault'."
        )

    def suggest_name(self, path: str) -> str:
        """Suggest a better file name based on analysis."""
        analysis = self.analyze_file(path)
        return analysis.get("suggested_name", Path(path).name)
