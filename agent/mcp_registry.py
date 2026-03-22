"""
AetherCloud-L — MCP Server Registry
Defines available MCP servers and auto-detects which ones a query needs.

Aether Systems LLC — Patent Pending
"""

from typing import Optional

MCP_SERVERS: dict[str, dict] = {
    "gmail": {
        "name": "gmail-mcp",
        "type": "url",
        "url": "https://gmail.mcp.claude.com/mcp",
        "description": "Read, draft, send Gmail emails",
        "triggers": [
            "email", "gmail", "inbox", "draft", "reply",
            "message", "unread", "send", "compose",
        ],
    },
    "google_calendar": {
        "name": "gcal-mcp",
        "type": "url",
        "url": "https://gcal.mcp.claude.com/mcp",
        "description": "Read and create Google Calendar events",
        "triggers": [
            "calendar", "meeting", "schedule", "event",
            "appointment", "tomorrow", "today", "week",
        ],
    },
}


def detect_required_servers(query: str) -> list[dict]:
    """Analyze query and return list of MCP server configs needed."""
    query_lower = query.lower()
    required: list[dict] = []
    seen: set[str] = set()

    for server_id, config in MCP_SERVERS.items():
        if any(trigger in query_lower for trigger in config["triggers"]):
            if server_id not in seen:
                required.append({
                    "type": config["type"],
                    "url": config["url"],
                    "name": config["name"],
                })
                seen.add(server_id)

    return required


def get_server_names(servers: list[dict]) -> list[str]:
    """Return human-readable names from server config list."""
    return [s.get("name", "unknown") for s in servers]


def get_all_server_configs() -> list[dict]:
    """Return all registered MCP server configs."""
    return [
        {"type": c["type"], "url": c["url"], "name": c["name"]}
        for c in MCP_SERVERS.values()
    ]
