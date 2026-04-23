-- ═══════════════════════════════════════════════════════════════════════════
-- routing_decisions — DEFAULT partition + monthly pg_cron roll-forward
-- 2026-04-23 (Red Team #1 M1)
--
-- Why:
--   20260422_routing_decisions.sql seeds 12 monthly partitions from
--   2026-04-01 through 2027-03-31. After that, any INSERT with
--   created_at >= 2027-04-01 errors with "no partition of relation found."
--   The red-team report flagged H4 makes it invisible (default
--   _errorHandler was noop-on-paper) — H4 now emits, but the primary fix
--   is to keep the partition set current.
--
-- Two-layer defense:
--   1. DEFAULT partition — empty today, catches any row that falls
--      outside a specific monthly range. Keeps INSERTs from ever failing.
--   2. pg_cron job — creates next-month + month-after partitions on the
--      1st of each month, keeping DEFAULT empty in steady state.
--
-- The auto-extend function is idempotent (uses CREATE TABLE IF NOT EXISTS)
-- so it's safe to run repeatedly and safe to bootstrap on a cluster that
-- already has some partitions.
--
-- Follow-up for 20260422b_routing_decisions_partition_rls.sql: the RLS
-- DO block there only enables policies on existing partitions at apply
-- time. The auto-extend function below ALSO enables RLS + policy on every
-- new partition it creates, keeping the PostgREST-bypass advisor clean.
-- ═══════════════════════════════════════════════════════════════════════════

-- 1. Enable pg_cron extension (Supabase pattern: schema = extensions)
create extension if not exists pg_cron with schema extensions;

-- 2. DEFAULT partition — safety net for any unmatched created_at.
--    MUST be created before the auto-extend function runs, since specific
--    partitions cannot be added to a parent that has rows in DEFAULT
--    overlapping the new range. DEFAULT is empty at creation time here,
--    so seeding future partitions over the next decade works cleanly.
create table if not exists public.routing_decisions_default
  partition of public.routing_decisions default;

alter table public.routing_decisions_default enable row level security;
drop policy if exists "own rows" on public.routing_decisions_default;
create policy "own rows" on public.routing_decisions_default
  for select using (auth.uid() = user_id);

comment on table public.routing_decisions_default is
  'DEFAULT partition — catches rows whose created_at is outside all specific monthly partitions. Kept empty in steady state by the pg_cron roll-forward job. Non-zero row count here = alert: the cron job stopped running.';

-- 3. Auto-extend function — creates any missing monthly partition up to
--    now() + n_months_ahead. Also enables RLS + own-rows policy on each
--    new partition (mirrors 20260422b for new children).
create or replace function public.extend_routing_decisions_partitions(
  n_months_ahead int default 2
)
returns int
language plpgsql
security definer
set search_path = public
as $$
declare
  target_start date;
  target_end   date;
  pname        text;
  created      int := 0;
begin
  if n_months_ahead < 1 then
    raise exception 'n_months_ahead must be >= 1';
  end if;

  -- Start from current month, extend n months forward. Includes current
  -- month so a bootstrap call on a fresh DB also populates the present.
  for i in 0..n_months_ahead loop
    target_start := date_trunc('month', now())::date + (i || ' month')::interval;
    target_end   := target_start + interval '1 month';
    pname := format('routing_decisions_y%s_m%s',
                    extract(year from target_start),
                    lpad(extract(month from target_start)::text, 2, '0'));

    -- Idempotent: IF NOT EXISTS skips existing partitions. Returns row
    -- count via `get diagnostics` — but because we use IF NOT EXISTS,
    -- existing partitions don't raise, they just no-op.
    execute format(
      'create table if not exists public.%I partition of public.routing_decisions
         for values from (%L) to (%L);',
      pname, target_start, target_end
    );

    -- Enable RLS + policy on whatever we just created (no-op if pre-existing
    -- and already enabled).
    execute format('alter table public.%I enable row level security;', pname);
    execute format('drop policy if exists "own rows" on public.%I;', pname);
    execute format(
      'create policy "own rows" on public.%I for select using (auth.uid() = user_id);',
      pname
    );

    created := created + 1;
  end loop;

  return created;
end;
$$;

revoke all on function public.extend_routing_decisions_partitions(int) from public;
grant execute on function public.extend_routing_decisions_partitions(int) to service_role;

comment on function public.extend_routing_decisions_partitions(int) is
  'Idempotent monthly-partition auto-extender. Creates routing_decisions_yYYYY_mMM for the current month + n months ahead, enabling RLS + own-rows policy on each. Called by the pg_cron job scheduled below; safe to run manually as well.';

-- 4. Bootstrap run so we have at least current + 2 months ahead at migration time.
--    (If the 12 seeded partitions are still future, this is a no-op.)
select public.extend_routing_decisions_partitions(2);

-- 5. Schedule the cron job — 1st of each month at 00:05 UTC.
--    Using cron.schedule is idempotent only by name; use unschedule then
--    re-schedule to guarantee the latest definition.
do $$
begin
  perform cron.unschedule('routing_decisions_rollforward');
exception when others then
  null;
end $$;

select cron.schedule(
  'routing_decisions_rollforward',
  '5 0 1 * *',  -- minute 5, hour 0, day 1 of every month
  $$select public.extend_routing_decisions_partitions(2);$$
);
