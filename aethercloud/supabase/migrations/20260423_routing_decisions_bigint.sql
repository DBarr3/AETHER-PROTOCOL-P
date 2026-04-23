-- ═══════════════════════════════════════════════════════════════════════════
-- routing_decisions — widen UVT cost columns to bigint (PR 1 v5 Red Team #1 H2)
-- 2026-04-23
--
-- Why:
--   predicted_uvt_cost, predicted_uvt_cost_simple, actual_uvt_cost were
--   declared INTEGER (int32) in 20260422_routing_decisions.sql. The weighted
--   formula with Opus (×5 multiplier) can exceed int32 max (~2.1e9) with
--   large-but-legal prompts: ceil((500M input * 1) * 5) ≈ 2.5e9 → overflow.
--   Postgres INSERT fails; fireAndForget swallows the error; audit row lost.
--   Combined with the client-trusted uvtBalance bug (C2, fixed in 85b060f)
--   this was a turn-key billing-evasion: lie about balance, spike the input
--   count, make the audit row disappear.
--
--   Zod max(2_000_000) in site/app/api/internal/router/pick/route.ts is the
--   edge-level defense; this migration makes the DB side unable to overflow
--   even if a future schema-change reopens the input cap.
--
-- Safety:
--   - ALTER COLUMN ... TYPE bigint on a partitioned parent cascades to all
--     12 monthly partitions automatically.
--   - bigint is binary-compatible with int for existing rows (int32 → int64
--     is a widening conversion). No data rewrite except for type metadata.
--   - Zero-downtime: Postgres holds ACCESS EXCLUSIVE during the ALTER but
--     the table is tiny in PR 1 (shadow mode, low write rate); sub-second.
-- ═══════════════════════════════════════════════════════════════════════════

alter table public.routing_decisions
  alter column predicted_uvt_cost        type bigint,
  alter column predicted_uvt_cost_simple type bigint,
  alter column actual_uvt_cost           type bigint;

comment on column public.routing_decisions.predicted_uvt_cost is
  'Weighted UVT cost from TS computeUvtWeighted (spec §2). bigint since 20260423 — see Red Team #1 H2. Not used for gating in PR 1 (UVT_FORMULA_ENFORCEMENT=simple).';
comment on column public.routing_decisions.predicted_uvt_cost_simple is
  'Simple UVT cost from TS computeUvtSimple = (input-cached)+output. Python-parity. bigint since 20260423 — see Red Team #1 H2. Used for balance gate and opus_pct_mtd arithmetic in PR 1.';
comment on column public.routing_decisions.actual_uvt_cost is
  'Reconciled actual UVT from usage_events (written by PR 2). bigint since 20260423 — Red Team #1 H2.';
