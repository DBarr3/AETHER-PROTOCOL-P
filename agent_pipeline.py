"""
AetherCloud-L — Agent Pipeline Executor (Priority 6)
Chains MCP agents sequentially: output of step N feeds step N+1.
Built-in templates: Research→Image, Code Review→PR, Notion→Slack.

Aether Systems LLC — Patent Pending
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("aethercloud.pipeline")


# ── Data models ────────────────────────────────────────────────

@dataclass
class PipelineStep:
    """One step in a pipeline."""
    agent_id: str                   # matches a teamAgent.id
    prompt_template: str            # may contain {previous_output} and {initial_input}
    label: str = ""                 # human-readable step name


@dataclass
class Pipeline:
    name: str
    steps: list = field(default_factory=list)   # list of PipelineStep


@dataclass
class StepResult:
    step_index: int
    agent_id: str
    label: str
    prompt_sent: str
    output: str
    status: str         # "ok" | "error"
    error: str = ""
    duration_ms: int = 0


# ── Templates ──────────────────────────────────────────────────

PIPELINE_TEMPLATES = [
    {
        "id": "research_image",
        "name": "Research → Image",
        "description": "Research a topic with Firecrawl, then generate an image with fal.ai",
        "steps": [
            {
                "agent_id": "",     # filled by user from their team
                "label": "Research",
                "prompt_template": "Research this topic thoroughly and summarise key findings in 3-5 sentences: {initial_input}",
                "hint_server": "firecrawl",
            },
            {
                "agent_id": "",
                "label": "Generate Image",
                "prompt_template": "Based on this research summary, generate a compelling image that visualises the main concept:\n\n{previous_output}",
                "hint_server": "fal_ai",
            },
        ],
    },
    {
        "id": "code_review_pr",
        "name": "Code Review → PR",
        "description": "Review code with Context7 docs, then create a GitHub PR",
        "steps": [
            {
                "agent_id": "",
                "label": "Code Review",
                "prompt_template": "Review the following code for correctness, best practices, and documentation. Provide a structured review:\n\n{initial_input}",
                "hint_server": "context7",
            },
            {
                "agent_id": "",
                "label": "Create PR",
                "prompt_template": "Based on this code review, create a GitHub pull request with title, description, and suggested changes:\n\n{previous_output}",
                "hint_server": "github",
            },
        ],
    },
    {
        "id": "notion_slack",
        "name": "Notion → Slack",
        "description": "Summarise a Notion page and post it to Slack",
        "steps": [
            {
                "agent_id": "",
                "label": "Read Notion",
                "prompt_template": "Retrieve and summarise this Notion content in a clear, concise format suitable for a team update:\n\n{initial_input}",
                "hint_server": "notion",
            },
            {
                "agent_id": "",
                "label": "Post to Slack",
                "prompt_template": "Post this team update to the appropriate Slack channel:\n\n{previous_output}",
                "hint_server": "slack",
            },
        ],
    },
]


# ── Executor ───────────────────────────────────────────────────

class PipelineExecutor:
    """
    Executes a pipeline by running each step through the MCPRouter.
    Requires an anthropic AsyncAnthropic client and the MCPRouter singleton.
    """

    def __init__(self, mcp_router, anthropic_client=None):
        self.router = mcp_router
        self.client = anthropic_client  # set later by api_server

    async def run(
        self,
        user_id: str,
        steps: list,            # list of dicts: {agent_id, prompt_template, label}
        initial_input: str,
        api_key: str,
    ) -> list:
        """
        Execute each step sequentially.
        Returns list of StepResult objects (serialised as dicts).
        """
        results: list = []
        previous_output = ""

        for i, step in enumerate(steps):
            t0 = time.time()
            agent_id = step.get("agent_id", "")
            label = step.get("label") or f"Step {i + 1}"
            template = step.get("prompt_template", "{initial_input}")

            # Resolve prompt
            prompt = template.replace("{initial_input}", initial_input).replace(
                "{previous_output}", previous_output or initial_input
            )

            # Find the agent in the user's team
            agent = self.router.get_agent(user_id, agent_id)
            if not agent:
                result = StepResult(
                    step_index=i,
                    agent_id=agent_id,
                    label=label,
                    prompt_sent=prompt,
                    output="",
                    status="error",
                    error=f"Agent '{agent_id}' not found in team config",
                    duration_ms=0,
                )
                results.append(_step_to_dict(result))
                previous_output = ""
                continue

            # Execute via direct Anthropic call with MCP servers wired
            try:
                output = await self._call_agent(agent, prompt, api_key, user_id)
                duration_ms = int((time.time() - t0) * 1000)
                result = StepResult(
                    step_index=i,
                    agent_id=agent_id,
                    label=label,
                    prompt_sent=prompt[:400],
                    output=output,
                    status="ok",
                    duration_ms=duration_ms,
                )
                previous_output = output
            except Exception as e:
                duration_ms = int((time.time() - t0) * 1000)
                log.warning("Pipeline step %d failed for agent %s: %s", i, agent_id, e)
                result = StepResult(
                    step_index=i,
                    agent_id=agent_id,
                    label=label,
                    prompt_sent=prompt[:400],
                    output="",
                    status="error",
                    error=str(e)[:300],
                    duration_ms=duration_ms,
                )
                previous_output = ""

            results.append(_step_to_dict(result))

        return results

    async def _call_agent(self, agent: dict, prompt: str, api_key: str, user_id: str) -> str:
        """Make a direct Anthropic call with the agent's MCP server wired in."""
        import httpx, json as _json

        server = agent.get("server", "")
        url = agent.get("url", "")
        transport = agent.get("transport", "http")

        # Load the user's API key for this agent
        agent_key = await _load_agent_key_for_pipeline(user_id, agent.get("id", ""))

        # Build mcp_servers list
        mcp_servers = []
        if url and transport in ("http", "sse"):
            srv: dict = {"type": "url", "url": url, "name": server}
            if agent_key:
                srv["authorization_token"] = agent_key
            mcp_servers.append(srv)

        # System prompt
        system = agent.get("prompt") or (
            f"You are an expert {agent.get('name','AI')} assistant. "
            "Complete the task autonomously and respond concisely."
        )

        from lib import token_accountant
        resp = await token_accountant.call(
            model="sonnet",
            messages=[{"role": "user", "content": prompt}],
            user_id=None,
            system=system,
            mcp_servers=mcp_servers or None,
            max_tokens=1500,
        )
        return resp.text


async def _load_agent_key_for_pipeline(user_id: str, agent_id: str) -> Optional[str]:
    """Read the stored API key for an agent (same file used by /agent/key endpoint)."""
    from pathlib import Path
    import json as _json
    keys_file = (
        Path(__file__).parent / "data" / "users" / user_id / "agents" / "agent_keys.json"
    )
    if not keys_file.exists():
        return None
    try:
        keys = _json.loads(keys_file.read_text(encoding="utf-8"))
        return keys.get(agent_id)
    except Exception:
        return None


def _step_to_dict(s: StepResult) -> dict:
    return {
        "step_index":  s.step_index,
        "agent_id":    s.agent_id,
        "label":       s.label,
        "prompt_sent": s.prompt_sent,
        "output":      s.output,
        "status":      s.status,
        "error":       s.error,
        "duration_ms": s.duration_ms,
    }
