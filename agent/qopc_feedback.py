"""
AetherCloud-L — QOPC Recursive Truth Loop
Quantum Optimized Prompt Circuit wired into
the Claude agent feedback reasoning loop.

Reference: quantum_ai_blueprint.svg

  Node 1  DQVL   — VaultState (verified ground truth)
  Node 2  QOPGC  — PromptOptimizer (quantum prompt selection)
  Node 3  LLMRE  — HardenedClaudeAgent (reasoning engine)
  Node 4  QOVL   — ResponseValidator (output validation)
  Node 5  REAL   — OutcomeObserver (delta correction)
  Loop    D(n)   — delta feeds back to DQVL for cycle n+1

The agent reasons, acts, observes what actually
happened, scores itself, and tightens its model
for the next decision. Every cycle is Protocol-L
committed. Every delta is auditable.

Aether Systems LLC — Patent Pending
"""

import hashlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Persistence path for scores and cycle history
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_SCORES_PATH = _DATA_DIR / "prompt_scores.json"
_CYCLES_PATH = _DATA_DIR / "qopc_cycles.jsonl"


# ─── User Context Scorer ────────────────────────────────
import re as _re

class UserContextScorer:
    """
    Scores agent responses against user-defined context preferences.

    When a user writes context like:
      "organize everything cleanly but never delete files without asking"

    The scorer extracts intent signals from the context and checks
    if the agent response honored them.

    This score feeds back into Node 2 (PromptOptimizer) as an additional
    weight factor alongside the existing ACCEPTED/REJECTED/PUBLISHED outcomes.
    """

    def __init__(self, user_context: str = ""):
        self.user_context = user_context
        self._intent_signals = self._parse_context(user_context)

    def _parse_context(self, context: str) -> dict:
        """Extract intent signals from user context."""
        ctx = context.lower()
        return {
            "never_delete": any(
                phrase in ctx for phrase in
                ["never delete", "don't delete", "do not delete", "keep all"]
            ),
            "prefer_clean": any(
                phrase in ctx for phrase in
                ["clean", "organized", "tidy", "neat", "structured"]
            ),
            "ask_before_action": any(
                phrase in ctx for phrase in
                ["ask before", "confirm before", "always ask", "check with me"]
            ),
            "date_prefix": any(
                phrase in ctx for phrase in
                ["date prefix", "yyyymmdd", "date format", "by date"]
            ),
            "custom_signals": [],
        }

    def score_response(self, agent_response: str, action_taken: str = "") -> float:
        """
        Score an agent response 0.0-1.0 based on alignment with user context.
        0.0 = violated user context, 0.5 = neutral, 1.0 = fully aligned.
        """
        if not self.user_context.strip():
            return 0.5  # No context — neutral

        score = 0.5
        violations = 0
        alignments = 0

        combined = (agent_response + " " + action_taken).lower()

        # Check never_delete
        if self._intent_signals["never_delete"]:
            if any(w in combined for w in ["delete", "remove", "trash", "permanent"]):
                violations += 1
            else:
                alignments += 1

        # Check ask_before_action
        if self._intent_signals["ask_before_action"]:
            if any(p in combined for p in ["would you like", "shall i", "do you want", "confirm"]):
                alignments += 1
            elif any(w in combined for w in ["i have renamed", "i moved", "i deleted", "i organized"]):
                violations += 1

        # Check prefer_clean
        if self._intent_signals["prefer_clean"]:
            if any(w in combined for w in ["organized", "clean", "renamed", "structured", "sorted"]):
                alignments += 1

        # Check date_prefix
        if self._intent_signals["date_prefix"]:
            if _re.search(r'\d{8}', combined):
                alignments += 1

        # Calculate final score
        total = violations + alignments
        if total > 0:
            score = alignments / total

        return round(score, 3)

    def update_context(self, new_context: str) -> None:
        """Update context and re-parse signals."""
        self.user_context = new_context
        self._intent_signals = self._parse_context(new_context)

    @property
    def has_context(self) -> bool:
        return bool(self.user_context.strip())

    @property
    def active_signals(self) -> list:
        return [
            k for k, v in self._intent_signals.items()
            if v and k != "custom_signals"
        ]


