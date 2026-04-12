"""
QOPC Interaction Style Engine
Aether Systems LLC · Patent Pending

Learns HOW to communicate with each user by observing interaction patterns.
Infers 6 style dimensions from behavioral signals, merges with tone wizard
data when available, and generates a natural-language injection string that
personalizes every Claude API call.

Dimensions:
  verbosity        (0=terse → 1=exhaustive)
  formality        (0=casual → 1=professional)
  technicalDepth   (0=plain language → 1=deep technical)
  formatPreference (0=prose/narrative → 1=structured/code/tables)
  pace             (0=quick answers → 1=thorough exploration)
  examplePreference(0=concepts first → 1=examples first)
"""

import json
import math
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Signal definitions ──────────────────────────────────────────

STYLE_SIGNAL_WEIGHTS = {
    # Verbosity signals
    "RESPONSE_TOO_LONG":   {"verbosity": -0.3},
    "RESPONSE_TOO_SHORT":  {"verbosity":  0.3},
    "USER_QUERY_SHORT":    {"verbosity": -0.15, "pace": 0.1},
    "USER_QUERY_LONG":     {"verbosity":  0.15, "pace": -0.1},

    # Formality signals
    "GREETING_CASUAL":     {"formality": -0.2},
    "GREETING_FORMAL":     {"formality":  0.2},
    "PUNCTUATION_MINIMAL": {"formality": -0.1},
    "PUNCTUATION_FULL":    {"formality":  0.1},

    # Technical depth signals
    "FOLLOW_UP_CLARIFY":   {"technicalDepth": -0.2},
    "USED_JARGON":         {"technicalDepth":  0.15},
    "ASKED_FOR_DETAIL":    {"technicalDepth":  0.2},

    # Format preference signals
    "COPIED_CODE":         {"formatPreference":  0.2},
    "COPIED_PROSE":        {"formatPreference": -0.1},
    "ASKED_FOR_LIST":      {"formatPreference":  0.15},
    "ASKED_FOR_TABLE":     {"formatPreference":  0.2},

    # Pace signals
    "RAPID_FIRE":          {"pace": 0.2},
    "LONG_COMPOSE":        {"pace": -0.2},
    "SKIMMED_RESPONSE":    {"pace": 0.15},
    "READ_FULL_RESPONSE":  {"pace": -0.1},

    # Example preference signals
    "EXPANDED_EXAMPLE":    {"examplePreference":  0.2},
    "SKIPPED_EXAMPLE":     {"examplePreference": -0.15},
    "ASKED_FOR_EXAMPLE":   {"examplePreference":  0.25},
}

HALF_LIFE_DAYS = 14  # Style signals decay slower than task signals (14 vs 7 days)
MAX_SIGNALS = 200
MIN_SIGNALS_FOR_INJECTION = 5  # Need at least 5 signals before injecting style
TONE_PROFILE_WEIGHT = 0.4  # 40% tone wizard, 60% inferred
QOPC_INFERRED_WEIGHT = 0.6

DEFAULT_DIMENSIONS = {
    "verbosity": 0.5,
    "formality": 0.5,
    "technicalDepth": 0.5,
    "formatPreference": 0.5,
    "pace": 0.5,
    "examplePreference": 0.5,
}

# ── Human-readable labels per dimension ─────────────────────────

DIMENSION_LABELS = {
    "verbosity": {
        "low": ("concise", "keep responses brief and actionable"),
        "mid": ("balanced", "standard detail level"),
        "high": ("detailed", "provide thorough, comprehensive responses"),
    },
    "formality": {
        "low": ("casual", "conversational tone, no corporate speak"),
        "mid": ("balanced", "professional but approachable"),
        "high": ("formal", "structured, professional language"),
    },
    "technicalDepth": {
        "low": ("accessible", "use plain language, explain concepts"),
        "mid": ("moderate", "some technical terms with brief explanations"),
        "high": ("technical", "use precise terminology, skip basics"),
    },
    "formatPreference": {
        "low": ("prose", "write in flowing paragraphs and narrative"),
        "mid": ("mixed", "blend prose with occasional structure"),
        "high": ("structured", "prefer bullet points, tables, code blocks"),
    },
    "pace": {
        "low": ("quick", "get to the answer fast, details on request"),
        "mid": ("standard", "balanced pacing"),
        "high": ("thorough", "explore topics in depth, anticipate follow-ups"),
    },
    "examplePreference": {
        "low": ("concepts-first", "explain the principle, then illustrate"),
        "mid": ("balanced", "mix concepts and examples"),
        "high": ("examples-first", "lead with concrete examples before theory"),
    },
}


