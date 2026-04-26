-- ═══════════════════════════════════════════════════════════════════════════
-- Phase 1 — DeepSeek V4 UVT schema readiness
-- 2026-04-26
--
-- Adds: reasoning_tokens + cache_write_tokens + shadow on usage_events
-- Adds: provider_uvt jsonb on uvt_balances (dual-write alongside legacy cols)
-- Updates: rpc_record_usage with two new params and dual-write body
-- Updates: usage_events.model + tasks.orchestrator_model CHECK to accept
--          'dsv4_flash' and 'dsv4_pro'
--
-- Does NOT add DeepSeek registry entries or adapter code — that's Phase 2.
-- ═══════════════════════════════════════════════════════════════════════════

-- 1. usage_events — new columns for DeepSeek reasoning + cache write tracking
ALTER TABLE public.usage_events
  ADD COLUMN IF NOT EXISTS reasoning_tokens integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cache_write_tokens integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS shadow boolean NOT NULL DEFAULT false;

-- Partial index on shadow — keeps hot path tight, makes shadow-eval queries fast
CREATE INDEX IF NOT EXISTS usage_events_shadow_idx
  ON public.usage_events (shadow) WHERE shadow = true;

COMMENT ON COLUMN public.usage_events.reasoning_tokens IS
  'Thinking/reasoning tokens reported by provider (DeepSeek V4-Pro). 0 for Anthropic.';
COMMENT ON COLUMN public.usage_events.cache_write_tokens IS
  'Cache write tokens reported by provider. 0 for Anthropic (cache writes are free-ish).';
COMMENT ON COLUMN public.usage_events.shadow IS
  'True for shadow-eval calls (Phase 4). Not billed to user. Partial index for fast queries.';

-- 2. Pre-flight: confirm no historical 'gpt5' rows exist (the slot was always a stub)
DO $$
DECLARE
  v_count integer;
BEGIN
  SELECT COUNT(*) INTO v_count FROM public.usage_events WHERE model = 'gpt5';
  IF v_count > 0 THEN
    RAISE EXCEPTION 'Migration aborted: % usage_events rows have model=''gpt5''. '
      'Backfill or rename before applying this migration.', v_count;
  END IF;
  SELECT COUNT(*) INTO v_count FROM public.tasks WHERE orchestrator_model = 'gpt5';
  IF v_count > 0 THEN
    RAISE EXCEPTION 'Migration aborted: % tasks rows have orchestrator_model=''gpt5''. '
      'Backfill or rename before applying this migration.', v_count;
  END IF;
END $$;

-- 3. usage_events.model CHECK — accept new model keys (gpt5 replaced by gpt55/gpt54/gpt54_mini)
ALTER TABLE public.usage_events
  DROP CONSTRAINT IF EXISTS usage_events_model_check;
ALTER TABLE public.usage_events
  ADD CONSTRAINT usage_events_model_check
  CHECK (model IN (
    'haiku','sonnet','opus',
    'gpt55','gpt54','gpt54_mini',
    'gemma',
    'dsv4_flash','dsv4_pro'
  ));

-- 4. tasks.orchestrator_model CHECK — accept new model keys
ALTER TABLE public.tasks
  DROP CONSTRAINT IF EXISTS tasks_orchestrator_model_check;
ALTER TABLE public.tasks
  ADD CONSTRAINT tasks_orchestrator_model_check
  CHECK (orchestrator_model IN (
    'haiku','sonnet','opus',
    'gpt55','gpt54','gpt54_mini',
    'gemma',
    'dsv4_flash','dsv4_pro'
  ));

-- 5. uvt_balances — provider_uvt jsonb for model-agnostic UVT tracking
ALTER TABLE public.uvt_balances
  ADD COLUMN IF NOT EXISTS provider_uvt jsonb NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.uvt_balances.provider_uvt IS
  'Model-keyed UVT breakdown: {"haiku": 1200, "sonnet": 500, "dsv4_flash": 300}. '
  'Dual-written alongside legacy haiku_uvt/sonnet_uvt/opus_uvt columns until Phase 6 '
  'removes the legacy columns after router.py migrates to reading provider_uvt.';

