"""
AetherCloud-L — Claude API Sub-Agent
Purpose-built file intelligence agent powered by Claude.
Only file names, extensions, and paths are sent to the API.
File contents NEVER leave the machine.
Aether Systems LLC — Patent Pending
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

from anthropic import Anthropic

from config.settings import (
    CLAUDE_API_KEY,
    CLAUDE_MODEL,
    CLAUDE_MAX_TOKENS,
    AGENT_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


class AetherClaudeAgent:
    """
    Claude API sub-agent for AetherCloud-L.

    This is a purpose-built file intelligence agent powered by Claude.
    It analyzes file names and directory context, suggests organization,
    and answers natural language vault queries.

    Security model:
    - Only file names, extensions, and paths are ever sent to the API
    - File contents NEVER leave the machine
    - Every agent call is logged via Protocol-L
    - Conversation history maintained per session
    - Agent identity is fixed by system prompt

    Aether Systems LLC — Patent Pending
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ):
        self._api_key = api_key or CLAUDE_API_KEY
        if not self._api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. Add to your .env file."
            )

        self.client = Anthropic(api_key=self._api_key)
        self.model = model or CLAUDE_MODEL
        self.max_tokens = max_tokens or CLAUDE_MAX_TOKENS
        self.conversation_history: list[dict] = []
        self.system_prompt = AGENT_SYSTEM_PROMPT
        logger.info("Claude agent initialized (model=%s)", self.model)

    def analyze_file(
        self,
        filename: str,
        extension: str,
        directory: str,
        vault_context: Optional[dict] = None,
    ) -> dict:
        """
        Analyze a single file and return organization recommendations.

        Sends ONLY: filename, extension, directory.
        Never sends file contents.

        Returns:
        {
          "suggested_name": str,
          "category": str,
          "suggested_directory": str,
          "confidence": float,
          "reasoning": str,
          "security_flag": bool,
          "security_note": str | None
        }
        """
        prompt = (
            f"Analyze this file and respond with a JSON object only. No other text.\n\n"
            f"filename: {filename}\n"
            f"extension: {extension}\n"
            f"current_directory: {directory}\n\n"
            f"Respond with exactly:\n"
            f'{{\n'
            f'  "suggested_name": "YYYYMMDD_CATEGORY_Description{extension}",\n'
            f'  "category": "PATENT|CODE|BACKUP|LEGAL|FINANCE|TRADING|SECURITY|PERSONAL|ARCHIVE|CONFIG|LOG",\n'
            f'  "suggested_directory": "relative/path",\n'
            f'  "confidence": 0.0-1.0,\n'
            f'  "reasoning": "one sentence",\n'
            f'  "security_flag": true|false,\n'
            f'  "security_note": "note if flagged, null otherwise"\n'
            f'}}'
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = self._strip_markdown_fences(raw)
            return json.loads(raw)

        except Exception as e:
            logger.warning("Claude agent error: %s — using rule-based fallback", e)
            return self._rule_based_fallback(filename, extension, directory)

    def batch_analyze(
        self,
        files: list[dict],
        dry_run: bool = True,
    ) -> list[dict]:
        """
        Analyze multiple files in one API call.
        files: list of {filename, extension, directory}
        Returns list of analysis results.
        """
        if not files:
            return []

        file_list = "\n".join(
            f"{i + 1}. {f['filename']}{f['extension']} in {f['directory']}"
            for i, f in enumerate(files)
        )

        prompt = (
            f"Analyze these {len(files)} files.\n"
            f"Respond with a JSON array only. No other text.\n\n"
            f"Files:\n{file_list}\n\n"
            f"For each file respond with:\n"
            f'{{\n'
            f'  "index": 1,\n'
            f'  "suggested_name": "YYYYMMDD_CATEGORY_Description.ext",\n'
            f'  "category": "CATEGORY",\n'
            f'  "suggested_directory": "path",\n'
            f'  "confidence": 0.0-1.0,\n'
            f'  "reasoning": "one sentence",\n'
            f'  "security_flag": false,\n'
            f'  "security_note": null\n'
            f'}}\n\n'
            f"Return a JSON array of {len(files)} objects."
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = self._strip_markdown_fences(raw)
            results = json.loads(raw)

            for i, result in enumerate(results):
                if i < len(files):
                    result["original"] = files[i]

            return results

        except Exception as e:
            logger.warning("Batch analysis failed: %s — falling back to individual", e)
            return [
                self.analyze_file(f["filename"], f["extension"], f["directory"])
                for f in files
            ]

    def chat(self, query: str, vault_context: Optional[dict] = None) -> str:
        """
        Natural language conversation about the vault.
        Maintains conversation history within the session so
        follow-up questions work correctly.

        vault_context:
          file_count: int
          file_sample: list of filenames
          recent_events: list of audit events
          vault_stats: dict

        File contents never included in context.
        """
        vault_context = vault_context or {}

        # Build context string from vault metadata
        context = (
            f"Current vault state:\n"
            f"  Files: {vault_context.get('file_count', 0)}\n"
            f"  Recent audit events: {json.dumps(vault_context.get('recent_events', [])[-5:], indent=2, default=str)}\n"
            f"  Sample files: {', '.join(vault_context.get('file_sample', [])[:10])}\n"
            f"  Vault stats: {json.dumps(vault_context.get('vault_stats', {}), indent=2, default=str)}"
        )

        if not self.conversation_history:
            full_query = f"{context}\n\nUser: {query}"
        else:
            full_query = query

        self.conversation_history.append({"role": "user", "content": full_query})

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=self.conversation_history,
            )

            reply = response.content[0].text.strip()
            self.conversation_history.append({"role": "assistant", "content": reply})

            # Keep history bounded (last 20 turns)
            if len(self.conversation_history) > 40:
                self.conversation_history = self.conversation_history[-40:]

            return reply

        except Exception as e:
            logger.error("Chat failed: %s", e)
            return f"Agent unavailable: {str(e)}\nCheck ANTHROPIC_API_KEY in .env"

    def analyze_security_pattern(self, audit_events: list[dict]) -> dict:
        """
        Analyze recent audit events for suspicious patterns.

        This is AetherCloud-L's threat intelligence layer —
        Claude analyzes the audit trail and flags anything suspicious:
          - Brute force login attempts
          - Systematic file enumeration
          - Access to sensitive files at unusual times
          - Repeated unauthorized access attempts

        Returns:
        {
          "threat_level": "NONE|LOW|MEDIUM|HIGH",
          "findings": list of strings,
          "recommended_action": str
        }
        """
        if not audit_events:
            return {
                "threat_level": "NONE",
                "findings": [],
                "recommended_action": "No events to analyze",
            }

        events_str = json.dumps(audit_events[-50:], indent=2, default=str)

        prompt = (
            f"Analyze these vault audit events for security threats.\n"
            f"Respond with JSON only.\n\n"
            f"Recent audit events:\n{events_str}\n\n"
            f"Respond with exactly:\n"
            f'{{\n'
            f'  "threat_level": "NONE|LOW|MEDIUM|HIGH",\n'
            f'  "findings": ["finding 1", "finding 2"],\n'
            f'  "recommended_action": "one clear action"\n'
            f'}}'
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                system=self.system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = self._strip_markdown_fences(raw)
            return json.loads(raw)

        except Exception as e:
            logger.error("Security analysis failed: %s", e)
            return {
                "threat_level": "UNKNOWN",
                "findings": [f"Analysis failed: {e}"],
                "recommended_action": "Manual review required",
            }

    def reset_conversation(self) -> None:
        """Clear conversation history. Called on session end or explicit reset."""
        self.conversation_history = []
        logger.info("Agent conversation reset")

    def _strip_markdown_fences(self, text: str) -> str:
        """Strip markdown code fences from API response."""
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json) and last line (```)
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines)
        return text

    def _rule_based_fallback(
        self,
        filename: str,
        extension: str,
        directory: str,
    ) -> dict:
        """
        Rule-based fallback when Claude API is unavailable.
        Uses extension and keyword matching.
        Always returns valid structure — never crashes.
        """
        date = datetime.now().strftime("%Y%m%d")

        ext_map = {
            ".py": "CODE", ".js": "CODE", ".ts": "CODE", ".sh": "CODE",
            ".java": "CODE", ".c": "CODE", ".cpp": "CODE", ".rs": "CODE",
            ".go": "CODE", ".html": "CODE", ".css": "CODE",
            ".pdf": "LEGAL", ".docx": "LEGAL", ".doc": "LEGAL",
            ".xlsx": "FINANCE", ".xls": "FINANCE", ".csv": "FINANCE",
            ".zip": "BACKUP", ".tar": "BACKUP", ".gz": "BACKUP",
            ".rar": "BACKUP", ".7z": "BACKUP",
            ".log": "LOG", ".json": "CONFIG", ".env": "CONFIG",
            ".yml": "CONFIG", ".yaml": "CONFIG", ".toml": "CONFIG",
            ".ini": "CONFIG",
        }
        category = ext_map.get(extension.lower(), "PERSONAL")

        name_lower = filename.lower()
        if any(k in name_lower for k in ["patent", "filing", "uspto"]):
            category = "PATENT"
        elif any(k in name_lower for k in ["trade", "position", "pnl", "futures"]):
            category = "TRADING"
        elif any(k in name_lower for k in ["password", "key", "secret", "credential"]):
            category = "SECURITY"
        elif any(k in name_lower for k in ["contract", "nda", "legal"]):
            category = "LEGAL"
        elif any(k in name_lower for k in ["backup", "bak"]):
            category = "BACKUP"

        clean = filename.replace(" ", "_")

        return {
            "suggested_name": f"{date}_{category}_{clean}{extension}",
            "category": category,
            "suggested_directory": category.lower(),
            "confidence": 0.6,
            "reasoning": "Rule-based (API unavailable)",
            "security_flag": False,
            "security_note": None,
        }
