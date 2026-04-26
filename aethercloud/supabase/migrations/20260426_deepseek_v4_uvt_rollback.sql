-- ═══════════════════════════════════════════════════════════════════════════
-- ROLLBACK — Phase 1 DeepSeek V4 UVT schema readiness
-- 2026-04-26
--
-- Reverses every DDL change in 20260426_deepseek_v4_uvt.sql.
-- Run manually: psql $DATABASE_URL -f this_file.sql
--
-- Order is the reverse of the forward migration.
-- ═══════════════════════════════════════════════════════════════════════════

-- 5. rpc_record_usage — drop the 10-param signature, restore 8-param
DROP FUNCTION IF EXISTS public.rpc_record_usage(uuid, uuid, text, integer, integer, integer, numeric, text, integer, integer);

CREATE OR REPLACE FUNCTION public.rpc_record_usage(
  p_user_id uuid,
  p_task_id uuid,
  p_model text,
  p_input_tokens integer,
  p_output_tokens integer,
  p_cached_input_tokens integer,
  p_cost_usd_cents_fractional numeric,
  p_qopc_load text
) RETURNS TABLE (
  total_uvt  bigint,
  haiku_uvt  bigint,
  sonnet_uvt bigint,
  opus_uvt   bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_uvt bigint := greatest(0,
    (coalesce(p_input_tokens, 0) - coalesce(p_cached_input_tokens, 0))
    + coalesce(p_output_tokens, 0)
  );
  v_period_start timestamptz;
  v_period_end   timestamptz;
BEGIN
  SELECT current_period_started_at
    INTO v_period_start
    FROM public.users
    WHERE id = p_user_id
    FOR UPDATE;

  IF v_period_start IS NULL THEN
    v_period_start := now();
    UPDATE public.users SET current_period_started_at = v_period_start WHERE id = p_user_id;
  END IF;

  v_period_end := v_period_start + interval '30 days';

  INSERT INTO public.usage_events (
    user_id, task_id, model, input_tokens, output_tokens,
    cached_input_tokens, uvt_counted, cost_usd_cents_fractional,
    qopc_load
  ) VALUES (
    p_user_id, p_task_id, p_model, p_input_tokens, p_output_tokens,
    p_cached_input_tokens, v_uvt, p_cost_usd_cents_fractional,
    p_qopc_load
  );

  INSERT INTO public.uvt_balances (
    user_id, period_started_at, period_ends_at,
    total_uvt, haiku_uvt, sonnet_uvt, opus_uvt
  ) VALUES (
    p_user_id, v_period_start, v_period_end,
    v_uvt,
    CASE WHEN p_model = 'haiku'  THEN v_uvt ELSE 0 END,
    CASE WHEN p_model = 'sonnet' THEN v_uvt ELSE 0 END,
    CASE WHEN p_model = 'opus'   THEN v_uvt ELSE 0 END
  )
  ON CONFLICT (user_id, period_started_at) DO UPDATE SET
    total_uvt  = public.uvt_balances.total_uvt  + excluded.total_uvt,
    haiku_uvt  = public.uvt_balances.haiku_uvt  + excluded.haiku_uvt,
    sonnet_uvt = public.uvt_balances.sonnet_uvt + excluded.sonnet_uvt,
    opus_uvt   = public.uvt_balances.opus_uvt   + excluded.opus_uvt;

  RETURN QUERY
    SELECT b.total_uvt, b.haiku_uvt, b.sonnet_uvt, b.opus_uvt
    FROM public.uvt_balances b
    WHERE b.user_id = p_user_id AND b.period_started_at = v_period_start;
END;
$$;

REVOKE ALL ON FUNCTION public.rpc_record_usage(uuid, uuid, text, integer, integer, integer, numeric, text) FROM public;
REVOKE ALL ON FUNCTION public.rpc_record_usage(uuid, uuid, text, integer, integer, integer, numeric, text) FROM anon, authenticated;

-- 4. uvt_balances — drop provider_uvt jsonb column
ALTER TABLE public.uvt_balances
  DROP COLUMN IF EXISTS provider_uvt;

-- 3. tasks.orchestrator_model CHECK — restore without dsv4 keys
ALTER TABLE public.tasks
  DROP CONSTRAINT IF EXISTS tasks_orchestrator_model_check;
ALTER TABLE public.tasks
  ADD CONSTRAINT tasks_orchestrator_model_check
  CHECK (orchestrator_model IN ('haiku','sonnet','opus','gpt5','gemma'));

-- 2. usage_events.model CHECK — restore without dsv4 keys
ALTER TABLE public.usage_events
  DROP CONSTRAINT IF EXISTS usage_events_model_check;
ALTER TABLE public.usage_events
  ADD CONSTRAINT usage_events_model_check
  CHECK (model IN ('haiku','sonnet','opus','gpt5','gemma'));

-- 1. usage_events — drop new columns + partial index
DROP INDEX IF EXISTS public.usage_events_shadow_idx;
ALTER TABLE public.usage_events
  DROP COLUMN IF EXISTS shadow,
  DROP COLUMN IF EXISTS cache_write_tokens,
  DROP COLUMN IF EXISTS reasoning_tokens;