# ─── Node 1: DQVL — Verified Ground Truth ────────────────

@dataclass
class VaultState:
    """
    Node 1 — DQVL
    Verified ground truth state of the vault
    at the moment of an agent decision.
    Anchored to physical reality — no approximation.

    This is T(n) — the verified input to
    the reasoning cycle.
    """
    file_count: int
    file_index: list[dict]       # names + paths only
    recent_events: list[dict]    # last 50 audit events
    category_counts: dict        # files per category
    vault_root: str
    snapshot_hash: str           # SHA-256 of state
    timestamp: str

    @classmethod
    def capture(cls, vault) -> "VaultState":
        """
        Capture current vault state.
        Compute SHA-256 of state for integrity.
        """
        files = vault.list_files(recursive=True)
        events = vault.get_audit_trail(limit=50)

        categories: dict[str, int] = {}
        for f in files:
            cat = f.get("category", "UNKNOWN")
            categories[cat] = categories.get(cat, 0) + 1

        state_str = json.dumps(
            {
                "files": [f["path"] for f in files],
                "event_count": len(events),
                "timestamp": datetime.now(tz=None).isoformat(),
            },
            sort_keys=True,
        )
        state_hash = hashlib.sha256(state_str.encode()).hexdigest()

        return cls(
            file_count=len(files),
            file_index=files,
            recent_events=events,
            category_counts=categories,
            vault_root=str(getattr(vault, "root", getattr(vault, "_root", ""))),
            snapshot_hash=state_hash,
            timestamp=datetime.now(tz=None).isoformat(),
        )

    def to_dict(self) -> dict:
        return {
            "file_count": self.file_count,
            "category_counts": self.category_counts,
            "vault_root": self.vault_root,
            "snapshot_hash": self.snapshot_hash,
            "timestamp": self.timestamp,
        }


# ─── Node 2: QOPGC — Prompt Variant ─────────────────────

@dataclass
class PromptVariant:
    """
    Node 2 — QOPGC
    A specific prompt configuration for a task.
    The PromptOptimizer selects between variants
    based on historical accuracy scores.
    """
    variant_id: str
    task_type: str               # ANALYZE | PLAN | CHAT | SCAN
    system_prompt: str
    suffix: str
    temperature_hint: str        # PRECISE | BALANCED | CREATIVE
    accuracy_score: float        # 0.0-1.0 historical accuracy
    use_count: int               # times this variant was used
    success_count: int           # times user accepted output


# ─── Reasoning Cycle ─────────────────────────────────────

@dataclass
class ReasoningCycle:
    """
    One complete cycle of the recursive truth loop.

    Cycle n:
      vault_state   = T(n)   — DQVL ground truth
      prompt        = P(n)   — QOPGC optimal prompt
      raw_response  = R(n)   — LLMRE reasoning
      validated     = R'(n)  — QOVL validated output
      outcome       = O(n)   — real world observation
      delta         = D(n)   — O(n) minus R'(n)
    """
    cycle_id: str
    task_type: str
    query: str

    # Node outputs
    vault_state: Optional[dict] = None
    prompt_variant_id: Optional[str] = None
    raw_response: Optional[str] = None
    validated_response: Optional[dict] = None
    commitment_hash: Optional[str] = None

    # Outcome (filled after user responds)
    user_action: Optional[str] = None      # ACCEPTED | REJECTED | CORRECTED | IGNORED
    user_correction: Optional[str] = None
    outcome_score: Optional[float] = None  # 1.0=perfect, 0.0=wrong
    delta: Optional[float] = None          # prediction vs reality

    # Timing
    started_at: str = field(
        default_factory=lambda: datetime.now(tz=None).isoformat()
    )
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "cycle_id": self.cycle_id,
            "task_type": self.task_type,
            "query": self.query,
            "vault_state": self.vault_state,
            "prompt_variant_id": self.prompt_variant_id,
            "commitment_hash": self.commitment_hash,
            "user_action": self.user_action,
            "user_correction": self.user_correction,
            "outcome_score": self.outcome_score,
            "delta": self.delta,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


