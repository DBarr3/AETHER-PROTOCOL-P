"""
AetherCloud-L — Agent Activity Logger (Priority 5)
Per-agent call history with Protocol-C HMAC-SHA256 commit hashes.
Stored in DO Spaces (falls back to local JSON if spaces unavailable).

Aether Systems LLC — Patent Pending
"""

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("aethercloud.agent_activity")

# Injected by api_server at startup:  agent_activity.vault_spaces = svc.vault_spaces
vault_spaces: Optional[object] = None

_HMAC_KEY = os.environ.get("AETHER_PROTOCOL_C_KEY", "aether-protocol-c-default-key").encode()
_LOCAL_FALLBACK_DIR = Path(__file__).parent / "data" / "agent_activity"
_MAX_ENTRIES = 200   # keep rolling window per agent


# ── Protocol-C hash ────────────────────────────────────────────

def _protocol_c_hash(entry: dict) -> str:
    """HMAC-SHA256 over the canonical entry fields (excluding the hash itself)."""
    canonical = json.dumps({
        "timestamp":      entry.get("timestamp", ""),
        "agent_id":       entry.get("agent_id", ""),
        "server_name":    entry.get("server_name", ""),
        "tool_name":      entry.get("tool_name", ""),
        "query_summary":  entry.get("query_summary", ""),
        "result_summary": entry.get("result_summary", ""),
        "status":         entry.get("status", ""),
    }, sort_keys=True)
    return hmac.new(_HMAC_KEY, canonical.encode(), hashlib.sha256).hexdigest()


# ── Storage helpers ────────────────────────────────────────────

def _spaces_key(user_id: str, agent_id: str) -> str:
    return f"agent_activity/{agent_id}.json"


def _local_path(user_id: str, agent_id: str) -> Path:
    d = _LOCAL_FALLBACK_DIR / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{agent_id}.json"


async def _read_log(user_id: str, agent_id: str) -> list:
    """Read existing activity entries from Spaces or local fallback."""
    if vault_spaces and getattr(vault_spaces, "available", False):
        try:
            text = await _spaces_download(user_id, _spaces_key(user_id, agent_id))
            if text:
                data = json.loads(text)
                return data if isinstance(data, list) else []
        except Exception as e:
            log.debug("Spaces read failed for activity log: %s", e)

    # Local fallback
    p = _local_path(user_id, agent_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


async def _write_log(user_id: str, agent_id: str, entries: list) -> None:
    """Write activity log to Spaces or local fallback."""
    text = json.dumps(entries, indent=2)
    if vault_spaces and getattr(vault_spaces, "available", False):
        try:
            await _spaces_upload(user_id, _spaces_key(user_id, agent_id), text)
            return
        except Exception as e:
            log.debug("Spaces write failed for activity log: %s", e)

    # Local fallback
    p = _local_path(user_id, agent_id)
    p.write_text(text, encoding="utf-8")


async def _spaces_download(user_id: str, key: str) -> Optional[str]:
    """Thin async wrapper around VaultSpacesClient.download_text (which is sync)."""
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(
            None,
            lambda: vault_spaces.download_text(user_id, key),
        )
    except Exception:
        return None


async def _spaces_upload(user_id: str, key: str, text: str) -> None:
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: vault_spaces.upload(user_id, key, text.encode("utf-8"), "application/json"),
    )


# ── Public API ─────────────────────────────────────────────────

async def log_activity(
    user_id: str,
    agent_id: str,
    server_name: str,
    tool_name: str,
    query_summary: str,
    result_summary: str,
    status: str,          # "ok" | "error"
    error: str = "",
) -> None:
    """Append one activity entry. Fire-and-forget via asyncio.create_task()."""
    ts = datetime.now(timezone.utc).isoformat()
    entry: dict = {
        "timestamp":      ts,
        "agent_id":       agent_id,
        "server_name":    server_name,
        "tool_name":      tool_name,
        "query_summary":  query_summary[:200],
        "result_summary": result_summary[:300],
        "status":         status,
        "error":          error[:200] if error else "",
    }
    entry["hash"] = _protocol_c_hash(entry)

    try:
        entries = await _read_log(user_id, agent_id)
        entries.insert(0, entry)                    # newest first
        entries = entries[:_MAX_ENTRIES]            # rolling window
        await _write_log(user_id, agent_id, entries)
        log.debug("Activity logged for agent %s (user %s): %s", agent_id, user_id, status)
    except Exception as e:
        log.warning("Failed to log activity for agent %s: %s", agent_id, e)


async def get_activity(user_id: str, agent_id: str, limit: int = 50) -> list:
    """Return the most recent *limit* entries for a specific agent."""
    entries = await _read_log(user_id, agent_id)
    return entries[:limit]


async def get_all_activity(user_id: str, limit: int = 100) -> list:
    """Return the most recent *limit* entries across ALL of the user's agents."""
    all_entries: list = []

    # Collect from local files
    local_dir = _LOCAL_FALLBACK_DIR / user_id
    if local_dir.exists():
        for f in local_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    all_entries.extend(data)
            except Exception:
                pass

    # Sort newest first
    all_entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return all_entries[:limit]