@dataclass
class StyleSignal:
    signal_type: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class InteractionStyleProfile:
    """
    Per-user interaction style profile. Learns from behavioral signals,
    merges with tone wizard data, and generates prompt injection strings.
    """

    def __init__(self, user_id: str, data_dir: str = "data/users"):
        self.user_id = user_id
        self.data_dir = data_dir
        self.dimensions: dict[str, float] = dict(DEFAULT_DIMENSIONS)
        self.signals: list[dict] = []
        self.signal_count: int = 0
        self.last_updated: Optional[str] = None
        self._load()

    # ── Persistence ─────────────────────────────────────────

    @property
    def _file_path(self) -> str:
        return os.path.join(self.data_dir, self.user_id, "interaction_style.json")

    def _load(self):
        path = self._file_path
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                self.dimensions = data.get("dimensions", dict(DEFAULT_DIMENSIONS))
                self.signals = data.get("rawSignals", [])
                self.signal_count = data.get("signalCount", len(self.signals))
                self.last_updated = data.get("lastUpdated")
            except (json.JSONDecodeError, IOError):
                pass

    def save(self):
        path = self._file_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "dimensions": self.dimensions,
            "signalCount": self.signal_count,
            "lastUpdated": self.last_updated,
            "rawSignals": self.signals[-MAX_SIGNALS:],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    # ── Signal recording ────────────────────────────────────

    def record_signal(self, signal_type: str, metadata: dict = None):
        """Record a user interaction signal and recompute dimensions."""
        if signal_type not in STYLE_SIGNAL_WEIGHTS:
            return

        signal = {
            "signal_type": signal_type,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }
        self.signals.append(signal)
        if len(self.signals) > MAX_SIGNALS:
            self.signals = self.signals[-MAX_SIGNALS:]
        self.signal_count += 1
        self.last_updated = time.strftime("%Y-%m-%dT%H:%M:%S")

        self._recompute_dimensions()
        self.save()

    def _recompute_dimensions(self):
        """Recompute all 6 dimensions from accumulated signals with time decay."""
        if not self.signals:
            return

        now = time.time()
        # Accumulate weighted deltas per dimension
        dim_accum = {d: [] for d in DEFAULT_DIMENSIONS}

        for sig in self.signals:
            signal_type = sig.get("signal_type", "")
            weights = STYLE_SIGNAL_WEIGHTS.get(signal_type, {})
            if not weights:
                continue

            age_days = (now - sig.get("timestamp", now)) / 86400
            decay = math.pow(0.5, age_days / HALF_LIFE_DAYS)

            for dim, weight in weights.items():
                if dim in dim_accum:
                    dim_accum[dim].append(weight * decay)

        # Compute new dimension values
        for dim in DEFAULT_DIMENSIONS:
            values = dim_accum[dim]
            if not values:
                continue
            # Mean of weighted signals, mapped to 0-1 scale
            raw = sum(values) / len(values)
            # Current value moves toward the signal direction
            # Blend: 70% new evidence, 30% current value (momentum)
            target = max(0.0, min(1.0, 0.5 + raw / 0.6))
            self.dimensions[dim] = round(
                self.dimensions[dim] * 0.3 + target * 0.7, 3
            )

    # ── Tone profile merging ────────────────────────────────

    def merge_with_tone_profile(self, tone_data: dict):
        """
        Merge wizard-collected tone profile data with inferred dimensions.
        tone_data keys: formalityLevel, directness, warmth, humor,
                        technicalDepth, explicitness (all 0.0-1.0)
        """
        if not tone_data:
            return

        mapping = {
            "formalityLevel": "formality",
            "directness": "pace",       # directness ≈ inverse of pace
            "technicalDepth": "technicalDepth",
            "explicitness": "verbosity",  # explicitness ≈ verbosity
        }

        for tone_key, dim_key in mapping.items():
            if tone_key in tone_data and dim_key in self.dimensions:
                tone_val = float(tone_data[tone_key])
                inferred_val = self.dimensions[dim_key]
                # If we have enough signals, weight inferred higher
                if self.signal_count >= MIN_SIGNALS_FOR_INJECTION:
                    merged = tone_val * TONE_PROFILE_WEIGHT + inferred_val * QOPC_INFERRED_WEIGHT
                else:
                    # Few signals — trust the wizard more
                    merged = tone_val * 0.7 + inferred_val * 0.3
                self.dimensions[dim_key] = round(max(0.0, min(1.0, merged)), 3)

    # ── Injection generation ────────────────────────────────

    def get_style_injection(self) -> str:
        """
        Generate a natural-language injection string describing the user's
        communication preferences. Returns empty string if insufficient data.
        """
        if self.signal_count < MIN_SIGNALS_FOR_INJECTION:
            return ""

        lines = [
            f"INTERACTION STYLE PREFERENCES (learned from {self.signal_count} interactions):"
        ]

        for dim, value in self.dimensions.items():
            labels = DIMENSION_LABELS.get(dim)
            if not labels:
                continue

            pct = round(value * 100)
            if value < 0.35:
                label, desc = labels["low"]
            elif value > 0.65:
                label, desc = labels["high"]
            else:
                label, desc = labels["mid"]

            lines.append(f"- {dim.replace('P', ' p').replace('D', ' d').strip()}: "
                         f"{label} ({pct}%) — {desc}")

        return "\n".join(lines)

    def get_dimensions_dict(self) -> dict:
        """Return current dimensions as a serializable dict."""
        return {
            "dimensions": dict(self.dimensions),
            "signalCount": self.signal_count,
            "lastUpdated": self.last_updated,
        }


