"""
In-memory stateful Supabase client for the Stage I integration harness.

Mimics supabase-py enough that every query shape our production modules use
(pricing_guard, router, uvt_routes, token_accountant's rpc call) returns
correct results without ever touching a network or a Postgres instance.

Why a hand-rolled fake instead of testing.postgresql:
- Windows-friendly. testing.postgresql needs pg_ctl / initdb on PATH.
- Deterministic. No schema-migration drift between harness and production.
- Fast. A 25-user × 30-day simulation does ~20k queries; SQLite or Postgres
  in-process both add 10-50ms per call via psycopg2/supabase-py round-trips.

State is held as plain dicts. Not thread-safe (the harness is single-process).

Aether Systems LLC — Patent Pending
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional


# ─── Seeded plan rows (mirror of live public.plans as of 2026-04-21) ───
# Kept in sync with aethercloud/supabase/migrations/20260421_uvt_accounting.sql
# by hand. If the migration changes, update this dict — a test will catch
# a pricing mismatch in the margin report.
PLANS_SEED: dict[str, dict] = {
    "free": {
        "tier": "free", "display_name": "Free",
        "price_usd_cents": 0, "uvt_monthly": 15_000,
        "sub_agent_cap": 5, "output_cap": 8_000,
        "opus_pct_cap": 0.0, "concurrency_cap": 1,
        "overage_rate_usd_cents_per_million": None,
        "context_budget_tokens": 8_000, "stripe_price_id": None,
        "active": True,
    },
    "solo": {
        "tier": "solo", "display_name": "Starter",
        "price_usd_cents": 1_999, "uvt_monthly": 400_000,
        "sub_agent_cap": 8, "output_cap": 16_000,
        "opus_pct_cap": 0.0, "concurrency_cap": 1,
        "overage_rate_usd_cents_per_million": 4_900,
        "context_budget_tokens": 24_000,
        "stripe_price_id": "price_1TOhH33TqWOqdd87qbWtG5ZG",
        "active": True,
    },
    "pro": {
        "tier": "pro", "display_name": "Pro",
        "price_usd_cents": 4_999, "uvt_monthly": 1_500_000,
        "sub_agent_cap": 15, "output_cap": 32_000,
        "opus_pct_cap": 0.10, "concurrency_cap": 3,
        "overage_rate_usd_cents_per_million": 3_500,
        "context_budget_tokens": 80_000,
        "stripe_price_id": "price_1TOhH23TqWOqdd87AxosMSfb",
        "active": True,
    },
    "team": {
        "tier": "team", "display_name": "Team",
        "price_usd_cents": 8_999, "uvt_monthly": 3_000_000,
        "sub_agent_cap": 25, "output_cap": 64_000,
        "opus_pct_cap": 0.25, "concurrency_cap": 10,
        "overage_rate_usd_cents_per_million": 3_200,
        "context_budget_tokens": 160_000,
        "stripe_price_id": "price_1TOhH23TqWOqdd87M3w25HEE",
        "active": True,
    },
}


@dataclass
class _DB:
    """The entire simulated schema in RAM."""
    plans: dict[str, dict] = field(default_factory=dict)
    users: dict[str, dict] = field(default_factory=dict)            # user_id → row
    users_by_email: dict[str, str] = field(default_factory=dict)    # email → user_id
    uvt_balances: list[dict] = field(default_factory=list)
    usage_events: list[dict] = field(default_factory=list)
    tasks: list[dict] = field(default_factory=list)

    def seed_plans(self) -> None:
        for tier, row in PLANS_SEED.items():
            self.plans[tier] = dict(row)

    def add_user(self, email: str, tier: str, *, overage_enabled: bool = False,
                 subscription_status: str = "active") -> str:
        uid = str(uuid.uuid4())
        self.users[uid] = {
            "id": uid,
            "email": email,
            "tier": tier,
            "license_key": f"AETH-CLD-HARN-{uid[:4].upper()}-{uid[4:8].upper()}",
            "subscription_status": subscription_status,
            "stripe_customer_id": f"cus_harness_{uid[:8]}",
            "stripe_subscription_id": f"sub_harness_{uid[:8]}",
            "overage_enabled": overage_enabled,
            "overage_cap_usd_cents": None,
            "current_period_started_at": datetime.now(timezone.utc).isoformat(),
            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        }
        self.users_by_email[email] = uid
        return uid


# ═══════════════════════════════════════════════════════════════════════════
# supabase-py-compatible response envelopes
# ═══════════════════════════════════════════════════════════════════════════


class _Resp:
    """Mimics supabase-py's execute() return value."""
    def __init__(self, data=None, count=None, error=None):
        self.data = data if data is not None else []
        self.count = count
        self.error = error