-- 6. rpc_record_usage — new params + dual-write body
--    Drop old signature to avoid overload ambiguity.
DROP FUNCTION IF EXISTS public.rpc_record_usage(uuid, uuid, text, integer, integer, integer, numeric, text);

CREATE OR REPLACE FUNCTION public.rpc_record_usage(
  p_user_id uuid,
  p_task_id uuid,
  p_model text,
  p_input_tokens integer,
  p_output_tokens integer,
  p_cached_input_tokens integer,
  p_cost_usd_cents_fractional numeric,
  p_qopc_load text,
  p_reasoning_tokens integer DEFAULT 0,
  p_cache_write_tokens integer DEFAULT 0
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
  -- Lock the user row to serialize concurrent calls
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

  -- Append usage event (now with reasoning + cache_write columns)
  INSERT INTO public.usage_events (
    user_id, task_id, model, input_tokens, output_tokens,
    cached_input_tokens, uvt_counted, cost_usd_cents_fractional,
    qopc_load, reasoning_tokens, cache_write_tokens
  ) VALUES (
    p_user_id, p_task_id, p_model, p_input_tokens, p_output_tokens,
    p_cached_input_tokens, v_uvt, p_cost_usd_cents_fractional,
    p_qopc_load, coalesce(p_reasoning_tokens, 0),
    coalesce(p_cache_write_tokens, 0)
  );

  -- Dual-write: legacy per-model columns + provider_uvt jsonb.
  -- Period boundary: users.current_period_started_at is lazily initialized above
  -- on first call; NO rollover mechanism exists today — Stage K planned work.
  INSERT INTO public.uvt_balances (
    user_id, period_started_at, period_ends_at,
    total_uvt, haiku_uvt, sonnet_uvt, opus_uvt, provider_uvt
  ) VALUES (
    p_user_id, v_period_start, v_period_end,
    v_uvt,
    CASE WHEN p_model = 'haiku'  THEN v_uvt ELSE 0 END,
    CASE WHEN p_model = 'sonnet' THEN v_uvt ELSE 0 END,
    CASE WHEN p_model = 'opus'   THEN v_uvt ELSE 0 END,
    jsonb_build_object(p_model, v_uvt)
  )
  ON CONFLICT (user_id, period_started_at) DO UPDATE SET
    total_uvt  = public.uvt_balances.total_uvt  + excluded.total_uvt,
    -- Legacy columns: only bump if model matches (new models hit else 0, safe)
    haiku_uvt  = public.uvt_balances.haiku_uvt  + excluded.haiku_uvt,
    sonnet_uvt = public.uvt_balances.sonnet_uvt + excluded.sonnet_uvt,
    opus_uvt   = public.uvt_balances.opus_uvt   + excluded.opus_uvt,
    -- provider_uvt: merge key, accumulate value
    provider_uvt = public.uvt_balances.provider_uvt
      || jsonb_build_object(
           p_model,
           coalesce(
             (public.uvt_balances.provider_uvt ->> p_model)::bigint, 0
           ) + v_uvt
         );

  RETURN QUERY
    SELECT b.total_uvt, b.haiku_uvt, b.sonnet_uvt, b.opus_uvt
    FROM public.uvt_balances b
    WHERE b.user_id = p_user_id AND b.period_started_at = v_period_start;
END;
$$;

-- Lock down: only service_role can call this function
REVOKE ALL ON FUNCTION public.rpc_record_usage(uuid, uuid, text, integer, integer, integer, numeric, text, integer, integer) FROM public;
REVOKE ALL ON FUNCTION public.rpc_record_usage(uuid, uuid, text, integer, integer, integer, numeric, text, integer, integer) FROM anon, authenticated;

COMMENT ON FUNCTION public.rpc_record_usage IS
  'Atomic UVT ledger write: appends usage_events + upserts uvt_balances in one transaction. '
  'Dual-writes legacy per-model columns AND provider_uvt jsonb. Returns new balance. '
  'Callable only by service_role. Phase 1 adds p_reasoning_tokens + p_cache_write_tokens.';
