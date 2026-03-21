"""
AetherCloud-L -- Adaptive Agent Task Scheduler
Runs scheduled tasks using APScheduler. Fires task execution on cron triggers.

Aether Systems LLC -- Patent Pending
"""

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False

logger = logging.getLogger("aethercloud.scheduler")

CONFIG_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent / "config"
TASKS_FILE = CONFIG_DIR / "scheduled_tasks.json"


# ================================================================
# NATURAL LANGUAGE SCHEDULE PARSER
# ================================================================

def parse_schedule(natural_language: str) -> tuple[str, str]:
    """
    Extract cron expression + human label from common scheduling phrases.

    Returns (cron_expr, label) tuple.
    """
    text = natural_language.lower().strip()

    # "every hour"
    if re.search(r"\bevery\s+hour\b", text):
        return ("0 * * * *", "Hourly")

    # "every 30 minutes" / "every 15 minutes"
    m = re.search(r"\bevery\s+(\d+)\s+min", text)
    if m:
        mins = int(m.group(1))
        return (f"*/{mins} * * * *", f"Every {mins} minutes")

    # "twice a day"
    if re.search(r"\btwice\s+a\s+day\b", text):
        return ("0 8,18 * * *", "Twice Daily")

    # "every day at Xam/Xpm" / "daily at X"
    m = re.search(r"(?:every\s+day|daily)\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        label_hour = hour % 12 or 12
        label_ampm = "AM" if hour < 12 else "PM"
        label_min = f":{minute:02d}" if minute else ":00"
        return (f"{minute} {hour} * * *", f"Daily {label_hour}{label_min} {label_ampm}")

    # "every morning"
    if re.search(r"\bevery\s+morning\b", text):
        return ("0 8 * * *", "Daily 8:00 AM")

    # "every evening" / "every night"
    if re.search(r"\bevery\s+(evening|night)\b", text):
        return ("0 20 * * *", "Daily 8:00 PM")

    # "weekdays at Xam/pm"
    m = re.search(r"\bweekdays?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        label_hour = hour % 12 or 12
        label_ampm = "AM" if hour < 12 else "PM"
        return (f"{minute} {hour} * * 1-5", f"Weekdays {label_hour}:{minute:02d} {label_ampm}")

    # "every monday/tuesday/..." etc.
    day_map = {
        "monday": ("1", "Monday"), "tuesday": ("2", "Tuesday"),
        "wednesday": ("3", "Wednesday"), "thursday": ("4", "Thursday"),
        "friday": ("5", "Friday"), "saturday": ("6", "Saturday"),
        "sunday": ("0", "Sunday"),
    }
    for day_name, (day_num, day_label) in day_map.items():
        if day_name in text:
            m2 = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
            hour = 9
            minute = 0
            if m2:
                hour = int(m2.group(1))
                minute = int(m2.group(2) or 0)
                ampm = m2.group(3)
                if ampm == "pm" and hour < 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0
            return (f"{minute} {hour} * * {day_num}", f"Every {day_label} {hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}")

    # "at Xam" / "at X pm" (standalone time — assume daily)
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        label_hour = hour % 12 or 12
        label_ampm = "AM" if hour < 12 else "PM"
        return (f"{minute} {hour} * * *", f"Daily {label_hour}:{minute:02d} {label_ampm}")

    # Default fallback
    return ("0 9 * * *", "Daily 9:00 AM")


# ================================================================
# TASK EXECUTION
# ================================================================

def execute_task(task: dict) -> dict:
    """
    Execute a scheduled task by calling the Claude API.

    Returns a result dict with status, output_preview, duration_ms.
    """
    start = time.time()
    task_id = task.get("task_id", "unknown")

    try:
        from config.settings import CLAUDE_API_KEY

        if not CLAUDE_API_KEY:
            return {
                "task_id": task_id,
                "status": "FAILED",
                "output_preview": "ANTHROPIC_API_KEY not configured",
                "ran_at": datetime.utcnow().isoformat() + "Z",
                "duration_ms": int((time.time() - start) * 1000),
            }

        import httpx

        # Build prompt from natural_language + agent context
        nl = task.get("natural_language", task.get("name", ""))
        agent_type = task.get("agent_type", "custom")
        user_context = task.get("_user_context", "")

        system_prompt = f"You are an AetherCloud-L {agent_type} agent. Execute the following task thoroughly and return a concise result summary."

        messages = [{"role": "user", "content": f"{nl}\n\nContext: {user_context}" if user_context else nl}]

        # Build MCP servers list
        mcp_servers = task.get("mcp_servers", [])
        if agent_type == "email" and not any(s.get("name") == "gmail-mcp" for s in mcp_servers):
            mcp_servers.append({
                "type": "url",
                "url": "https://gmail.mcp.claude.com/mcp",
                "name": "gmail-mcp",
            })

        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 1000,
            "system": system_prompt,
            "messages": messages,
        }

        headers = {
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        # Extract text from response content blocks
        output_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                output_text += block.get("text", "")

        preview = output_text[:500] if output_text else "(no output)"
        duration = int((time.time() - start) * 1000)

        # Store in task history
        result = {
            "task_id": task_id,
            "status": "SUCCESS",
            "output_preview": preview,
            "ran_at": datetime.utcnow().isoformat() + "Z",
            "duration_ms": duration,
        }

        _store_task_history(task_id, result)

        return result

    except Exception as e:
        duration = int((time.time() - start) * 1000)
        logger.error("Task %s execution failed: %s", task_id, e)
        result = {
            "task_id": task_id,
            "status": "FAILED",
            "output_preview": f"Error: {str(e)[:400]}",
            "ran_at": datetime.utcnow().isoformat() + "Z",
            "duration_ms": duration,
        }
        _store_task_history(task_id, result)
        return result


def _store_task_history(task_id: str, result: dict):
    """Append a run result to the task's history file. Keep last 20."""
    history_file = CONFIG_DIR / f"task_history_{task_id}.json"
    history = []
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text())
        except Exception:
            history = []

    history.append(result)
    history = history[-20:]  # keep last 20

    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        history_file.write_text(json.dumps(history, indent=2))
    except Exception as e:
        logger.error("Failed to write task history for %s: %s", task_id, e)


def get_task_history(task_id: str) -> list:
    """Get last 20 run results for a task."""
    history_file = CONFIG_DIR / f"task_history_{task_id}.json"
    if history_file.exists():
        try:
            return json.loads(history_file.read_text())
        except Exception:
            return []
    return []


# ================================================================
# TASK STORE PERSISTENCE
# ================================================================

def load_task_store() -> dict:
    """Load tasks from config/scheduled_tasks.json."""
    if TASKS_FILE.exists():
        try:
            tasks = json.loads(TASKS_FILE.read_text())
            return {t["task_id"]: t for t in tasks}
        except Exception as e:
            logger.error("Failed to load task store: %s", e)
    return {}


def save_task_store(store: dict):
    """Persist task store to config/scheduled_tasks.json."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TASKS_FILE.write_text(json.dumps(list(store.values()), indent=2))
    except Exception as e:
        logger.error("Failed to save task store: %s", e)


# ================================================================
# TASK SCHEDULER
# ================================================================

class TaskScheduler:
    """
    APScheduler-backed task scheduler.
    Manages cron-triggered background task execution.
    """

    def __init__(self):
        self._scheduler = None
        self._running = False
        if HAS_APSCHEDULER:
            self._scheduler = BackgroundScheduler(daemon=True)
        else:
            logger.warning("APScheduler not installed. Scheduled tasks will only run manually.")

    def start(self):
        """Start the scheduler and load all enabled tasks."""
        if not self._scheduler:
            logger.warning("No scheduler available (APScheduler not installed)")
            return

        try:
            self._scheduler.start()
            self._running = True
            logger.info("Task scheduler started")
        except Exception as e:
            logger.error("Failed to start scheduler: %s", e)

    def stop(self):
        """Stop the scheduler gracefully."""
        if self._scheduler and self._running:
            try:
                self._scheduler.shutdown(wait=False)
                self._running = False
                logger.info("Task scheduler stopped")
            except Exception as e:
                logger.error("Error stopping scheduler: %s", e)

    def add_task(self, task: dict):
        """Add a task to the scheduler with its cron trigger."""
        if not self._scheduler or not self._running:
            return

        task_id = task.get("task_id")
        cron_expr = task.get("schedule_cron", "0 9 * * *")
        enabled = task.get("enabled", True)

        if not enabled:
            return

        try:
            parts = cron_expr.split()
            if len(parts) >= 5:
                trigger = CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                )
                self._scheduler.add_job(
                    self._run_task_job,
                    trigger=trigger,
                    id=task_id,
                    args=[task],
                    replace_existing=True,
                    name=task.get("name", task_id),
                )
                logger.info("Scheduled task: %s (%s)", task.get("name"), cron_expr)
        except Exception as e:
            logger.error("Failed to schedule task %s: %s", task_id, e)

    def remove_task(self, task_id: str):
        """Remove a task from the scheduler."""
        if not self._scheduler:
            return
        try:
            self._scheduler.remove_job(task_id)
            logger.info("Removed scheduled task: %s", task_id)
        except Exception:
            pass  # job may not exist

    def pause_task(self, task_id: str):
        """Pause a scheduled task."""
        if not self._scheduler:
            return
        try:
            self._scheduler.pause_job(task_id)
            logger.info("Paused task: %s", task_id)
        except Exception:
            pass

    def resume_task(self, task_id: str):
        """Resume a paused task."""
        if not self._scheduler:
            return
        try:
            self._scheduler.resume_job(task_id)
            logger.info("Resumed task: %s", task_id)
        except Exception:
            pass

    def get_next_run(self, task_id: str) -> Optional[str]:
        """Get the next scheduled run time for a task."""
        if not self._scheduler:
            return None
        try:
            job = self._scheduler.get_job(task_id)
            if job and job.next_run_time:
                return job.next_run_time.isoformat()
        except Exception:
            pass
        return None

    def _run_task_job(self, task: dict):
        """Job callback: execute the task and update the store."""
        task_id = task.get("task_id")
        logger.info("Scheduler firing task: %s", task.get("name", task_id))

        from agent.task_scheduler import execute_task, load_task_store, save_task_store

        result = execute_task(task)

        # Update the persisted store
        store = load_task_store()
        if task_id in store:
            store[task_id]["last_run"] = result["ran_at"]
            store[task_id]["last_status"] = result["status"]
            store[task_id]["last_output_preview"] = result["output_preview"]
            store[task_id]["run_count"] = store[task_id].get("run_count", 0) + 1
            save_task_store(store)
