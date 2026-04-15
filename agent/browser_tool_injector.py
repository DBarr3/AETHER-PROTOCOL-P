"""
AetherCloud-L — Browser Tool Injector
Dynamically appends browser automation tools and operating manual
to Claude's context when an agent has requires_browser_sandbox=True.

Called by the task runner before building the Claude API payload.
Does NOT call AetherBrowser directly — just shapes the tool list
and system prompt for Claude.

Aether Systems LLC — Patent Pending
"""

import logging

logger = logging.getLogger("aethercloud.browser_tool_injector")

BROWSER_TOOLS = [
    {
        "name": "browser_navigate",
        "description": (
            "Navigate to a URL. Returns the page's accessibility tree. "
            "Does not consume a vision step."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to navigate to.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_interact",
        "description": (
            "Interact with a page element. Prefer selector over coordinates. "
            "Use coordinates only for canvas elements or items absent from "
            "the accessibility tree."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["click", "type", "scroll"],
                    "description": "The interaction action to perform.",
                },
                "target": {
                    "type": "object",
                    "description": (
                        "Target element. Use {selector} for elements in the "
                        "accessibility tree, or {x, y} coordinates for canvas "
                        "elements or unlabelled icons."
                    ),
                },
                "text": {
                    "type": "string",
                    "description": "Text to type. Required for 'type' action.",
                },
            },
            "required": ["action", "target"],
        },
    },
    {
        "name": "browser_snapshot",
        "description": (
            "Take a screenshot and get the current page state. "
            "Consumes one vision step from a limited budget. Use sparingly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "browser_end",
        "description": (
            "End the browser session and release resources. "
            "Always call this when browser tasks are complete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

BROWSER_OPERATING_MANUAL = """
--- BROWSER OPERATING MANUAL ---
Viewport: 1280x800. All coordinates must be within x:0-1280, y:0-800.

TOOL PRIORITY — follow this order without exception:
1. Always attempt tasks using direct API tools first (Gmail, GitHub, Calendar, etc.)
2. Only use browser tools if an API tool fails, returns insufficient data, or no API tool exists for the domain.
3. If an API fails mid-task, pivot autonomously to browser tools without returning to the user.

INTERACTION RULES:
- Prefer browser_interact with a selector target whenever the accessibility tree identifies the element clearly.
- Use coordinate targets only for canvas elements, unlabelled icons, or elements absent from the accessibility tree.
- Call browser_snapshot only when visual information is genuinely needed. Every snapshot consumes a vision step from a limited budget.
- Always call browser_end when browser tasks are complete, even if an error occurred.
--- END BROWSER OPERATING MANUAL ---
"""


def inject_browser_tools(
    agent_profile,
    mcp_tools: list,
    system_prompt: str,
) -> tuple[list, str]:
    """
    Conditionally inject browser tools into Claude's context.

    If agent_profile.requires_browser_sandbox is False (or absent),
    returns mcp_tools and system_prompt unchanged.

    If True, appends four browser tool definitions to mcp_tools
    and appends the Browser Operating Manual to system_prompt.

    Args:
        agent_profile: An object with a `requires_browser_sandbox` attribute
                       (ResolvedAgent, task dict, or similar).
        mcp_tools: The current list of tool definitions for the Claude call.
        system_prompt: The current system prompt string.

    Returns:
        (updated_tools, updated_prompt) tuple.
    """
    # Support both object attribute and dict key access
    if hasattr(agent_profile, "requires_browser_sandbox"):
        needs_browser = agent_profile.requires_browser_sandbox
    elif isinstance(agent_profile, dict):
        needs_browser = agent_profile.get("requires_browser_sandbox", False)
    else:
        needs_browser = False

    if not needs_browser:
        return mcp_tools, system_prompt

    updated_tools = list(mcp_tools) + BROWSER_TOOLS
    updated_prompt = system_prompt + "\n\n" + BROWSER_OPERATING_MANUAL

    logger.info("Injected %d browser tools into agent context", len(BROWSER_TOOLS))
    return updated_tools, updated_prompt