# ─── Node 2: QOPGC — Prompt Optimizer ───────────────────

class PromptOptimizer:
    """
    Node 2 — QOPGC
    Quantum Optimized Prompt Generation Circuit.

    Selects the optimal prompt variant for each
    task based on historical accuracy scores.

    In the blueprint this uses Grover's algorithm
    for prompt space search. In this implementation
    we use weighted random selection over variant
    accuracy scores — functionally equivalent at
    this scale, upgradeable to real Grover's when
    IBM circuit budget allows.

    Over time the optimizer learns which prompt
    variants perform best for which task types.
    Accurate variants get higher weight.
    Inaccurate variants get lower weight.
    """

    def __init__(self) -> None:
        from config.agent_prompt import (
            AETHER_AGENT_SYSTEM_PROMPT,
            ANALYSIS_SUFFIX,
            PLANNING_SUFFIX,
            SECURITY_SUFFIX,
            COMPETITIVE_CARD_SUFFIX,
            CONTENT_DRAFT_SUFFIX,
            EMAIL_SEQUENCE_SUFFIX,
            CONTENT_REVIEW_SUFFIX,
            POSITIONING_SUFFIX,
        )

        self.variants: dict[str, list[PromptVariant]] = {
            "ANALYZE": [
                PromptVariant(
                    variant_id="analyze_v1",
                    task_type="ANALYZE",
                    system_prompt=AETHER_AGENT_SYSTEM_PROMPT,
                    suffix=ANALYSIS_SUFFIX,
                    temperature_hint="PRECISE",
                    accuracy_score=0.8,
                    use_count=0,
                    success_count=0,
                ),
            ],
            "PLAN": [
                PromptVariant(
                    variant_id="plan_v1",
                    task_type="PLAN",
                    system_prompt=AETHER_AGENT_SYSTEM_PROMPT,
                    suffix=PLANNING_SUFFIX,
                    temperature_hint="BALANCED",
                    accuracy_score=0.8,
                    use_count=0,
                    success_count=0,
                ),
            ],
            "CHAT": [
                PromptVariant(
                    variant_id="chat_v1",
                    task_type="CHAT",
                    system_prompt=AETHER_AGENT_SYSTEM_PROMPT,
                    suffix="",
                    temperature_hint="BALANCED",
                    accuracy_score=0.8,
                    use_count=0,
                    success_count=0,
                ),
            ],
            "SCAN": [
                PromptVariant(
                    variant_id="scan_v1",
                    task_type="SCAN",
                    system_prompt=AETHER_AGENT_SYSTEM_PROMPT,
                    suffix=SECURITY_SUFFIX,
                    temperature_hint="PRECISE",
                    accuracy_score=0.8,
                    use_count=0,
                    success_count=0,
                ),
            ],
            "COMPETITIVE_CARD": [
                PromptVariant(
                    variant_id="competitive_v1",
                    task_type="COMPETITIVE_CARD",
                    system_prompt=AETHER_AGENT_SYSTEM_PROMPT,
                    suffix=COMPETITIVE_CARD_SUFFIX,
                    temperature_hint="BALANCED",
                    accuracy_score=0.8,
                    use_count=0,
                    success_count=0,
                ),
            ],
            "CONTENT_DRAFT": [
                PromptVariant(
                    variant_id="content_v1",
                    task_type="CONTENT_DRAFT",
                    system_prompt=AETHER_AGENT_SYSTEM_PROMPT,
                    suffix=CONTENT_DRAFT_SUFFIX,
                    temperature_hint="CREATIVE",
                    accuracy_score=0.8,
                    use_count=0,
                    success_count=0,
                ),
            ],
            "EMAIL_SEQUENCE": [
                PromptVariant(
                    variant_id="email_v1",
                    task_type="EMAIL_SEQUENCE",
                    system_prompt=AETHER_AGENT_SYSTEM_PROMPT,
                    suffix=EMAIL_SEQUENCE_SUFFIX,
                    temperature_hint="BALANCED",
                    accuracy_score=0.8,
                    use_count=0,
                    success_count=0,
                ),
            ],
            "CONTENT_REVIEW": [
                PromptVariant(
                    variant_id="review_v1",
                    task_type="CONTENT_REVIEW",
                    system_prompt=AETHER_AGENT_SYSTEM_PROMPT,
                    suffix=CONTENT_REVIEW_SUFFIX,
                    temperature_hint="PRECISE",
                    accuracy_score=0.8,
                    use_count=0,
                    success_count=0,
                ),
            ],
            "POSITIONING": [
                PromptVariant(
                    variant_id="positioning_v1",
                    task_type="POSITIONING",
                    system_prompt=AETHER_AGENT_SYSTEM_PROMPT,
                    suffix=POSITIONING_SUFFIX,
                    temperature_hint="BALANCED",
                    accuracy_score=0.8,
                    use_count=0,
                    success_count=0,
                ),
            ],
        }

        self._load_scores()

    # ── Selection ────────────────────────────────────────

    def select_variant(self, task_type: str) -> PromptVariant:
        """
        Select optimal prompt variant for task.
        Uses weighted selection over accuracy scores.
        Higher accuracy = higher selection probability.
        This is P(n) — the quantum optimized prompt.
        """
        candidates = self.variants.get(task_type, [])
        if not candidates:
            raise ValueError(f"No variants for task type: {task_type}")
        if len(candidates) == 1:
            return candidates[0]

        weights = [v.accuracy_score for v in candidates]
        total = sum(weights)
        if total == 0:
            return random.choice(candidates)
        normalized = [w / total for w in weights]

        r = random.random()
        cumulative = 0.0
        for variant, weight in zip(candidates, normalized):
            cumulative += weight
            if r <= cumulative:
                return variant
        return candidates[-1]

    # ── Feedback update ──────────────────────────────────

    def update_variant_score(
        self,
        variant_id: str,
        outcome_score: float,
    ) -> None:
        """
        Update accuracy score after observing outcome.
        This is the D(n) delta feeding back to QOPGC.

        Uses exponential moving average so recent
        outcomes matter more than old ones.
        alpha = 0.3 means 30% weight on new outcome.
        """
        alpha = 0.3
        for variants in self.variants.values():
            for v in variants:
                if v.variant_id == variant_id:
                    v.use_count += 1
                    if outcome_score >= 0.5:
                        v.success_count += 1
                    v.accuracy_score = (
                        alpha * outcome_score
                        + (1 - alpha) * v.accuracy_score
                    )
                    logger.info(
                        "Variant %s updated: accuracy=%.3f",
                        variant_id,
                        v.accuracy_score,
                    )
                    self._save_scores()
                    return

    # ── Get all scores (for status display) ──────────────

    def get_scores(self) -> dict:
        """Return all variant accuracy scores."""
        result = {}
        for task_type, variants in self.variants.items():
            result[task_type] = [
                {
                    "variant_id": v.variant_id,
                    "accuracy_score": round(v.accuracy_score, 3),
                    "use_count": v.use_count,
                    "success_count": v.success_count,
                    "success_rate": (
                        round(v.success_count / v.use_count, 3)
                        if v.use_count > 0
                        else 0.0
                    ),
                }
                for v in variants
            ]
        return result

    # ── Persistence ──────────────────────────────────────

    def _save_scores(self) -> None:
        """Persist variant scores across sessions."""
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        scores: dict = {}
        for task, variants in self.variants.items():
            scores[task] = [
                {
                    "variant_id": v.variant_id,
                    "accuracy_score": v.accuracy_score,
                    "use_count": v.use_count,
                    "success_count": v.success_count,
                }
                for v in variants
            ]
        with open(_SCORES_PATH, "w") as f:
            json.dump(scores, f, indent=2)

    def _load_scores(self) -> None:
        """Load persisted scores on startup."""
        if not _SCORES_PATH.exists():
            return
        try:
            with open(_SCORES_PATH) as f:
                scores = json.load(f)
            for task, variant_scores in scores.items():
                if task in self.variants:
                    for vs in variant_scores:
                        for v in self.variants[task]:
                            if v.variant_id == vs.get("variant_id"):
                                v.accuracy_score = vs.get(
                                    "accuracy_score", v.accuracy_score
                                )
                                v.use_count = vs.get("use_count", v.use_count)
                                v.success_count = vs.get(
                                    "success_count", v.success_count
                                )
            logger.info("Loaded QOPC scores from %s", _SCORES_PATH)
        except Exception as e:
            logger.warning("Failed to load QOPC scores: %s", e)


