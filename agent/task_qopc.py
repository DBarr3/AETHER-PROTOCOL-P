"""
AetherCloud-L -- QOPC Task Feedback Engine
Learns from user interactions with scheduled task outputs.
Signals: open, use, edit, ignore, delete, reschedule.

Aether Systems LLC -- Patent Pending
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("aethercloud.task_qopc")


# ================================================================
# SIGNAL MODEL
# ================================================================

@dataclass
class TaskSignal:
    task_id: str
    signal_type: str       # "OPENED" | "USED" | "EDITED" | "IGNORED" | "DELETED" | "RESCHEDULED" | "MANUAL_RUN"
    timestamp: str
    metadata: dict         # e.g. {"edit_ratio": 0.3, "time_to_open_hours": 2.1}


# Signal weights for quality score calculation
SIGNAL_WEIGHTS = {
    "USED": 0.3,
    "EDITED": 0.3,
    "MANUAL_RUN": 0.2,
    "OPENED": 0.1,
    "IGNORED": -0.15,
    "DELETED": -0.5,
    "RESCHEDULED": 0.0,
}


# ================================================================
# QOPC TASK FEEDBACK ENGINE
# ================================================================

class TaskQOPC:
    """
    Per-task QOPC feedback engine.
    Records user interaction signals and derives quality scores,
    timing recommendations, tone adjustments, and prompt injections.

    Paths resolved via config.storage per-user resolvers.
    """

    def __init__(self, username: str):
        self._username = username
        self._cache: dict[str, list[dict]] = {}

    def _signal_file(self, task_id: str) -> Path:
        from config.storage import user_task_qopc
        return user_task_qopc(self._username, task_id)

    def _load_signals(self, task_id: str) -> list[dict]:
        if task_id in self._cache:
            return self._cache[task_id]

        path = self._signal_file(task_id)
        signals = []
        if path.exists():
            try:
                signals = json.loads(path.read_text())
            except Exception as e:
                logger.warning("Failed to load QOPC signals for %s: %s", task_id, e)
                signals = []

        self._cache[task_id] = signals
        return signals

    def _save_signals(self, task_id: str, signals: list[dict]):
        path = self._signal_file(task_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Keep last 200 signals per task
            trimmed = signals[-200:]
            path.write_text(json.dumps(trimmed, indent=2))
            self._cache[task_id] = trimmed
        except Exception as e:
            logger.error("Failed to save QOPC signals for %s: %s", task_id, e)

    # ── Signal Recording ──────────────────────────────

    def record_signal(self, signal: TaskSignal) -> None:
        """Append a signal to the task's history."""
        signals = self._load_signals(signal.task_id)
        signals.append(asdict(signal))
        self._save_signals(signal.task_id, signals)
        logger.info("QOPC signal recorded: %s → %s", signal.task_id[:8], signal.signal_type)

    # ── Quality Score ─────────────────────────────────

    def get_score(self, task_id: str) -> float:
        """
        Returns 0.0-1.0 quality score based on signal history.
        Uses weighted sum of signals with exponential time decay.
        """
        signals = self._load_signals(task_id)
        if not signals:
            return 0.5  # neutral default

        now = datetime.utcnow()
        total_weight = 0.0
        total_signals = 0

        for sig in signals:
            sig_type = sig.get("signal_type", "")
            weight = SIGNAL_WEIGHTS.get(sig_type, 0.0)
            if weight == 0.0 and sig_type != "RESCHEDULED":
                continue

            # Time decay: recent signals matter more (half-life = 7 days)
            try:
                ts = datetime.fromisoformat(sig.get("timestamp", "").replace("Z", "+00:00").replace("+00:00", ""))
            except (ValueError, TypeError):
                ts = now
            days_ago = max(0, (now - ts).total_seconds() / 86400)
            decay = 0.5 ** (days_ago / 7.0)

            total_weight += weight * decay
            total_signals += 1

        if total_signals == 0:
            return 0.5

        # Normalize: raw_score is the mean weighted signal
        raw_score = total_weight / total_signals
        # Map from roughly [-0.5, 0.3] to [0, 1]
        normalized = max(0.0, min(1.0, (raw_score + 0.5) / 0.8))
        return round(normalized, 3)

    # ── Signal Count ──────────────────────────────────

    def get_signal_count(self, task_id: str) -> int:
        return len(self._load_signals(task_id))

    # ── Recommendations ───────────────────────────────

    def get_recommendations(self, task_id: str) -> dict:
        """
        Returns actionable recommendations based on signal patterns.
        """
        signals = self._load_signals(task_id)
        result = {
            "optimal_time": None,
            "suggested_depth": "standard",
            "tone_adjustment": "",
            "confidence": 0.0,
            "insights": [],
        }

        if not signals:
            return result

        count = len(signals)
        result["confidence"] = min(1.0, count / 20.0)  # needs 20 signals for full confidence

        # ── Optimal time from OPENED signals ──────────
        opened_hours = []
        for sig in signals:
            if sig.get("signal_type") == "OPENED":
                meta = sig.get("metadata", {})
                tto = meta.get("time_to_open_hours")
                if tto is not None:
                    opened_hours.append(float(tto))

        if opened_hours:
            avg_open = sum(opened_hours) / len(opened_hours)
            fast_opens = sum(1 for h in opened_hours if h <= 2.0)
            fast_pct = fast_opens / len(opened_hours)

            if fast_pct >= 0.7:
                result["insights"].append(f"Opens within 2hrs {int(fast_pct * 100)}% of the time")

            if avg_open > 0:
                result["insights"].append(f"Average time to open: {avg_open:.1f}hrs")

            # Derive optimal time: if user tends to open within 1hr, schedule is good;
            # if they open hours later, suggest shifting forward
            if avg_open > 3.0:
                result["insights"].append("User opens output late — consider scheduling earlier")

        # ── Depth from EDITED signals ─────────────────
        edit_ratios = []
        for sig in signals:
            if sig.get("signal_type") == "EDITED":
                meta = sig.get("metadata", {})
                ratio = meta.get("edit_ratio")
                if ratio is not None:
                    edit_ratios.append(float(ratio))

        if edit_ratios:
            avg_edit = sum(edit_ratios) / len(edit_ratios)
            if avg_edit > 0.5:
                result["suggested_depth"] = "brief"
                result["tone_adjustment"] = "be more concise"
                result["insights"].append("Heavily edited outputs suggest: be more concise")
            elif avg_edit < 0.15:
                result["suggested_depth"] = "detailed"
                result["tone_adjustment"] = "maintain current detail level"
                result["insights"].append("Low edits — output quality is well calibrated")

        # ── Usage patterns ────────────────────────────
        used_count = sum(1 for s in signals if s.get("signal_type") == "USED")
        ignored_count = sum(1 for s in signals if s.get("signal_type") == "IGNORED")
        manual_count = sum(1 for s in signals if s.get("signal_type") == "MANUAL_RUN")

        if used_count > 0:
            use_rate = used_count / max(1, used_count + ignored_count)
            if use_rate > 0.8:
                result["insights"].append(f"High usage rate ({int(use_rate * 100)}%) — task is highly relevant")
            elif use_rate < 0.3:
                result["insights"].append(f"Low usage rate ({int(use_rate * 100)}%) — consider adjusting task focus")

        if manual_count >= 3:
            result["insights"].append(f"Manually triggered {manual_count}x — user finds this valuable on-demand")

        # ── Optimal time derivation ───────────────────
        # Look at timestamps of OPENED signals to find preferred hour
        open_timestamps = []
        for sig in signals:
            if sig.get("signal_type") in ("OPENED", "USED", "MANUAL_RUN"):
                try:
                    ts = sig.get("timestamp", "")
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00").replace("+00:00", ""))
                    open_timestamps.append(dt.hour + dt.minute / 60.0)
                except (ValueError, TypeError):
                    pass

        if len(open_timestamps) >= 5:
            avg_hour = sum(open_timestamps) / len(open_timestamps)
            hour_int = int(avg_hour)
            minute_int = int((avg_hour - hour_int) * 60)
            # Round to nearest 30 minutes
            minute_int = 0 if minute_int < 15 else 30 if minute_int < 45 else 0
            if minute_int == 0 and (avg_hour - hour_int) >= 0.75:
                hour_int += 1
            optimal = f"{hour_int:02d}:{minute_int:02d}"
            result["optimal_time"] = optimal
            result["insights"].append(f"Optimal schedule: {optimal}")

        # ── Confidence label ──────────────────────────
        if count >= 20:
            result["insights"].append(f"Confidence: HIGH ({count} signals)")
        elif count >= 10:
            result["insights"].append(f"Confidence: MEDIUM ({count} signals)")
        elif count >= 3:
            result["insights"].append(f"Confidence: LOW ({count} signals)")

        return result

    # ── Prompt Injection ──────────────────────────────

    def get_prompt_injection(self, task_id: str) -> str:
        """
        Returns a string to prepend to the Claude API prompt.
        Based on accumulated signal patterns.
        """
        signals = self._load_signals(task_id)
        if len(signals) < 3:
            return ""

        score = self.get_score(task_id)
        recs = self.get_recommendations(task_id)
        count = len(signals)

        parts = [f"User context: This task has been interacted with {count} times."]

        # Usage info
        used = sum(1 for s in signals if s.get("signal_type") == "USED")
        edited = sum(1 for s in signals if s.get("signal_type") == "EDITED")
        if used > 0:
            parts.append(f"Output was used directly {used} times.")
        if edited > 0:
            parts.append(f"Output was edited {edited} times before use.")

        # Depth preference
        depth = recs.get("suggested_depth", "standard")
        if depth == "brief":
            parts.append("Previous outputs that were edited heavily suggest: be more concise.")
            parts.append("Preferred depth: brief. Match this tone: direct, action-oriented.")
        elif depth == "detailed":
            parts.append("User accepts detailed outputs with minimal editing.")
            parts.append("Preferred depth: detailed. Maintain thoroughness.")

        # Tone
        tone = recs.get("tone_adjustment")
        if tone:
            parts.append(f"Tone guidance: {tone}.")

        # Time context
        opened_hours = []
        for sig in signals:
            if sig.get("signal_type") == "OPENED":
                meta = sig.get("metadata", {})
                tto = meta.get("time_to_open_hours")
                if tto is not None:
                    opened_hours.append(float(tto))
        if opened_hours:
            avg = sum(opened_hours) / len(opened_hours)
            parts.append(f"User typically opens output within {avg:.1f} hours.")

        return "\n".join(parts)

    # ── Utility ───────────────────────────────────────

    def get_last_signals(self, task_id: str, limit: int = 20) -> list[dict]:
        """Return last N signals for display."""
        signals = self._load_signals(task_id)
        return signals[-limit:]

    def cleanup(self, task_id: str):
        """Remove all signal data for a deleted task."""
        path = self._signal_file(task_id)
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
        self._cache.pop(task_id, None)