# ═══════════════════════════════════════════════════════════════════════════
# Query builder — chainable like supabase-py
# ═══════════════════════════════════════════════════════════════════════════


class _Query:
    """Accumulates a query plan and evaluates it on .execute()."""

    def __init__(self, db: _DB, table: str):
        self._db = db
        self._table = table
        self._select_cols: Optional[str] = None
        self._count_mode: Optional[str] = None
        self._filters: list[tuple] = []      # list of (op, col, value)
        self._order_col: Optional[str] = None
        self._order_desc: bool = False
        self._limit: Optional[int] = None
        self._op: str = "select"
        self._update_payload: Optional[dict] = None
        self._insert_payload: Any = None
        self._upsert_on_conflict: Optional[str] = None

    # ── builder methods (all return self to chain) ─────────────────
    def select(self, cols: str = "*", count: Optional[str] = None):
        self._op = "select"
        self._select_cols = cols
        self._count_mode = count
        return self

    def eq(self, col: str, val: Any):
        self._filters.append(("eq", col, val))
        return self

    def in_(self, col: str, vals: Iterable):
        self._filters.append(("in", col, tuple(vals)))
        return self

    def gte(self, col: str, val: Any):
        self._filters.append(("gte", col, val))
        return self

    def lte(self, col: str, val: Any):
        self._filters.append(("lte", col, val))
        return self

    def order(self, col: str, desc: bool = False):
        self._order_col = col
        self._order_desc = desc
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def update(self, payload: dict):
        self._op = "update"
        self._update_payload = dict(payload)
        return self

    def insert(self, payload):
        self._op = "insert"
        self._insert_payload = payload
        return self

    def upsert(self, payload, on_conflict: Optional[str] = None):
        self._op = "upsert"
        self._insert_payload = payload
        self._upsert_on_conflict = on_conflict
        return self

    # ── execute ───────────────────────────────────────────────────
    def execute(self) -> _Resp:
        rows = self._rows_for_table()
        if self._op == "select":
            matched = [r for r in rows if self._matches(r)]
            if self._order_col:
                matched.sort(
                    key=lambda r: (r.get(self._order_col) or ""),
                    reverse=self._order_desc,
                )
            count = len(matched) if self._count_mode == "exact" else None
            if self._limit is not None:
                matched = matched[: self._limit]
            return _Resp(data=matched, count=count)

        if self._op == "update":
            if self._table == "users":
                for uid, row in self._db.users.items():
                    if self._matches(row):
                        row.update(self._update_payload or {})
                return _Resp(data=[])
            # Not needed for the harness
            return _Resp(data=[], error=f"update not supported on {self._table}")

        if self._op in ("insert", "upsert"):
            payload = self._insert_payload
            records = payload if isinstance(payload, list) else [payload]
            inserted = []
            for rec in records:
                rec = dict(rec)
                self._db_append(rec)
                inserted.append(rec)
            return _Resp(data=inserted)

        return _Resp(data=[], error=f"unknown op {self._op}")

    # ── internals ─────────────────────────────────────────────────
    def _rows_for_table(self):
        t = self._table
        if t == "plans":       return list(self._db.plans.values())
        if t == "users":       return list(self._db.users.values())
        if t == "uvt_balances":return list(self._db.uvt_balances)
        if t == "usage_events":return list(self._db.usage_events)
        if t == "tasks":       return list(self._db.tasks)
        return []

    def _db_append(self, rec: dict) -> None:
        t = self._table
        if t == "uvt_balances": self._db.uvt_balances.append(rec); return
        if t == "usage_events": self._db.usage_events.append(rec); return
        if t == "tasks":        self._db.tasks.append(rec); return
        if t == "users":
            uid = rec.get("id") or str(uuid.uuid4())
            rec["id"] = uid
            self._db.users[uid] = rec
            return

    def _matches(self, row: dict) -> bool:
        for op, col, val in self._filters:
            rv = row.get(col)
            if op == "eq":
                if rv != val: return False
            elif op == "in":
                if rv not in val: return False
            elif op == "gte":
                if rv is None or rv < val: return False
            elif op == "lte":
                if rv is None or rv > val: return False
        return True


