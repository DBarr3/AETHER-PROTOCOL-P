/**
 * Client-side config for the aethersystems.net marketing SPA.
 *
 * All runtime-variable values are Vite env vars (VITE_*) so Vercel deploys
 * can override without a rebuild. Defaults are production-safe.
 *
 * Env vars at deploy time (Vercel project settings):
 *   VITE_SUPABASE_FUNCTIONS_URL  e.g. https://cjjcdwrnpzwlvradbros.supabase.co/functions/v1
 *   VITE_DOWNLOAD_URL            e.g. https://api.aethersystems.net/downloads/AetherCloud-Setup.exe
 *
 * The checkout + free-signup APIs are Supabase edge functions:
 *   POST {FUNCTIONS_URL}/create-checkout-session  → Stripe redirect URL
 *   POST {FUNCTIONS_URL}/free-signup              → license key + welcome email
 */

export const SUPABASE_FUNCTIONS_URL =
  import.meta.env.VITE_SUPABASE_FUNCTIONS_URL ||
  "https://cjjcdwrnpzwlvradbros.supabase.co/functions/v1";

export const DOWNLOAD_URL =
  import.meta.env.VITE_DOWNLOAD_URL ||
  "https://api.aethersystems.net/downloads/AetherCloud-Setup.exe";

/**
 * Internal anchor for "See pricing →" links.
 * The paid tier buttons on the aether-cloud page call startCheckout()
 * directly and bypass this URL.
 */
export const UPGRADE_URL = "/aether-cloud#ac-how-it-works";

/**
 * UI tier name → backend plan slug.
 *
 * Must match `PLAN_TO_ENV` in the `create-checkout-session` edge function
 * (supabase/functions/create-checkout-session/index.ts). If you add a tier
 * here, add it to the edge function's plan map + set the matching Stripe
 * price ID env var on the Supabase project.
 */
export const TIER_KEYS = {
  Free:         "free",                     // no checkout — /free-signup
  Solo:         "aether_cloud_solo",        // NEW — needs edge function update
  Professional: "aether_cloud_pro",
  Team:         "aether_cloud_team",
};

/**
 * Public URLs the marketing SPA owns. The checkout edge function posts the
 * user to these after Stripe redirects back.
 */
export const SITE_ORIGIN =
  import.meta.env.VITE_SITE_ORIGIN ||
  (typeof window !== "undefined" ? window.location.origin : "https://aethersystems.net");

export const WELCOME_URL = `${SITE_ORIGIN}/welcome?session={CHECKOUT_SESSION_ID}`;
export const CANCEL_URL  = `${SITE_ORIGIN}/aether-cloud?canceled=1#ac-how-it-works`;
