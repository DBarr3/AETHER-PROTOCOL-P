"""
AetherCloud-L -- QOPC Per-Agent Learning Module
Tracks task outcomes per agent and computes affinity weights
using Protocol-C seeded EMA updates with optional Qiskit
quantum perturbation.

Each agent accumulates TaskRecords, builds 6-dim feature
vectors per task type, and maintains AgentWeights that are
updated every cycle via exponential moving average with
exploration noise from a SHA-256 CSPRNG.

Aether Systems LLC -- Patent Pending
"""

import hashlib
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("aethercloud.qopc_agent")

# ================================================================
# CONSTANTS
# ================================================================

EMA_ALPHA: float = 0.3
QISKIT_BATCH_SIZE: int = 30
LOOP_INTERVAL_SEC: int = 30
MIN_SAMPLES: int = 3
DECAY_FACTOR: float = 0.95
RBF_SIGMA: float = 0.30

TASK_TYPES: List[str] = [
    "research", "write", "code", "analyze", "summarize",
    "email", "schedule", "search", "security", "data",
    "monitor", "automate", "translate", "review", "plan",
]

# Persistence directory -- created on import
QOPC_DIR: Path = Path(__file__).parent / "qopc"
QOPC_DIR.mkdir(parents=True, exist_ok=True)

# Keyword map for task classification
_TASK_KEYWORDS: Dict[str, List[str]] = {
    "research":   ["research", "investigate", "explore", "study", "survey"],
    "write":      ["write", "draft", "compose", "author", "blog", "essay"],
    "code":       ["code", "program", "implement", "develop", "debug", "fix", "refactor", "build"],
    "analyze":    ["analyze", "evaluate", "assess", "compare", "measure"],
    "summarize":  ["summarize", "summary", "recap", "condense", "digest", "tldr"],
    "email":      ["email", "mail", "inbox", "reply", "forward", "send"],
    "schedule":   ["schedule", "calendar", "meeting", "appointment", "remind"],
    "search":     ["search", "find", "lookup", "query", "locate", "discover"],
    "security":   ["security", "audit", "vulnerability", "threat", "encrypt", "auth"],
    "data":       ["data", "database", "dataset", "csv", "sql", "etl", "pipeline"],
    "monitor":    ["monitor", "watch", "alert", "observe", "track", "log"],
    "automate":   ["automate", "automation", "workflow", "script", "cron", "bot"],
    "translate":  ["translate", "translation", "localize", "i18n", "language"],
    "review":     ["review", "feedback", "critique", "inspect", "approve", "pr"],
    "plan":       ["plan", "roadmap", "strategy", "outline", "design", "architect"],
}


# ================================================================
# DATA STRUCTURES
# ================================================================

@dataclass
class TaskRecord:
    """Single recorded task outcome for an agent."""
    task_type: str
    outcome: str            # "success" | "failure" | "partial"
    tokens: int
    tools_used: List[str]
    duration_ms: int
    corrected: bool
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AgentWeights:
    """Learned affinity weights for a single agent."""
    agent_id: str
    task_affinity: Dict[str, float] = field(default_factory=dict)
    efficiency_score: float = 0.5
    reliability: float = 0.5
    cycle_count: int = 0
    last_qiskit_seed: int = 0
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sample_count: int = 0


# ================================================================
# PROTOCOL-C CSPRNG
# ================================================================