# ═══════════════════════════════════════════════════════════════════════════
# The client itself
# ═══════════════════════════════════════════════════════════════════════════


class InMemorySupabaseClient:
    """Drop-in for `supabase.Client`. Exposes .table(...) and .rpc(...).

    The harness seeds plans + users at construction; each /agent/run call
    then triggers ~5 queries + one rpc_record_usage. All state is in RAM.
    """

    def __init__(self, *, db: Optional[_DB] = None, seed_plans: bool = True):
        self._db = db or _DB()
        if seed_plans and not self._db.plans:
            self._db.seed_plans()

    # Underlying store exposed for the harness to introspect at end-of-run
    @property
    def db(self) -> _DB:
        return self._db

    # supabase-py surface ───────────────────────────────────────────
    def table(self, name: str) -> _Query:
        return _Query(self._db, name)

    # The `.from_("tbl")` alias — supabase-py accepts both; our code uses .table
    def from_(self, name: str) -> _Query:
        return self.table(name)

    def rpc(self, fn_name: str, params: dict) -> "_RpcBuilder":
        return _RpcBuilder(self, fn_name, params)


# ═══════════════════════════════════════════════════════════════════════════
# RPC — mirrors rpc_record_usage's semantics
# ═══════════════════════════════════════════════════════════════════════════


class _RpcBuilder:
    def __init__(self, client: InMemorySupabaseClient, fn_name: str, params: dict):
        self._client = client
        self._fn = fn_name
        self._params = params

    def execute(self) -> _Resp:
        if self._fn != "rpc_record_usage":
            return _Resp(data=[], error=f"unknown rpc: {self._fn}")
        return _rpc_record_usage(self._client.db, self._params)


def _rpc_record_usage(db: _DB, p: dict) -> _Resp:
    """Mirrors the SQL function from 20260421_uvt_accounting.sql.

    Appends one usage_events row, upserts the current-period uvt_balances
    row. Returns the new totals.
    """
    user_id = p["p_user_id"]
    task_id = p.get("p_task_id")
    model = p["p_model"]
    input_tok = int(p.get("p_input_tokens") or 0)
    output_tok = int(p.get("p_output_tokens") or 0)
    cached_tok = int(p.get("p_cached_input_tokens") or 0)
    cost = float(p.get("p_cost_usd_cents_fractional") or 0.0)
    qopc_load = p.get("p_qopc_load")

    uvt = max(0, (input_tok - cached_tok) + output_tok)

    # Period boundary comes from users.current_period_started_at.
    user = db.users.get(user_id)
    if user is None:
        return _Resp(data=[], error=f"user {user_id} not found")
    period_started_iso = user.get("current_period_started_at")
    if not period_started_iso:
        now = datetime.now(timezone.utc).isoformat()
        user["current_period_started_at"] = now
        period_started_iso = now

    # Append the event
    db.usage_events.append({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "task_id": task_id,
        "model": model,
        "input_tokens": input_tok,
        "output_tokens": output_tok,
        "cached_input_tokens": cached_tok,
        "uvt_counted": uvt,
        "cost_usd_cents_fractional": cost,
        "qopc_load": qopc_load,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # Upsert balance row for (user, period)
    row = None
    for r in db.uvt_balances:
        if r["user_id"] == user_id and r["period_started_at"] == period_started_iso:
            row = r
            break
    if row is None:
        row = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "period_started_at": period_started_iso,
            "period_ends_at": (
                datetime.fromisoformat(period_started_iso.replace("Z", "+00:00"))
                + timedelta(days=30)
            ).isoformat(),
            "total_uvt": 0,
            "haiku_uvt": 0, "sonnet_uvt": 0, "opus_uvt": 0,
            "overage_usd_cents": 0,
        }
        db.uvt_balances.append(row)

    row["total_uvt"] += uvt
    if model == "haiku":  row["haiku_uvt"]  += uvt
    if model == "sonnet": row["sonnet_uvt"] += uvt
    if model == "opus":   row["opus_uvt"]   += uvt

    return _Resp(data=[{
        "total_uvt": row["total_uvt"],
        "haiku_uvt": row["haiku_uvt"],
        "sonnet_uvt": row["sonnet_uvt"],
        "opus_uvt":  row["opus_uvt"],
    }])
