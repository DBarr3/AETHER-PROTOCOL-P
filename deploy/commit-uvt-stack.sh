#!/usr/bin/env bash
# commit-uvt-stack.sh — stages and commits the full UVT stack (A–J)
# as a single clean PR branch.
#
# SAFE BY DEFAULT: this script runs the full test suite before committing,
# stages files EXPLICITLY by path (no `git add .`), and stops if anything
# is off. It does NOT push or create the PR automatically — those are the
# final two commands at the bottom, commented out. Uncomment when you're
# ready.
#
# USAGE:
#   cd /path/to/AETHER-CLOUD   (or the worktree)
#   bash deploy/commit-uvt-stack.sh
#
# WHAT IT DOES:
#   1. Verifies you're on a feature branch (not main)
#   2. Shows you what's about to be committed
#   3. Runs the full 186-test suite — aborts if anything fails
#   4. Stages files in 5 logical groups (one `git add` per group for clarity
#      in `git status` output, but all land in the same commit)
#   5. Creates ONE commit with a structured message covering stages A–J
#   6. Stops — you review, then push + open PR manually (or uncomment the
#      bottom lines to do it all)
#
# ROLLBACK (before the final push):
#   git reset HEAD~1               # undo the commit, keep files staged
#   git reset                      # unstage everything
#
# Aether Systems LLC — Patent Pending

set -euo pipefail

# ─── 0. Sanity checks ────────────────────────────────────────────
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" = "main" ] || [ "$CURRENT_BRANCH" = "master" ]; then
    echo "[commit] refusing to commit directly to $CURRENT_BRANCH"
    echo "[commit] create a feature branch first:"
    echo "    git checkout -b feat/uvt-stack-stages-a-j"
    exit 1
fi

echo "[commit] current branch: $CURRENT_BRANCH"
echo "[commit] verifying working tree..."

if [ -z "$(git status --porcelain)" ]; then
    echo "[commit] nothing to commit — working tree clean"
    exit 0
fi

# ─── 1. Show what's about to be committed ──────────────────────────
echo ""
echo "─── files about to be staged ────────────────────────────────────"
git status --short
echo "─────────────────────────────────────────────────────────────────"
echo ""

# ─── 2. Run the full test suite first ───────────────────────────────
echo "[commit] running full UVT test suite (186 tests)..."
python -m pytest \
    tests/test_model_registry.py \
    tests/test_token_accountant.py \
    tests/test_qopc_bridge.py \
    tests/test_context_compressor.py \
    tests/test_router.py \
    tests/test_pricing_guard.py \
    tests/test_uvt_routes.py \
    tests/test_feature_flags.py \
    tests/test_health_routes.py \
    tests/harness/test_harness_smoke.py \
    -q

echo "[commit] tests green. staging files..."

# ─── 3. Stage in logical groups ─────────────────────────────────────
# Each `git add` below corresponds to one of the 10 stages (A–J). One
# commit, but the staging calls are ordered so the diff reads linearly.

# Stage A — ModelRegistry + TokenAccountant
git add lib/model_registry.py lib/token_accountant.py \
        tests/test_model_registry.py tests/test_token_accountant.py

# Stage B — refactor existing Anthropic call sites through TokenAccountant
git add api_server.py project_orchestrator.py task_decomposer.py \
        agent_pipeline.py agent/task_scheduler.py \
        desktop/main.js desktop/preload.js desktop/package.json \
        README.md

# BYOK removal (pre-Stage A, same session) — destructive change, explicit
git add -u desktop/key-manager.js   # -u catches the deletion

# Stage C — QOPCBridge + ContextCompressor
git add lib/qopc_bridge.py lib/context_compressor.py \
        tests/test_qopc_bridge.py tests/test_context_compressor.py

# Stage D — Router
git add lib/router.py tests/test_router.py

# Stage E — PricingGuard
git add lib/pricing_guard.py tests/test_pricing_guard.py

# Stage F — /agent/run + /account/usage + /account/overage
git add lib/uvt_routes.py tests/test_uvt_routes.py

# Stage G — UVT Meter v3 (frontend) + /account/usage extension (backend)
git add desktop/pages/uvt-meter/ desktop/pages/dashboard.html \
        site/lib/tiers.ts

# Supabase migration — the DB schema side of the whole thing
git add aethercloud/supabase/migrations/20260421_uvt_accounting.sql