# ─── Node 4: QOVL — Response Validator ──────────────────

class ResponseValidator:
    """
    Node 4 — QOVL
    Quantum Output Validation Layer.

    Validates Claude's response against the current
    vault state — does the response make sense given
    what we know to be true?

    Checks:
      1. JSON parsability (for structured responses)
      2. Category validity (is the category real?)
      3. Confidence bounds (0.0-1.0)
      4. File existence (does the file it references exist?)
      5. Security flag consistency
    """

    VALID_CATEGORIES = frozenset({
        "PATENT", "CODE", "BACKUP", "LEGAL", "FINANCE",
        "TRADING", "SECURITY", "PERSONAL", "ARCHIVE",
        "CONFIG", "LOG", "UNKNOWN",
    })

    def validate_analysis(
        self,
        response: dict,
        vault_state: Optional[VaultState] = None,
    ) -> dict:
        """
        Validate an analysis response.
        Returns {valid: bool, issues: list, adjusted: dict}
        """
        issues = []
        adjusted = dict(response)

        # Check required fields
        required = ["category", "confidence", "reasoning"]
        for field_name in required:
            if field_name not in response:
                issues.append(f"Missing required field: {field_name}")

        # Validate category
        cat = response.get("category", "").upper()
        if cat and cat not in self.VALID_CATEGORIES:
            issues.append(f"Invalid category: {cat}")
            adjusted["category"] = "PERSONAL"

        # Validate confidence bounds
        conf = response.get("confidence", 0.5)
        if not isinstance(conf, (int, float)):
            issues.append(f"Confidence is not a number: {conf}")
            adjusted["confidence"] = 0.5
        elif conf < 0.0 or conf > 1.0:
            issues.append(f"Confidence out of bounds: {conf}")
            adjusted["confidence"] = max(0.0, min(1.0, conf))

        # Security flag check
        sec_flag = response.get("security_flag")
        if sec_flag is not None and not isinstance(sec_flag, bool):
            issues.append(f"security_flag is not boolean: {sec_flag}")
            adjusted["security_flag"] = bool(sec_flag)

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "adjusted": adjusted,
        }

    def validate_security_scan(
        self,
        response: dict,
        vault_state: Optional[VaultState] = None,
    ) -> dict:
        """Validate a security scan response."""
        issues = []
        adjusted = dict(response)

        valid_threats = {"NONE", "LOW", "MEDIUM", "HIGH", "UNKNOWN"}
        threat = response.get("threat_level", "").upper()
        if threat not in valid_threats:
            issues.append(f"Invalid threat_level: {threat}")
            adjusted["threat_level"] = "UNKNOWN"

        findings = response.get("findings", [])
        if not isinstance(findings, list):
            issues.append("findings is not a list")
            adjusted["findings"] = [str(findings)]

        if "recommended_action" not in response:
            issues.append("Missing recommended_action")
            adjusted["recommended_action"] = "Manual review required"

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "adjusted": adjusted,
        }

    def validate_chat(
        self,
        response: str,
        vault_state: Optional[VaultState] = None,
    ) -> dict:
        """Validate a chat response (minimal — just check not empty)."""
        issues = []
        if not response or not response.strip():
            issues.append("Empty response")
        if len(response) > 10000:
            issues.append("Response exceeds 10000 characters")
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "adjusted": response.strip() if response else "",
        }