class ProtocolCRNG:
    """
    SHA-256 based deterministic CSPRNG for exploration perturbation.
    Uses Protocol-C seeding: hash-chain from an initial seed so that
    every agent's exploration trajectory is reproducible.
    """

    def __init__(self, seed: str = "protocol-c-default"):
        self._state: bytes = hashlib.sha256(seed.encode("utf-8")).digest()
        self._counter: int = 0

    def next_float(self) -> float:
        """Return a deterministic float in [0, 1)."""
        payload = self._state + self._counter.to_bytes(8, "big")
        self._state = hashlib.sha256(payload).digest()
        self._counter += 1
        # Take first 8 bytes as unsigned int, normalise to [0, 1)
        val = int.from_bytes(self._state[:8], "big")
        return val / (2**64)

    def next_gaussian(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        """Box-Muller transform for Gaussian noise."""
        u1 = max(self.next_float(), 1e-15)
        u2 = self.next_float()
        z0 = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        return mu + sigma * z0

    def reseed(self, new_seed: str) -> None:
        self._state = hashlib.sha256(new_seed.encode("utf-8")).digest()
        self._counter = 0


# ================================================================
# MATH HELPERS
# ================================================================

def rbf_similarity(a: List[float], b: List[float], sigma: float = RBF_SIGMA) -> float:
    """
    Radial Basis Function kernel matching Predator architecture.
    k(a, b) = exp(-||a - b||^2 / (2 * sigma^2))
    """
    if len(a) != len(b):
        raise ValueError(f"Dimension mismatch: {len(a)} vs {len(b)}")
    sq_dist = sum((ai - bi) ** 2 for ai, bi in zip(a, b))
    return math.exp(-sq_dist / (2.0 * sigma * sigma))


def build_feature_vector(records: List[TaskRecord], task_type: str) -> List[float]:
    """
    Build a 6-dimensional feature vector for a task type from records.
    Dimensions:
      [0] success_rate    -- fraction of successful outcomes
      [1] tokens_norm     -- mean tokens normalised to [0, 1] (cap 10 000)
      [2] duration_norm   -- mean duration normalised to [0, 1] (cap 120 000 ms)
      [3] tool_diversity  -- unique tools / max(total tools, 1)
      [4] recency         -- exponential decay weight of recent records
      [5] sample_density  -- tanh(count / 20) for saturation curve
    """
    typed = [r for r in records if r.task_type == task_type]
    if not typed:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    n = len(typed)

    # [0] success_rate
    successes = sum(1 for r in typed if r.outcome == "success")
    success_rate = successes / n

    # [1] tokens_norm -- cap at 10 000
    mean_tokens = sum(r.tokens for r in typed) / n
    tokens_norm = min(mean_tokens / 10_000.0, 1.0)

    # [2] duration_norm -- cap at 120 000 ms (2 min)
    mean_dur = sum(r.duration_ms for r in typed) / n
    duration_norm = min(mean_dur / 120_000.0, 1.0)

    # [3] tool_diversity
    all_tools: List[str] = []
    for r in typed:
        all_tools.extend(r.tools_used)
    unique_tools = len(set(all_tools))
    tool_diversity = unique_tools / max(len(all_tools), 1)

    # [4] recency -- weighted by DECAY_FACTOR^(index from newest)
    now = time.time()
    recency_sum = 0.0
    for i, r in enumerate(sorted(typed, key=lambda x: x.timestamp, reverse=True)):
        recency_sum += DECAY_FACTOR ** i
    recency = recency_sum / n  # normalised average decay

    # [5] sample_density -- tanh saturation
    sample_density = math.tanh(n / 20.0)

    return [success_rate, tokens_norm, duration_norm, tool_diversity, recency, sample_density]


# ================================================================
# QISKIT WEIGHT REFRESH (optional)
# ================================================================

def qiskit_weight_refresh(
    features: List[float],
    rng: ProtocolCRNG,
    seed: int = 42,
) -> List[float]:
    """
    Attempt Qiskit ZZFeatureMap perturbation with 512 shots.
    Falls back to ProtocolCRNG classical perturbation if Qiskit
    is not installed.

    Returns a list of perturbation deltas scaled to +/-8%.
    """
    num_features = len(features)
    try:
        from qiskit.circuit.library import ZZFeatureMap
        from qiskit.primitives import StatevectorSampler

        fmap = ZZFeatureMap(feature_dimension=num_features, reps=2)
        # Bind parameters
        bound = fmap.assign_parameters(features[:num_features])
        sampler = StatevectorSampler(seed=seed)
        job = sampler.run([bound], shots=512)
        result = job.result()
        quasi_dist = result[0].data
        # Extract counts and derive perturbation from distribution entropy
        counts = {}
        if hasattr(quasi_dist, "meas"):
            counts = quasi_dist.meas.get_counts()
        elif hasattr(quasi_dist, "get_counts"):
            counts = quasi_dist.get_counts()
        else:
            # Fallback -- iterate items
            counts = dict(quasi_dist.items()) if hasattr(quasi_dist, "items") else {}

        total_shots = sum(counts.values()) if counts else 512
        deltas: List[float] = []
        sorted_keys = sorted(counts.keys())[:num_features] if counts else []
        for i in range(num_features):
            if i < len(sorted_keys):
                prob = counts[sorted_keys[i]] / total_shots
                delta = (prob - 0.5) * 0.16  # scale to +/-8%
            else:
                delta = rng.next_gaussian(0.0, 0.04)
            deltas.append(delta)

        logger.info("Qiskit ZZFeatureMap refresh: %d shots, seed=%d", 512, seed)
        return deltas

    except ImportError:
        logger.debug("Qiskit not available; using classical ProtocolCRNG fallback")
        return [rng.next_gaussian(0.0, 0.04) for _ in range(num_features)]
    except Exception as exc:
        logger.warning("Qiskit refresh failed (%s); falling back to classical", exc)
        return [rng.next_gaussian(0.0, 0.04) for _ in range(num_features)]


# ================================================================
# QOPC AGENT LEARNER
# ================================================================

class QOPCAgentLearner:
    """
    Per-agent learning engine.
    Tracks task outcomes, computes 6-dim feature vectors, and
    maintains EMA affinity weights with Protocol-C exploration.
    """

    def __init__(self, agent_id: str):
        self.agent_id: str = agent_id
        self.records: List[TaskRecord] = []
        self.weights: AgentWeights = AgentWeights(agent_id=agent_id)
        self.rng: ProtocolCRNG = ProtocolCRNG(seed=f"agent-{agent_id}")
        self._weights_path: Path = QOPC_DIR / f"{agent_id}.json"
        self._records_path: Path = QOPC_DIR / f"{agent_id}_records.json"
        self._load()

    # ---- persistence ----

    def _load(self) -> None:
        """Load weights and records from disk if they exist."""
        if self._weights_path.exists():
            try:
                raw = json.loads(self._weights_path.read_text(encoding="utf-8"))
                self.weights = AgentWeights(
                    agent_id=raw.get("agent_id", self.agent_id),
                    task_affinity=raw.get("task_affinity", {}),
                    efficiency_score=raw.get("efficiency_score", 0.5),
                    reliability=raw.get("reliability", 0.5),
                    cycle_count=raw.get("cycle_count", 0),
                    last_qiskit_seed=raw.get("last_qiskit_seed", 0),
                    last_updated=raw.get("last_updated", ""),
                    sample_count=raw.get("sample_count", 0),
                )
                logger.debug("Loaded weights for agent %s", self.agent_id)
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Failed to load weights for %s: %s", self.agent_id, exc)

        if self._records_path.exists():
            try:
                raw_list = json.loads(self._records_path.read_text(encoding="utf-8"))
                self.records = [
                    TaskRecord(
                        task_type=r["task_type"],
                        outcome=r["outcome"],
                        tokens=r["tokens"],
                        tools_used=r.get("tools_used", []),
                        duration_ms=r["duration_ms"],
                        corrected=r.get("corrected", False),
                        timestamp=r.get("timestamp", ""),
                    )
                    for r in raw_list
                ]
                logger.debug("Loaded %d records for agent %s", len(self.records), self.agent_id)
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Failed to load records for %s: %s", self.agent_id, exc)

    def _save(self) -> None:
        """Persist weights and records to disk."""
        self._weights_path.write_text(
            json.dumps(asdict(self.weights), indent=2, default=str),
            encoding="utf-8",
        )
        self._records_path.write_text(
            json.dumps([asdict(r) for r in self.records], indent=2, default=str),
            encoding="utf-8",
        )

    # ---- task classification ----

    @staticmethod
    def _classify_task_type(raw: str) -> str:
        """
        Keyword-based mapping of a raw task description to one of
        the 15 known TASK_TYPES. Falls back to 'research' if no
        keywords match.
        """
        lower = raw.lower().strip()
        # Direct match first
        if lower in TASK_TYPES:
            return lower
        # Keyword scan
        for ttype, keywords in _TASK_KEYWORDS.items():
            for kw in keywords:
                if kw in lower:
                    return ttype
        return "research"  # default fallback

    # ---- recording ----

    def record(
        self,
        task_type: str,
        outcome: str,
        tokens: int,
        tools_used: List[str],
        duration_ms: int,
        corrected: bool = False,
    ) -> None:
        """
        Record a task outcome and run a learning cycle.
        task_type is classified via _classify_task_type if not already
        a known type.
        """
        classified = (
            task_type if task_type in TASK_TYPES
            else self._classify_task_type(task_type)
        )
        rec = TaskRecord(
            task_type=classified,
            outcome=outcome,
            tokens=tokens,
            tools_used=tools_used,
            duration_ms=duration_ms,
            corrected=corrected,
        )
        self.records.append(rec)
        self.weights.sample_count = len(self.records)
        self._run_cycle()
        self._save()

    # ---- EMA learning cycle ----

    def _run_cycle(self) -> None:
        """
        Single EMA update cycle:
        1. For each task type with records, build feature vector
        2. Compute new affinity from success_rate weighted by RBF
           similarity to an 'ideal' vector
        3. EMA blend with existing affinity
        4. Add Protocol-C exploration perturbation
        5. Every QISKIT_BATCH_SIZE cycles, run Qiskit refresh
        """
        self.weights.cycle_count += 1
        self.weights.last_updated = datetime.now(timezone.utc).isoformat()

        # Ideal feature vector: perfect success, low tokens, low duration,
        # high tool diversity, high recency, high density
        ideal = [1.0, 0.2, 0.15, 0.8, 1.0, 1.0]

        # Accumulate reliability and efficiency across all types
        total_success = 0
        total_records = 0
        total_tokens = 0
        total_duration = 0

        for ttype in TASK_TYPES:
            fv = build_feature_vector(self.records, ttype)
            if fv == [0.0] * 6:
                continue  # no records for this type

            # RBF similarity to ideal
            sim = rbf_similarity(fv, ideal)

            # Raw affinity: blend success_rate with RBF similarity
            raw_affinity = 0.6 * fv[0] + 0.4 * sim

            # EMA update
            prev = self.weights.task_affinity.get(ttype, 0.5)
            updated = EMA_ALPHA * raw_affinity + (1.0 - EMA_ALPHA) * prev

            # Protocol-C exploration perturbation
            noise = self.rng.next_gaussian(0.0, 0.02)
            updated = max(0.0, min(1.0, updated + noise))

            self.weights.task_affinity[ttype] = round(updated, 6)

            # Aggregate stats
            typed_records = [r for r in self.records if r.task_type == ttype]
            n = len(typed_records)
            total_success += sum(1 for r in typed_records if r.outcome == "success")
            total_records += n
            total_tokens += sum(r.tokens for r in typed_records)
            total_duration += sum(r.duration_ms for r in typed_records)

        # Update global scores
        if total_records > 0:
            self.weights.reliability = round(total_success / total_records, 6)
            avg_tokens = total_tokens / total_records
            avg_duration = total_duration / total_records
            # Efficiency: lower tokens + lower duration = higher score
            token_eff = max(0.0, 1.0 - avg_tokens / 10_000.0)
            dur_eff = max(0.0, 1.0 - avg_duration / 120_000.0)
            self.weights.efficiency_score = round(0.5 * token_eff + 0.5 * dur_eff, 6)

        # Qiskit refresh every QISKIT_BATCH_SIZE cycles
        if self.weights.cycle_count % QISKIT_BATCH_SIZE == 0 and total_records > 0:
            self._qiskit_refresh()

    def _qiskit_refresh(self) -> None:
        """Apply Qiskit quantum perturbation across all active task types."""
        self.weights.last_qiskit_seed += 1
        seed = self.weights.last_qiskit_seed

        for ttype in TASK_TYPES:
            fv = build_feature_vector(self.records, ttype)
            if fv == [0.0] * 6:
                continue
            deltas = qiskit_weight_refresh(fv, self.rng, seed=seed)
            prev = self.weights.task_affinity.get(ttype, 0.5)
            # Apply mean delta as perturbation
            mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
            updated = max(0.0, min(1.0, prev + mean_delta))
            self.weights.task_affinity[ttype] = round(updated, 6)

        logger.info(
            "Qiskit refresh for agent %s at cycle %d (seed=%d)",
            self.agent_id,
            self.weights.cycle_count,
            seed,
        )

    # ---- query ----

    def get_affinity(self, task_type: str) -> float:
        """
        Return 0-1 affinity score for a task type.
        Applies a confidence penalty when sample count is below MIN_SAMPLES.
        """
        classified = (
            task_type if task_type in TASK_TYPES
            else self._classify_task_type(task_type)
        )
        base = self.weights.task_affinity.get(classified, 0.5)

        # Confidence penalty for low sample counts
        typed_count = sum(1 for r in self.records if r.task_type == classified)
        if typed_count < MIN_SAMPLES:
            penalty = typed_count / MIN_SAMPLES  # 0..1 ramp
            base = base * penalty + 0.5 * (1.0 - penalty)  # blend toward 0.5

        return round(max(0.0, min(1.0, base)), 4)

    def get_summary(self) -> dict:
        """Return a dict suitable for dashboard display."""
        top_types = sorted(
            self.weights.task_affinity.items(),
            key=lambda kv: kv[1],
            reverse=True,
        )[:5]

        return {
            "agent_id": self.agent_id,
            "cycle_count": self.weights.cycle_count,
            "sample_count": self.weights.sample_count,
            "reliability": self.weights.reliability,
            "efficiency_score": self.weights.efficiency_score,
            "top_affinities": {k: v for k, v in top_types},
            "last_updated": self.weights.last_updated,
            "total_records": len(self.records),
        }


# ================================================================
# QOPC REGISTRY (singleton)
# ================================================================

class QOPCRegistry:
    """
    Singleton manager for multiple QOPCAgentLearner instances.
    Provides a clean API for the rest of the system to interact
    with per-agent learning.
    """

    _instance: Optional["QOPCRegistry"] = None
    _learners: Dict[str, QOPCAgentLearner]

    def __new__(cls) -> "QOPCRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._learners = {}
        return cls._instance

    def get(self, agent_id: str) -> QOPCAgentLearner:
        """Get or create a learner for the given agent."""
        if agent_id not in self._learners:
            self._learners[agent_id] = QOPCAgentLearner(agent_id)
        return self._learners[agent_id]

    def record(
        self,
        agent_id: str,
        task_type: str,
        outcome: str,
        tokens: int,
        tools_used: List[str],
        duration_ms: int,
        corrected: bool = False,
    ) -> None:
        """Record a task outcome for a specific agent."""
        learner = self.get(agent_id)
        learner.record(task_type, outcome, tokens, tools_used, duration_ms, corrected)

    def get_affinity(self, agent_id: str, task_type: str) -> float:
        """Get affinity score for an agent + task type pair."""
        return self.get(agent_id).get_affinity(task_type)

    def get_all_summaries(self) -> List[dict]:
        """Return dashboard summaries for every known agent."""
        return [learner.get_summary() for learner in self._learners.values()]

    def rank_agents_for_task(
        self,
        agent_ids: List[str],
        task_type: str,
    ) -> List[Tuple[str, float]]:
        """
        Rank a list of agent IDs by their affinity for a task type.
        Returns list of (agent_id, score) tuples sorted descending.
        """
        scored: List[Tuple[str, float]] = []
        for aid in agent_ids:
            score = self.get_affinity(aid, task_type)
            scored.append((aid, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
