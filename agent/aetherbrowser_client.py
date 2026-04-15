"""
AetherCloud-L — AetherBrowser Client
Async HTTP client for all AetherCloud → AetherBrowser communication.
All browser automation requests MUST go through this module.

Aether Systems LLC — Patent Pending
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("aethercloud.aetherbrowser_client")

AETHERBROWSER_URL = os.getenv("AETHERBROWSER_URL", "http://10.116.0.6:8092")
AETHERBROWSER_BEARER_TOKEN = os.getenv("AETHERBROWSER_BEARER_TOKEN", "")


class BrowserCapacityError(Exception):
    """Raised when AetherBrowser has no available session slots."""

    def __init__(self, retry_after: int = 60, estimated_available: str = "unknown"):
        self.retry_after = retry_after
        self.estimated_available = estimated_available
        super().__init__(f"Browser capacity exceeded — retry in {retry_after}s")


class BrowserSessionError(Exception):
    """Raised on unrecoverable browser session errors."""


def _headers() -> dict:
    return {"Authorization": f"Bearer {AETHERBROWSER_BEARER_TOKEN}"}


async def create_session(max_vision_steps: int = 20) -> str:
    """Create a new browser session. Returns session_id."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{AETHERBROWSER_URL}/browser/session/create",
            headers=_headers(),
            params={"max_vision_steps": max_vision_steps},
        )
        if resp.status_code == 503:
            data = resp.json().get("detail", {})
            raise BrowserCapacityError(
                retry_after=data.get("retry_after_seconds", 60),
                estimated_available=data.get("estimated_available", "unknown"),
            )
        resp.raise_for_status()
        return resp.json()["session_id"]


async def navigate(
    session_id: str,
    url: str,
    credential_token: Optional[str] = None,
) -> dict:
    """Navigate to a URL. Returns {current_url, a11y_tree}."""
    body: dict = {"session_id": session_id, "url": url}
    if credential_token:
        body["credential_token"] = credential_token
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{AETHERBROWSER_URL}/browser/navigate",
            headers=_headers(),
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


async def snapshot(session_id: str) -> dict:
    """Take a screenshot + a11y snapshot. Returns {image_base64, a11y_tree, steps_remaining}."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{AETHERBROWSER_URL}/browser/snapshot",
            headers=_headers(),
            json={"session_id": session_id},
        )
        resp.raise_for_status()
        return resp.json()


async def interact(session_id: str, action: str, target: dict, **kwargs) -> dict:
    """Interact with a page element. Returns {success, a11y_tree}."""
    body: dict = {
        "session_id": session_id,
        "action": action,
        "target": target,
    }
    body.update(kwargs)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{AETHERBROWSER_URL}/browser/interact",
            headers=_headers(),
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


async def end_session(session_id: str) -> None:
    """End a browser session. Always call in a finally block."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{AETHERBROWSER_URL}/browser/session/end",
                headers=_headers(),
                json={"session_id": session_id},
            )
            # Don't raise — session end is best-effort cleanup
            if resp.status_code != 200:
                logger.warning(
                    "Session end returned %d for %s", resp.status_code, session_id
                )
    except Exception as exc:
        logger.warning("Failed to end browser session %s: %s", session_id, exc)


async def health() -> dict:
    """Check AetherBrowser health. Returns {status, slots_available, warm_pool_ready}."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{AETHERBROWSER_URL}/browser/health")
        resp.raise_for_status()
        return resp.json()
