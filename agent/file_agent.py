"""
AetherCloud-L — AI File Agent
Understands file intent and manages the vault intelligently.
Powered by Claude API sub-agent with rule-based fallback.
Aether Systems LLC — Patent Pending
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AetherFileAgent:
    """
    AI agent that understands file intent and manages the vault intelligently.

    The agent can:
    - Analyze file names and contents to understand what they are
    - Suggest better names and locations
    - Auto-organize on request
    - Learn from user corrections
    - Answer questions about the vault
    - Run security scans on audit trails

    Every agent action is logged via Protocol-L so the agent's decisions
    are auditable and cannot be disputed retroactively.

    Uses Claude API for AI analysis. Falls back to rule-based when
    API is unavailable. File contents NEVER leave the machine.
    """

    def __init__(self, vault: "AetherVault"):
        self._vault = vault
        self._organizer = None
        self._claude_agent = None
        self._claude_available = False
        self._init_claude_agent()

    def _init_claude_agent(self) -> None:
        """Initialize Claude agent with Protocol-L hardening when enabled."""
        try:
            from config.settings import HARDENED_AGENT_ENABLED, RFC3161_ENABLED

            if HARDENED_AGENT_ENABLED:
                from agent.hardened_claude_agent import HardenedClaudeAgent
                self._claude_agent = HardenedClaudeAgent(
                    enable_rfc3161=RFC3161_ENABLED,
                )
                self._claude_available = True
                self._hardened = True
                logger.info("Hardened Claude agent initialized (Protocol-L secured)")
            else:
                from agent.claude_agent import AetherClaudeAgent
                self._claude_agent = AetherClaudeAgent()
                self._claude_available = True
                self._hardened = False
                logger.info("Claude agent initialized (standard mode)")
        except Exception as e:
            logger.warning("Claude agent unavailable: %s — using rule-based fallback", e)
            self._claude_available = False
            self._hardened = False

    @property
    def organizer(self):
        if self._organizer is None:
            from agent.organizer import FileOrganizer
            self._organizer = FileOrganizer()
        return self._organizer

    @property
    def is_claude_available(self) -> bool:
        """Whether the Claude API agent is active."""
        return self._claude_available

    @property
    def is_hardened(self) -> bool:
        """Whether the agent is using Protocol-L hardened mode."""
        return getattr(self, "_hardened", False)

    def get_verification_report(self) -> dict:
        """Get the Protocol-L verification report from the hardened agent."""
        if self._hardened and self._claude_agent:
            return self._claude_agent.get_verification_report()
        return {"integrity": "NOT_HARDENED", "total_responses": 0}

    def analyze_file(self, path: str) -> dict:
        """
        Analyze a file and return category, suggested name/location.
        Uses Claude API agent, falls back to rule-based.
        """
        p = Path(path)

        if self._claude_available:
            try:
                result = self._claude_agent.analyze_file(
                    filename=p.stem,
                    extension=p.suffix,
                    directory=str(p.parent),
                )
                return {
                    "current_name": p.name,
                    "suggested_name": result.get("suggested_name", p.name),
                    "current_location": str(p.parent),
                    "suggested_location": result.get("suggested_directory", ""),
                    "category": result.get("category", "PERSONAL").lower(),
                    "confidence": result.get("confidence", 0.85),
                    "reasoning": result.get("reasoning", "Claude analysis"),
                    "security_flag": result.get("security_flag", False),
                    "security_note": result.get("security_note"),
                }
            except Exception as e:
                logger.warning("Claude analyze_file failed: %s", e)

        return self._rule_based_analysis(path)

    def organize_vault(self, dry_run: bool = True) -> list[dict]:
        """
        Scan the entire vault and suggest organization changes.
        dry_run=True: return suggestions only
        dry_run=False: execute moves/renames
        """
        files = self._vault.list_files(recursive=True)
        file_entries = [f for f in files if not f.get("is_dir")]

        # Try batch analysis with Claude
        if self._claude_available and file_entries:
            try:
                batch_input = [
                    {
                        "filename": Path(f["name"]).stem,
                        "extension": Path(f["name"]).suffix,
                        "directory": str(Path(f["path"]).parent),
                    }
                    for f in file_entries
                ]
                batch_results = self._claude_agent.batch_analyze(batch_input, dry_run)
                return self._process_batch_results(
                    file_entries, batch_results, dry_run
                )
            except Exception as e:
                logger.warning("Batch analyze failed: %s — falling back to individual", e)

        # Fallback: individual rule-based analysis
        suggestions = []
        for file_info in file_entries:
            path = file_info["path"]
            analysis = self._rule_based_analysis(str(self._vault.root / path))

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
                    self._execute_suggestion(suggestion, path, suggested_name, suggested_location)

                suggestions.append(suggestion)

        return suggestions

    def _process_batch_results(
        self,
        file_entries: list[dict],
        batch_results: list[dict],
        dry_run: bool,
    ) -> list[dict]:
        """Process batch analysis results into suggestion list."""
        suggestions = []
        for i, file_info in enumerate(file_entries):
            if i >= len(batch_results):
                break
            result = batch_results[i]
            current_name = file_info["name"]
            suggested_name = result.get("suggested_name", current_name)
            suggested_location = result.get("suggested_directory", "")

            if suggested_name != current_name or suggested_location:
                suggestion = {
                    "path": file_info["path"],
                    "current_name": current_name,
                    "suggested_name": suggested_name,
                    "suggested_location": suggested_location,
                    "category": result.get("category", "PERSONAL"),
                    "confidence": result.get("confidence", 0.0),
                    "action": "pending",
                }

                if not dry_run and result.get("confidence", 0) >= 0.7:
                    self._execute_suggestion(
                        suggestion, file_info["path"], suggested_name, suggested_location
                    )

                suggestions.append(suggestion)

        return suggestions

    def _execute_suggestion(
        self,
        suggestion: dict,
        path: str,
        suggested_name: str,
        suggested_location: str,
    ) -> None:
        """Execute a single organization suggestion."""
        try:
            if suggested_location and suggested_location != str(Path(path).parent):
                dest = f"{suggested_location}/{suggested_name}"
                self._vault.move_file(path, dest, reason="agent_suggested")
                suggestion["action"] = "moved"
            elif suggested_name != suggestion["current_name"]:
                self._vault.rename_file(path, suggested_name, reason="agent_suggested")
                suggestion["action"] = "renamed"
        except Exception as e:
            suggestion["action"] = f"error: {e}"

    def chat(self, query: str) -> str:
        """
        Natural language interface to the vault.
        Uses Claude for intelligent responses, with rule-based fallback.
        """
        query_lower = query.lower()

        # Build vault context for Claude
        if self._claude_available:
            try:
                vault_context = self._build_vault_context()
                return self._claude_agent.chat(query, vault_context)
            except Exception as e:
                logger.warning("Claude chat failed: %s — using rule-based", e)

        # Rule-based fallback
        return self._rule_based_chat(query_lower)

    def security_scan(self) -> dict:
        """
        Run a security scan on the vault's audit trail.
        Uses Claude to analyze patterns in audit events.

        Returns:
        {
          "threat_level": "NONE|LOW|MEDIUM|HIGH",
          "findings": list,
          "recommended_action": str
        }
        """
        trail = self._vault.get_audit_trail(limit=50)

        if self._claude_available:
            try:
                return self._claude_agent.analyze_security_pattern(trail)
            except Exception as e:
                logger.warning("Security scan via Claude failed: %s", e)

        # Rule-based fallback
        return self._rule_based_security_scan(trail)

    def suggest_name(self, path: str) -> str:
        """Suggest a better file name based on analysis."""
        analysis = self.analyze_file(path)
        return analysis.get("suggested_name", Path(path).name)

    # ─── Marketing skill routing ────────────────────────

    def route_request(self, intent: str, **kwargs) -> dict:
        """
        Route an agent request by intent to the correct skill method.

        Supported intents:
          FILE_ANALYZE, SECURITY_SCAN, CHAT,
          COMPETITIVE_CARD, CONTENT_DRAFT, EMAIL_SEQUENCE,
          CONTENT_REVIEW, POSITIONING

        Returns the skill output dict or a fallback error dict.
        """
        intent_upper = intent.upper().replace(" ", "_")

        if not self._claude_available:
            return {
                "error": "Agent unavailable — Claude API not configured",
                "intent": intent_upper,
            }

        routing = {
            "FILE_ANALYZE": lambda: self.analyze_file(kwargs.get("path", "")),
            "SECURITY_SCAN": lambda: self.security_scan(),
            "CHAT": lambda: {"response": self.chat(kwargs.get("query", ""))},
            "COMPETITIVE_CARD": lambda: self._claude_agent.create_competitive_card(
                product=kwargs.get("product", "AetherCloud-L"),
                competitors=kwargs.get("competitors", []),
                features=kwargs.get("features"),
            ),
            "CONTENT_DRAFT": lambda: self._claude_agent.draft_content(
                content_type=kwargs.get("content_type", "blog"),
                topic=kwargs.get("topic", ""),
                audience=kwargs.get("audience"),
                tone=kwargs.get("tone"),
            ),
            "EMAIL_SEQUENCE": lambda: self._claude_agent.draft_email_sequence(
                sequence_type=kwargs.get("sequence_type", "welcome"),
                product=kwargs.get("product", "AetherCloud-L"),
                num_emails=kwargs.get("num_emails", 5),
                audience=kwargs.get("audience"),
            ),
            "CONTENT_REVIEW": lambda: self._claude_agent.review_content(
                content=kwargs.get("content", ""),
                content_type=kwargs.get("content_type"),
                audience=kwargs.get("audience"),
            ),
            "POSITIONING": lambda: self._claude_agent.develop_positioning(
                product=kwargs.get("product", "AetherCloud-L"),
                market=kwargs.get("market", ""),
                competitors=kwargs.get("competitors"),
            ),
        }

        handler = routing.get(intent_upper)
        if handler is None:
            return {
                "error": f"Unknown intent: {intent_upper}",
                "supported": list(routing.keys()),
            }

        try:
            return handler()
        except Exception as e:
            logger.warning("route_request(%s) failed: %s", intent_upper, e)
            return {"error": str(e), "intent": intent_upper}

    def reset_conversation(self) -> None:
        """Reset the Claude agent's conversation history."""
        if self._claude_agent:
            self._claude_agent.reset_conversation()

    def _build_vault_context(self) -> dict:
        """Build vault context dict for Claude agent."""
        files = self._vault.list_files(recursive=True)
        stats = self._vault.get_stats()
        trail = self._vault.get_audit_trail(limit=10)

        return {
            "file_count": stats.get("file_count", 0),
            "file_sample": [f["name"] for f in files[:15]],
            "recent_events": [
                {
                    "type": e.get("data", {}).get("trade_details", {}).get("event_type", "?"),
                    "path": e.get("data", {}).get("trade_details", {}).get("path", "?"),
                }
                for e in trail[:5]
            ],
            "vault_stats": stats,
        }

    def _rule_based_analysis(self, path: str) -> dict:
        """Rule-based file analysis fallback."""
        p = Path(path)
        name = p.stem
        ext = p.suffix.lower()

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

        return {
            "current_name": p.name,
            "suggested_name": self.organizer.suggest_rename(path, category),
            "current_location": str(p.parent),
            "suggested_location": category,
            "category": category,
            "confidence": 0.7,
            "reasoning": f"Rule-based: extension={ext}, keywords detected in name",
        }

    def _rule_based_chat(self, query_lower: str) -> str:
        """Rule-based chat fallback when Claude is unavailable."""
        if any(k in query_lower for k in ["list", "show", "find", "where"]):
            files = self._vault.list_files(recursive=True)
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
                    f"  {s['current_name']} -> {s['suggested_name']} "
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

        elif "scan" in query_lower or "security" in query_lower or "threat" in query_lower:
            result = self.security_scan()
            return (
                f"Threat Level: {result['threat_level']}\n"
                f"Findings: {', '.join(result.get('findings', ['None']))}\n"
                f"Action: {result.get('recommended_action', 'None')}"
            )

        return (
            "I can help with: listing files, organizing, checking audit trails, "
            "security scans, and vault status. Try 'show all python files' or "
            "'organize my vault' or 'security scan'."
        )

    def _rule_based_security_scan(self, trail: list[dict]) -> dict:
        """Rule-based security scan fallback."""
        if not trail:
            return {
                "threat_level": "NONE",
                "findings": [],
                "recommended_action": "No events to analyze",
            }

        findings = []
        unauthorized_count = 0
        login_failures = 0

        for entry in trail:
            data = entry.get("data", {}).get("trade_details", {})
            event_type = data.get("event_type", "")
            if "UNAUTHORIZED" in event_type:
                unauthorized_count += 1
            if event_type == "AUTH_LOGIN" and not data.get("authenticated"):
                login_failures += 1

        if unauthorized_count > 0:
            findings.append(f"{unauthorized_count} unauthorized access events detected")
        if login_failures > 0:
            findings.append(f"{login_failures} failed login attempts")

        if unauthorized_count >= 10 or login_failures >= 5:
            threat = "HIGH"
            action = "Immediately review access logs and consider IP blocking"
        elif unauthorized_count >= 3 or login_failures >= 3:
            threat = "MEDIUM"
            action = "Review unauthorized access patterns"
        elif unauthorized_count > 0 or login_failures > 0:
            threat = "LOW"
            action = "Monitor for additional events"
        else:
            threat = "NONE"
            action = "No action required"

        return {
            "threat_level": threat,
            "findings": findings if findings else ["No suspicious activity detected"],
            "recommended_action": action,
        }
