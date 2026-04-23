-- ═══════════════════════════════════════════════════════════════════════════
-- HISTORY-ONLY — explicit deny-all policies on server-only tables
-- Applied LIVE via Supabase MCP on 2026-04-23; committed here afterward for
-- repo history. DO NOT re-apply — duplicate policy names would error.
--
-- Supabase advisor finding: rls_enabled_no_policy (INFO, 6x)
--   Detail: public.{plans, signup_attempts, tasks, usage_events, users,
--   uvt_balances} had RLS enabled but zero policies defined. Behavior
--   was already correct (service_role bypasses RLS; anon/authenticated
--   blocked by Postgres default-deny under RLS-enabled-with-no-policy)
--   but the posture was undocumented in schema.
--
-- Fix: explicit deny-all policies. Makes the "server-only / service_role-
-- writes, no client access" posture visible at schema level.
--
-- Post-fix verification:
--   - Supabase security advisor: 6 findings cleared
--   - All 6 server_only policies present on the listed tables
-- ═══════════════════════════════════════════════════════════════════════════

create policy "server_only" on public.plans
  for all to anon, authenticated using (false) with check (false);
create policy "server_only" on public.signup_attempts
  for all to anon, authenticated using (false) with check (false);
create policy "server_only" on public.tasks
  for all to anon, authenticated using (false) with check (false);
create policy "server_only" on public.usage_events
  for all to anon, authenticated using (false) with check (false);
create policy "server_only" on public.users
  for all to anon, authenticated using (false) with check (false);
create policy "server_only" on public.uvt_balances
  for all to anon, authenticated using (false) with check (false);