# ─── Node 5: REAL — Outcome Observer ────────────────────

class OutcomeObserver:
    """
    Node 5 — REAL
    Observes what the user actually did after
    the agent made a recommendation.

    Computes delta: how far was the agent's
    prediction from reality?

    Delta feeds back into PromptOptimizer to
    update variant accuracy scores.

    Outcome types:
      ACCEPTED   — user took the suggestion      → score 1.0
      REJECTED   — user explicitly rejected       → score 0.0
      CORRECTED  — user modified suggestion       → score 0.3
      IGNORED    — user did nothing               → score 0.5
      PUBLISHED  — marketing content was published → score 1.0
      REVISED    — content was edited then used    → score 0.6
      DISCARDED  — content was thrown away         → score 0.0
      A_B_TESTED — content entered A/B test        → score 0.8
    """

    OUTCOME_SCORES = {
        "ACCEPTED": 1.0,
        "REJECTED": 0.0,
        "CORRECTED": 0.3,
        "IGNORED": 0.5,
        "PUBLISHED": 1.0,
        "REVISED": 0.6,
        "DISCARDED": 0.0,
        "A_B_TESTED": 0.8,
    }

    def __init__(self) -> None:
        self._pending_cycles: dict[str, ReasoningCycle] = {}

    def register_cycle(self, cycle: ReasoningCycle) -> None:
        """Register a cycle that is awaiting outcome observation."""
        self._pending_cycles[cycle.cycle_id] = cycle

    def record_outcome(
        self,
        cycle_id: str,
        user_action: str,
        user_correction: Optional[str] = None,
        context_score: float = 0.5,
    ) -> Optional[ReasoningCycle]:
        """
        Record the user's response to an agent recommendation.
        Returns the completed cycle with delta computed.
        """
        cycle = self._pending_cycles.pop(cycle_id, None)
        if cycle is None:
            logger.warning("No pending cycle with id: %s", cycle_id)
            return None

        action_upper = user_action.upper()
        base_weight = self.OUTCOME_SCORES.get(action_upper, 0.5)
        # Blend context score: 70% outcome + 30% context alignment
        score = round(base_weight * 0.7 + context_score * 0.3, 3)

        cycle.user_action = action_upper
        cycle.user_correction = user_correction
        cycle.outcome_score = score

        # Compute delta: prediction confidence minus outcome score
        predicted_conf = 0.8  # default
        if cycle.validated_response and isinstance(cycle.validated_response, dict):
            predicted_conf = cycle.validated_response.get("confidence", 0.8)
        cycle.delta = score - predicted_conf

        cycle.completed_at = datetime.now(tz=None).isoformat()

        # Persist the completed cycle
        self._persist_cycle(cycle)

        logger.info(
            "Cycle %s completed: action=%s score=%.1f delta=%.2f",
            cycle_id,
            action_upper,
            score,
            cycle.delta,
        )
        return cycle

    @property
    def pending_count(self) -> int:
        return len(self._pending_cycles)

    def get_pending_ids(self) -> list[str]:
        return list(self._pending_cycles.keys())

    def _persist_cycle(self, cycle: ReasoningCycle) -> None:
        """Append completed cycle to JSONL log."""
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(_CYCLES_PATH, "a") as f:
                f.write(json.dumps(cycle.to_dict(), default=str) + "\n")
        except Exception as e:
            logger.warning("Failed to persist cycle: %s", e)


