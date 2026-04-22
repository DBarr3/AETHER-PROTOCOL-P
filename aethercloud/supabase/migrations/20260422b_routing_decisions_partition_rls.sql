-- ═══════════════════════════════════════════════════════════════════════════
-- routing_decisions — partition-level RLS (PR 1 v5 follow-up)
-- 2026-04-22
--
-- Why this exists: declarative partitioning in Postgres does NOT cascade
-- RLS from the parent to the child tables. Each partition is its own
-- table, and PostgREST (the Supabase data-API layer) exposes children
-- directly. Without RLS + a policy on each partition, a client could
-- bypass the parent's 'own rows' policy by querying the child partition.
--
-- Supabase advisor signal:
--   rls_disabled_in_public → ERROR, one per partition child.
--
-- Fix: enable RLS on every partition child and mirror the 'own rows'
-- policy from the parent. Run this after the partition-creating DO block
-- in 20260422_routing_decisions.sql, and any time new partitions are
-- added (future rollover migration).
-- ═══════════════════════════════════════════════════════════════════════════

do $$
declare
  part record;
begin
  for part in
    select c.relname
    from pg_inherits i
    join pg_class c on c.oid = i.inhrelid
    join pg_class p on p.oid = i.inhparent
    where p.relname = 'routing_decisions'
  loop
    execute format('alter table public.%I enable row level security;', part.relname);
    execute format('drop policy if exists "own rows" on public.%I;', part.relname);
    execute format(
      'create policy "own rows" on public.%I for select using (auth.uid() = user_id);',
      part.relname
    );
  end loop;
end $$;
