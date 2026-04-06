"""
AetherCloud-L — MCP Server Registry
Defines available MCP servers and auto-detects which ones a query needs.

Auth tokens are loaded from environment variables at call time so the
registry can be imported without a live environment.

Aether Systems LLC — Patent Pending
"""

import os
from typing import Optional

# ── Server Definitions ────────────────────────────────────────────────────────
# Each entry has:
#   name        — identifier passed to Anthropic API
#   type        — always "url" for remote MCP
#   url         — MCP server endpoint (env-overridable for self-hosted)
#   auth_env    — env var name holding the OAuth/API token (None = no auth needed)
#   description — human-readable capability summary
#   triggers    — keywords that auto-activate this server

MCP_SERVER_DEFS: dict[str, dict] = {
    # ── Google Suite (Anthropic-hosted, shared OAuth) ─────────────────────────
    "gmail": {
        "name": "gmail-mcp",
        "type": "url",
        "url": "https://gmail.mcp.claude.com/mcp",
        "auth_env": None,  # OAuth handled by Anthropic
        "description": "Read, draft, and send Gmail emails",
        "triggers": [
            "email", "gmail", "inbox", "draft", "reply",
            "message", "unread", "send", "compose", "mail",
        ],
    },
    "google_calendar": {
        "name": "gcal-mcp",
        "type": "url",
        "url": "https://gcal.mcp.claude.com/mcp",
        "auth_env": None,
        "description": "Read and create Google Calendar events",
        "triggers": [
            "calendar", "meeting", "schedule", "event",
            "appointment", "tomorrow", "today", "week", "remind",
        ],
    },
    "google_drive": {
        "name": "gdrive-mcp",
        "type": "url",
        "url": "https://drive.mcp.claude.com/mcp",
        "auth_env": None,
        "description": "Read, search, and manage Google Drive files",
        "triggers": [
            "drive", "google drive", "gdrive", "folder", "document",
            "spreadsheet", "slides", "shared drive", "file",
        ],
    },

    # ── GitHub ────────────────────────────────────────────────────────────────
    "github": {
        "name": "github-mcp",
        "type": "url",
        "url": os.getenv("GITHUB_MCP_URL", "https://api.githubcopilot.com/mcp/"),
        "auth_env": "GITHUB_MCP_TOKEN",  # Personal access token or fine-grained PAT
        "description": "Read repos, issues, PRs; create issues and comments",
        "triggers": [
            "github", "repo", "repository", "pull request", "pr",
            "issue", "commit", "branch", "code review", "merge",
            "bug", "release", "workflow", "action",
        ],
    },

    # ── Slack ─────────────────────────────────────────────────────────────────
    "slack": {
        "name": "slack-mcp",
        "type": "url",
        "url": os.getenv("SLACK_MCP_URL", "https://mcp.slack.com/sse"),
        "auth_env": "SLACK_MCP_TOKEN",  # Slack Bot OAuth token (xoxb-...)
        "description": "Send messages, read channels, search Slack workspace",
        "triggers": [
            "slack", "channel", "workspace", "dm", "direct message",
            "notify", "alert", "post to", "send to", "#",
        ],
    },

    # ── Brave Search ──────────────────────────────────────────────────────────
    "brave_search": {
        "name": "brave-search-mcp",
        "type": "url",
        "url": os.getenv("BRAVE_MCP_URL", "https://api.search.brave.com/mcp"),
        "auth_env": "BRAVE_SEARCH_API_KEY",  # Brave Search API key
        "description": "Live web search with privacy-respecting results",
        "triggers": [
            "search", "look up", "find online", "web search", "browse",
            "current", "latest", "news", "what is", "who is",
            "price", "weather", "today", "recent",
        ],
    },

    # ── Linear ────────────────────────────────────────────────────────────────
    "linear": {
        "name": "linear-mcp",
        "type": "url",
        "url": os.getenv("LINEAR_MCP_URL", "https://mcp.linear.app/sse"),
        "auth_env": "LINEAR_API_KEY",  # Linear personal API key
        "description": "Create and update Linear issues and projects",
        "triggers": [
            "linear", "task", "ticket", "backlog", "sprint",
            "project", "milestone", "bug report", "feature request",
            "roadmap", "team", "cycle",
        ],
    },

    # ── Notion ────────────────────────────────────────────────────────────────
    "notion": {
        "name": "notion-mcp",
        "type": "url",
        "url": os.getenv("NOTION_MCP_URL", "https://api.notion.com/v1/mcp"),
        "auth_env": "NOTION_API_KEY",  # Notion integration token (secret_...)
        "description": "Read and write Notion pages and databases",
        "triggers": [
            "notion", "page", "database", "wiki", "doc", "note",
            "knowledge base", "workspace", "block", "table",
        ],
    },
}


def _build_server_config(server_id: str) -> dict:
    """Build the Anthropic API server config for a given server_id."""
    defn = MCP_SERVER_DEFS[server_id]
    config = {
        "type": defn["type"],
        "url": defn["url"],
        "name": defn["name"],
    }
    if defn.get("auth_env"):
        token = os.getenv(defn["auth_env"], "")
        if token:
            config["authorization_token"] = token
    return config


def detect_required_servers(query: str) -> list[dict]:
    """Analyze query and return list of MCP server configs needed."""
    query_lower = query.lower()
    required: list[dict] = []
    seen: set[str] = set()

    for server_id, defn in MCP_SERVER_DEFS.items():
        if any(trigger in query_lower for trigger in defn["triggers"]):
            if server_id not in seen:
                required.append(_build_server_config(server_id))
                seen.add(server_id)

    return required


def get_server_by_id(server_id: str) -> Optional[dict]:
    """Return the Anthropic API config for a specific server."""
    if server_id not in MCP_SERVER_DEFS:
        return None
    return _build_server_config(server_id)


def get_server_names(servers: list[dict]) -> list[str]:
    """Return human-readable names from server config list."""
    return [s.get("name", "unknown") for s in servers]


def get_all_server_configs() -> list[dict]:
    """Return all registered MCP server configs (tokens injected from env)."""
    return [_build_server_config(sid) for sid in MCP_SERVER_DEFS]


def list_servers() -> list[dict]:
    """Return server metadata (no tokens) for display/logging."""
    return [
        {
            "id": sid,
            "name": defn["name"],
            "description": defn["description"],
            "requires_token": bool(defn.get("auth_env")),
            "token_configured": bool(defn.get("auth_env") and os.getenv(defn["auth_env"], "")),
        }
        for sid, defn in MCP_SERVER_DEFS.items()
    ]