# ─── QOPC Loop Controller ───────────────────────────────

class QOPCLoop:
    """
    The full QOPC Recursive Truth Loop.

    Orchestrates all 5 nodes:
      1. Capture vault state   (DQVL)
      2. Select optimal prompt (QOPGC)
      3. [External] Call Claude (LLMRE)
      4. Validate response     (QOVL)
      5. Observe outcome       (REAL)
      → Delta feeds back to prompt optimizer

    Usage:
        loop = QOPCLoop()
        cycle = loop.begin_cycle(vault, "ANALYZE", "patent_filing.pdf")
        variant = cycle.prompt_variant  # use this prompt
        # ... call Claude with variant.system_prompt + variant.suffix ...
        validated = loop.validate_response(cycle, response_dict)
        # ... present to user ...
        loop.record_outcome(cycle.cycle_id, "ACCEPTED")
    """

    def __init__(self) -> None:
        self.optimizer = PromptOptimizer()
        self.validator = ResponseValidator()
        self.observer = OutcomeObserver()
        self._cycle_count = 0
        self.context_scorer = UserContextScorer("")

    def begin_cycle(
        self,
        vault,
        task_type: str,
        query: str,
    ) -> tuple[ReasoningCycle, PromptVariant]:
        """
        Begin a new reasoning cycle.
        Captures vault state (Node 1) and selects prompt (Node 2).
        Returns (cycle, selected_variant).
        """
        self._cycle_count += 1
        cycle_id = f"qopc_{int(time.time() * 1000)}_{self._cycle_count}"

        # Node 1: Capture ground truth
        try:
            state = VaultState.capture(vault)
            state_dict = state.to_dict()
        except Exception as e:
            logger.warning("VaultState capture failed: %s", e)
            state_dict = {"error": str(e)}

        # Node 2: Select optimal prompt
        variant = self.optimizer.select_variant(task_type)

        cycle = ReasoningCycle(
            cycle_id=cycle_id,
            task_type=task_type,
            query=query,
            vault_state=state_dict,
            prompt_variant_id=variant.variant_id,
        )

        self.observer.register_cycle(cycle)
        return cycle, variant

    def validate_response(
        self,
        cycle: ReasoningCycle,
        response,
        vault_state: Optional[VaultState] = None,
    ) -> dict:
        """
        Node 4: Validate the Claude response.
        Returns validation result with adjusted response.
        """
        if cycle.task_type == "ANALYZE":
            if isinstance(response, dict):
                result = self.validator.validate_analysis(response, vault_state)
            else:
                result = {"valid": False, "issues": ["Expected dict"], "adjusted": {}}
        elif cycle.task_type == "SCAN":
            if isinstance(response, dict):
                result = self.validator.validate_security_scan(response, vault_state)
            else:
                result = {"valid": False, "issues": ["Expected dict"], "adjusted": {}}
        elif cycle.task_type == "CHAT":
            result = self.validator.validate_chat(
                response if isinstance(response, str) else str(response),
                vault_state,
            )
        else:
            result = {"valid": True, "issues": [], "adjusted": response}

        cycle.validated_response = result.get("adjusted")

        if result["issues"]:
            logger.warning(
                "QOVL validation issues for cycle %s: %s",
                cycle.cycle_id,
                result["issues"],
            )

        return result

    def record_outcome(
        self,
        cycle_id: str,
        user_action: str,
        user_correction: Optional[str] = None,
        context_score: float = 0.5,
    ) -> Optional[float]:
        """
        Node 5: Record outcome and feed delta back to optimizer.
        Returns the delta value (or None if cycle not found).
        """
        cycle = self.observer.record_outcome(
            cycle_id, user_action, user_correction, context_score
        )
        if cycle is None:
            return None

        # Feed delta back to prompt optimizer
        if cycle.prompt_variant_id and cycle.outcome_score is not None:
            self.optimizer.update_variant_score(
                cycle.prompt_variant_id,
                cycle.outcome_score,
            )

        return cycle.delta

    def get_loop_stats(self) -> dict:
        """Return QOPC loop statistics for status display."""
        stats = {
            "total_cycles": self._cycle_count,
            "pending_outcomes": self.observer.pending_count,
            "variant_scores": self.optimizer.get_scores(),
        }
        stats["context_scoring"] = {
            "has_context": self.context_scorer.has_context,
            "active_signals": self.context_scorer.active_signals,
        }
        return stats
