-- ═══════════════════════════════════════════════════════════════════════════
-- HISTORY-ONLY — contact_inbox backend-only lockdown
-- Applied LIVE via Supabase MCP on 2026-04-23; committed here afterward for
-- repo history. DO NOT re-apply; idempotent re-apply would succeed but the
-- operations are already in place.
--
-- Supabase advisor finding: security_definer_view (ERROR)
--   Detail: view public.contact_inbox was SECURITY DEFINER with SELECT
--   granted to anon + authenticated. The public anon key could read ~200
--   recent contact form submissions (names, emails, messages) bypassing
--   RLS on contact_submissions.
--
-- Fix:
--   1. revoke all on public.contact_inbox from anon;
--   2. revoke all on public.contact_inbox from authenticated;
--   3. alter view public.contact_inbox set (security_invoker = true);
--
-- Post-fix verification:
--   - Supabase security advisor: finding cleared
--   - contact_inbox: no anon/authenticated grants
--   - security_invoker = true
-- ═══════════════════════════════════════════════════════════════════════════

revoke all on public.contact_inbox from anon;
revoke all on public.contact_inbox from authenticated;
alter view public.contact_inbox set (security_invoker = true);
