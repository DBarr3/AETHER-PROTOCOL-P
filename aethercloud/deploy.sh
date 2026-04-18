#!/usr/bin/env bash
# AetherCloud billing — one-shot deploy.
# Fill in the values below, then:  ./deploy.sh
set -euo pipefail

# ─────────────────────────────────────────────────────────────
# Fill these in. All are REQUIRED.
# ─────────────────────────────────────────────────────────────
PROJECT_REF="REPLACE_ME_supabase_project_ref"   # e.g. abcdefghijklmnop
STRIPE_SECRET_KEY="sk_live_REPLACE_ME"
RESEND_API_KEY="re_REPLACE_ME"
SUPABASE_SERVICE_ROLE_KEY="sb_secret_REPLACE_ME"  # Supabase → Settings → API Keys → Secret keys
FROM_EMAIL="no-reply@aethersystems.net"

# Stripe price IDs — already created in Live mode, do not recreate.
PRICE_SOLO="price_1TNKCm3TqWOqdd87AngxY9ks"   # $19/mo
PRICE_PRO="price_1TNKCm3TqWOqdd87vSXEHnVW"    # $49/mo
PRICE_TEAM="price_1TNKCm3TqWOqdd87FJIdQFI1"   # $89/mo
# Free tier's Stripe price exists but isn't used here:
#   price_1TNKCm3TqWOqdd879Ih03NVe  ($0)

# PostHog — project 386803, US cloud.
POSTHOG_KEY="phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR"
POSTHOG_HOST="https://us.i.posthog.com"

# CORS allowlist for free-signup. Set to your Vercel URL after first deploy.
# Can be updated later with: supabase secrets set ALLOWED_ORIGIN_VERCEL=...
ALLOWED_ORIGIN_VERCEL="REPLACE_ME_after_vercel_first_deploy"   # e.g. https://aether-cloud-xxx.vercel.app

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
# ALLOWED_ORIGIN_VERCEL intentionally not guarded — first deploy runs before Vercel exists.
# Re-run deploy.sh (or just set the secret manually) after you have the Vercel URL.

if ! command -v supabase >/dev/null 2>&1; then
  echo "error: supabase CLI not found. Install: https://supabase.com/docs/guides/cli" >&2
  exit 1
fi

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "▸ Linking Supabase project ($PROJECT_REF)..."
supabase link --project-ref "$PROJECT_REF" || true

echo "▸ Applying migration (creates public.users + public.signup_attempts)..."
supabase db push

echo "▸ Setting secrets..."
SECRET_ARGS=(
  STRIPE_SECRET_KEY="$STRIPE_SECRET_KEY"
  RESEND_API_KEY="$RESEND_API_KEY"
  SUPABASE_URL="$SUPABASE_URL"
  SUPABASE_SERVICE_ROLE_KEY="$SUPABASE_SERVICE_ROLE_KEY"
  APP_URL="$APP_URL"
  FROM_EMAIL="$FROM_EMAIL"
  PRICE_SOLO="$PRICE_SOLO"
  PRICE_PRO="$PRICE_PRO"
  PRICE_TEAM="$PRICE_TEAM"
  POSTHOG_KEY="$POSTHOG_KEY"
  POSTHOG_HOST="$POSTHOG_HOST"
)
if [[ "$ALLOWED_ORIGIN_VERCEL" != *REPLACE_ME* ]]; then
  SECRET_ARGS+=(ALLOWED_ORIGIN_VERCEL="$ALLOWED_ORIGIN_VERCEL")
fi
supabase secrets set "${SECRET_ARGS[@]}"

echo "▸ Deploying stripe-webhook edge function..."
supabase functions deploy stripe-webhook --no-verify-jwt

echo "▸ Deploying free-signup edge function..."
supabase functions deploy free-signup --no-verify-jwt

WEBHOOK_URL="${SUPABASE_URL}/functions/v1/stripe-webhook"
FREE_SIGNUP_URL="${SUPABASE_URL}/functions/v1/free-signup"

cat <<EOF

─────────────────────────────────────────────────────────────
✓ Deployed.

Stripe webhook URL (register in Stripe dashboard):
  $WEBHOOK_URL

Free signup URL (set as NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL on Vercel):
  $FREE_SIGNUP_URL

Next steps:
  1. Open https://dashboard.stripe.com/webhooks (Live mode).
  2. Add endpoint with the stripe-webhook URL above.
  3. Select events: checkout.session.completed, customer.subscription.updated,
     customer.subscription.deleted, invoice.payment_failed.
  4. Copy the signing secret (whsec_...) and run:
       supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_...
  5. Deploy site/ to Vercel (see site/README.md or the spec) and, after first
     deploy, come back and run:
       supabase secrets set ALLOWED_ORIGIN_VERCEL=https://<your-vercel-url>.vercel.app
─────────────────────────────────────────────────────────────
EOF