# Stage I — integration harness + margin report
git add aether/harness/ tests/harness/test_harness_smoke.py \
        tests/harness/__init__.py \
        reports/.gitkeep reports/sample-pro-25u-30d.md

# Stage J — feature flag + healthz + deploy runbook + systemd + nginx
git add lib/feature_flags.py lib/health_routes.py \
        tests/test_feature_flags.py tests/test_health_routes.py \
        deploy/aether.service deploy/nginx.conf \
        deploy/deploy.sh deploy/rollback.sh deploy/healthcheck.sh \
        deploy/env.example deploy/README.md deploy/vps2-runbook.md \
        deploy/commit-uvt-stack.sh

# .gitignore updates (harness reports, .last-deployed-sha)
git add .gitignore

# ─── 4. Verify nothing unintended was staged ───────────────────────
echo ""
echo "─── staged diff summary ─────────────────────────────────────────"
git diff --cached --stat
echo "─────────────────────────────────────────────────────────────────"

# Ensure .env, secrets, or the DLQ path didn't sneak in.
FORBIDDEN_STAGED=$(git diff --cached --name-only | grep -E '\.env$|\.last-deployed-sha|usage_dlq\.jsonl|/credentials|secrets\.json|margin-[0-9]{8}T' || true)
if [ -n "$FORBIDDEN_STAGED" ]; then
    echo ""
    echo "[commit] REFUSING TO COMMIT — forbidden files staged:"
    echo "$FORBIDDEN_STAGED"
    echo ""
    echo "Unstage them with:  git reset $FORBIDDEN_STAGED"
    exit 1
fi

# ─── 5. Commit ─────────────────────────────────────────────────────
echo ""
echo "[commit] creating commit..."

git commit -m "$(cat <<'EOF'
feat(uvt): stages A-J - UVT accounting, router, guard, meter, harness, deploy

Ship the full User Visible Tokens (UVT) billing stack end-to-end, behind a
kill-switch feature flag for staged rollout.

Stage A - ModelRegistry + TokenAccountant
  lib/model_registry.py: one source of truth for Haiku 4.5 / Sonnet 4.6 /
    Opus 4.7 pricing + cache discount. GPT-5 and Gemma 4 slots present
    but enabled=False.
  lib/token_accountant.py: the ONLY file allowed to call api.anthropic.com.
    Auto-applies cache_control to system prompts + tool schemas. Posts
    usage via Supabase rpc_record_usage (atomic ledger write + balance
    upsert). Falls through to a local JSONL DLQ on RPC failure so we
    never silently lose billing data.

Stage B - refactor existing Anthropic call sites
  7 direct httpx.post() call sites across api_server.py,
  project_orchestrator.py, task_decomposer.py, agent_pipeline.py, and
  agent/task_scheduler.py now route through TokenAccountant. SDK-based
  legacy agents (claude_agent.py, hardened_claude_agent.py) and the
  VPS5-deployed mcp_worker deferred to Stage B.5.
  Also removes BYOK (desktop/key-manager.js + all wiring) — users no
  longer bring their own Anthropic key. All Claude calls are server-side.

Stage C - QOPCBridge + ContextCompressor
  lib/qopc_bridge.py: Haiku classifier that emits qopc_load ({light,
    medium, heavy}, confidence, reason) with a stable cached system
    prompt. Never raises — defaults to medium/0.5 on any parse failure.
  lib/context_compressor.py: char-based token estimator (len // 4 with
    95% safety margin) + trim-from-front for text / drop-oldest for
    turn lists. Keyed to plans.context_budget_tokens per tier.

Stage D - Router
  lib/router.py: classify -> pick orchestrator model -> call orchestrator.
    Light/medium/heavy map to Haiku/Sonnet/Opus, with Opus gated by
    plan.opus_pct_cap AND per-user opus_uvt sub-budget. Low-confidence
    (<0.6) heavy calls get a second-pass classify before committing to
    Opus. Fail-closed on Opus when Supabase errors.

Stage E - PricingGuard middleware
  lib/pricing_guard.py: three gates in fail-fast cost order: attribution
    (401), concurrency (429), daily soft cap at 15% of monthly (402),
    monthly quota (402). Overage_enabled bypasses daily + monthly.
    Stale-task auto-expiry (10 min) so crashed workers don't lock out
    users. Upper-bound UVT estimator uses typical 1500-token output,
    not max_tokens — makes free tier actually usable.

