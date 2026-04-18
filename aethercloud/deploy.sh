#!/usr/bin/env bash
# AetherCloud billing — one-shot deploy.
# Fill in the values below, then:  ./deploy.sh
set -euo pipefail

# ─────────────────────────────────────────────────────────────
# Fill these in. All are REQUIRED.
# ─────────────────────────────────────────────────────────────
PROJECT_REF="REPLACE_ME_supabase_project_ref"   # e.g. abcdefghijklmnop (from Supabase URL)
STRIPE_SECRET_KEY="sk_live_REPLACE_ME"
RESEND_API_KEY="re_REPLACE_ME"
SUPABASE_SERVICE_ROLE_KEY="eyJ_REPLACE_ME"
FROM_EMAIL="no-reply@aethersystems.net"

# Stripe price IDs — create these in Stripe dashboard first.
PRICE_SOLO="price_REPLACE_ME_solo"
PRICE_TEAM="price_REPLACE_ME_team"
PRICE_PRO="price_REPLACE_ME_pro"

# Usually no need to change these:
APP_URL="https://aethersystems.net"
SUPABASE_URL="https://${PROJECT_REF}.supabase.co"
# ─────────────────────────────────────────────────────────────

guard() {
  local name="$1" value="$2"
  if [[ "$value" == *REPLACE_ME* ]]; then
    echo "error: $name still has a REPLACE_ME placeholder. Edit deploy.sh and fill it in." >&2
    exit 1
  fi
}

guard PROJECT_REF "$PROJECT_REF"
guard STRIPE_SECRET_KEY "$STRIPE_SECRET_KEY"
guard RESEND_API_KEY "$RESEND_API_KEY"
guard SUPABASE_SERVICE_ROLE_KEY "$SUPABASE_SERVICE_ROLE_KEY"
guard PRICE_SOLO "$PRICE_SOLO"
guard PRICE_TEAM "$PRICE_TEAM"
guard PRICE_PRO "$PRICE_PRO"

if ! command -v supabase >/dev/null 2>&1; then
  echo "error: supabase CLI not found. Install: https://supabase.com/docs/guides/cli" >&2
  exit 1
fi

# cd to the directory this script lives in, so relative paths to supabase/ work.
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "▸ Linking Supabase project ($PROJECT_REF)..."
supabase link --project-ref "$PROJECT_REF" || true

echo "▸ Applying migration (creates public.users)..."
supabase db push

echo "▸ Setting secrets..."
supabase secrets set \
  STRIPE_SECRET_KEY="$STRIPE_SECRET_KEY" \
  RESEND_API_KEY="$RESEND_API_KEY" \
  SUPABASE_URL="$SUPABASE_URL" \
  SUPABASE_SERVICE_ROLE_KEY="$SUPABASE_SERVICE_ROLE_KEY" \
  APP_URL="$APP_URL" \
  FROM_EMAIL="$FROM_EMAIL" \
  PRICE_SOLO="$PRICE_SOLO" \
  PRICE_TEAM="$PRICE_TEAM" \
  PRICE_PRO="$PRICE_PRO"

echo "▸ Deploying stripe-webhook edge function..."
supabase functions deploy stripe-webhook --no-verify-jwt

FUNCTION_URL="${SUPABASE_URL}/functions/v1/stripe-webhook"

cat <<EOF

─────────────────────────────────────────────────────────────
✓ Deployed. Function URL:
    $FUNCTION_URL

Next steps (60 seconds, one-time):
  1. Open https://dashboard.stripe.com/webhooks (Live mode).
  2. Add endpoint → paste the URL above.
  3. Select events:
       - checkout.session.completed
       - customer.subscription.updated
       - customer.subscription.deleted
       - invoice.payment_failed
  4. Copy the signing secret (whsec_...) and run:
       supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_...

See STRIPE_WEBHOOK_SETUP.md for the walkthrough.
─────────────────────────────────────────────────────────────
EOF