# ── Query analysis helpers ──────────────────────────────────────

CASUAL_GREETINGS = {"hey", "hi", "yo", "sup", "hiya", "heya", "what's up", "whats up"}
FORMAL_GREETINGS = {"hello", "good morning", "good afternoon", "dear", "greetings"}
CLARIFY_PATTERNS = [
    "what do you mean", "what does", "can you explain", "i don't understand",
    "what is", "what's a", "clarify", "confused", "not sure what",
]
ELABORATE_PATTERNS = [
    "more detail", "elaborate", "expand on", "tell me more", "go deeper",
    "can you explain further", "more about",
]
EXAMPLE_PATTERNS = [
    "give me an example", "for example", "show me", "can you demonstrate",
    "what would that look like",
]
LIST_PATTERNS = ["list", "bullet", "summarize as points", "key points"]
TABLE_PATTERNS = ["table", "compare in a table", "spreadsheet", "columns"]


def analyze_query_signals(query: str, time_since_last: float = None) -> list[str]:
    """
    Analyze a user query and return a list of style signal types to record.
    Called on each user message before sending to Claude.
    """
    signals = []
    q = query.strip().lower()
    words = q.split()

    # Length signals
    if len(words) <= 5:
        signals.append("USER_QUERY_SHORT")
    elif len(words) >= 40:
        signals.append("USER_QUERY_LONG")

    # Greeting detection
    first_words = " ".join(words[:3])
    if any(g in first_words for g in CASUAL_GREETINGS):
        signals.append("GREETING_CASUAL")
    elif any(g in first_words for g in FORMAL_GREETINGS):
        signals.append("GREETING_FORMAL")

    # Punctuation
    if q.endswith(".") or q.endswith("?") or q.count(",") >= 2:
        signals.append("PUNCTUATION_FULL")
    elif not any(q.endswith(c) for c in ".?!,;:"):
        signals.append("PUNCTUATION_MINIMAL")

    # Clarification request
    if any(p in q for p in CLARIFY_PATTERNS):
        signals.append("FOLLOW_UP_CLARIFY")

    # Elaboration request
    if any(p in q for p in ELABORATE_PATTERNS):
        signals.append("RESPONSE_TOO_SHORT")

    # Example request
    if any(p in q for p in EXAMPLE_PATTERNS):
        signals.append("ASKED_FOR_EXAMPLE")

    # Format request
    if any(p in q for p in LIST_PATTERNS):
        signals.append("ASKED_FOR_LIST")
    if any(p in q for p in TABLE_PATTERNS):
        signals.append("ASKED_FOR_TABLE")

    # Technical jargon detection (simple heuristic)
    tech_terms = {"api", "sdk", "json", "yaml", "regex", "async", "await",
                  "middleware", "endpoint", "schema", "query", "mutation",
                  "docker", "kubernetes", "ci/cd", "pipeline", "webhook",
                  "oauth", "jwt", "ssl", "dns", "tcp", "http", "websocket"}
    jargon_count = sum(1 for w in words if w in tech_terms)
    if jargon_count >= 2:
        signals.append("USED_JARGON")

    # Pace signals
    if time_since_last is not None:
        if time_since_last < 30:
            signals.append("RAPID_FIRE")
        elif time_since_last > 60:
            signals.append("LONG_COMPOSE")

    return signals


def analyze_response_signals(
    response_length: int,
    scroll_pct: float = None,
    copied_type: str = None,
) -> list[str]:
    """
    Analyze user interaction with an AI response.
    Called from the frontend via API.
    """
    signals = []

    # Scroll depth → response length preference
    if scroll_pct is not None:
        if scroll_pct < 0.3 and response_length > 500:
            signals.append("RESPONSE_TOO_LONG")
            signals.append("SKIMMED_RESPONSE")
        elif scroll_pct > 0.8:
            signals.append("READ_FULL_RESPONSE")

    # Copy events
    if copied_type == "code":
        signals.append("COPIED_CODE")
    elif copied_type == "prose":
        signals.append("COPIED_PROSE")

    return signals