Stage F - API surface
  lib/uvt_routes.py: POST /agent/run (preflight -> router.route),
    GET /account/usage (snapshot + overage state + days_until_reset),
    POST /account/overage (toggle metered billing). All three gated on
    feature flag (Stage J).

Stage G - UVT Meter v3 (frontend)
  desktop/pages/uvt-meter/: droplet trigger + 152px popover tile with
    tube fill + mini bars (M/D/C). Polls /account/usage; ingests
    /agent/run responses for last-call breakdown.
  site/lib/tiers.ts: display rename Solo -> Starter; prices refreshed
    to $19.99/$49.99/$89.99; quota copy to 15k/400k/1.5M/3M UVT.

Supabase migration - public.plans, public.uvt_balances,
  public.usage_events, public.tasks + overage fields on public.users +
  rpc_record_usage (security definer, service_role only). Seeded from
  the new pricing model with tier keys preserved (free/solo/pro/team)
  for back-compat with existing rows.

Stage I - integration harness + margin report
  aether/harness/: in-memory Supabase client + FakeAnthropicTransport
    + persona-driven user simulator + CSV/MD report builder. CLI:
      python -m aether.harness.simulate --tier pro --users 25 --days 30
    Emits reports/margin-<ts>.md with per-tier margin, warning flags
    (negative margin, >40% quota hit, <5% quota hit), and routing mix
    breakdown. Committed sample: reports/sample-pro-25u-30d.md shows
    Pro at 93% margin (above the 50% acceptance floor).

Stage J - feature flag + healthz + deploy runbook
  lib/feature_flags.py: three-tier precedence (per-user overrides >
    percentage rollout > global). Deterministic SHA-256 bucketing —
    same user always gets the same answer within a rollout. Env re-read
    on every call so `systemctl set-environment` + restart changes
    rollout% without a redeploy.
  lib/health_routes.py: GET /healthz (liveness, no deps),
    /healthz/deep (Supabase probe with 1.5s timeout -> 503 on fail),
    /healthz/flags (sanitized snapshot — never leaks user IDs).
  Desktop UI: probes /healthz/flags before mounting the meter. When
    UVT is all-off, no meter renders and /agent/run 404s are avoided.
  deploy/: aether.service (hardened systemd), nginx.conf (TLS + rate
    limits + SSE-safe upstream), deploy.sh (git-reset + pip + restart +
    auto-rollback on healthcheck fail), rollback.sh (revert to
    .last-deployed-sha), healthcheck.sh (cron probe of all 3 healthz
    endpoints), env.example (every var documented with source URL),
    vps2-runbook.md (400-line operator runbook: first-time setup,
    routine redeploy, staged rollout checklist, "when X breaks").

Test suite: 186 tests across Stages A/C/D/E/F/I/J. All green, ~2s.

Kill switch: AETHER_UVT_ENABLED=false + systemctl restart aether =
3-second revert to the legacy /agent/chat path. Legacy MUST NOT be
removed for 90 days post-100%-rollout — it's the rollback target.

Deferred (post-J, not blocking):
- Stage B.5: agent/claude_agent.py + hardened_claude_agent.py SDK-
  based call sites (~60min)
- Stage D.5: sub-agent dispatch with right-sizing (~90min)
- Stripe metered-billing integration (overage $ currently stubbed to 0)
- DLQ replay cron (currently manual — re-run failed rpc_record_usage)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

echo ""
echo "[commit] commit created:"
git log --oneline -1
echo ""
echo "─── next steps ─────────────────────────────────────────────────"
echo "  1. Review the diff:  git show HEAD --stat"
echo "  2. Push the branch:  git push -u origin $CURRENT_BRANCH"
echo "  3. Open the PR:      gh pr create --title \"feat(uvt): stages A-J — UVT stack end-to-end\" --body-file deploy/PR_BODY.md"
echo ""
echo "[commit] done."

# ─── 6. Optional: push + open PR ────────────────────────────────────
# Uncomment these when you've reviewed the commit and are ready:
#
# git push -u origin "$CURRENT_BRANCH"
#
# gh pr create \
#     --title "feat(uvt): stages A-J — UVT stack end-to-end" \
#     --body-file deploy/PR_BODY.md \
#     --base main
