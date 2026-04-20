/**
 * Client-side config for the aethersystems.net marketing SPA.
 *
 * Runtime-variable values are Vite env vars (VITE_*) so Vercel deploys
 * can override without a rebuild. Defaults are production-safe.
 *
 * Env vars at deploy time (Vercel project settings):
 *   VITE_CHECKOUT_URL            e.g. https://app.aethersystems.net
 *   VITE_DOWNLOAD_URL            e.g. https://api.aethersystems.net/downloads/AetherCloud-Setup.exe
 *   VITE_SUPABASE_FUNCTIONS_URL  e.g. https://cjjcdwrnpzwlvradbros.supabase.co/functions/v1
 *                                (only used by the direct-to-edge-function fallback in
 *                                checkoutApi.js; the primary path is href-to-CHECKOUT_URL)
 *
 * Architecture note:
 *   The marketing SPA (this app, aethersystems.net) LINKS paid CTAs to the
 *   checkout app at CHECKOUT_URL (app.aethersystems.net). The checkout app
 *   (/site/ Next.js, already deployed as the Vercel "aether-cloud" project)
 *   owns Subscribe buttons → /api/checkout → Stripe → /success.
 *   Marketing never calls Stripe directly.
 */

export const CHECKOUT_URL =
  import.meta.env.VITE_CHECKOUT_URL ||
  "https://app.aethersystems.net";

export const SUPABASE_FUNCTIONS_URL =
  import.meta.env.VITE_SUPABASE_FUNCTIONS_URL ||
  "https://cjjcdwrnpzwlvradbros.supabase.co/functions/v1";

export const DOWNLOAD_URL =
  import.meta.env.VITE_DOWNLOAD_URL ||
  "https://api.aethersystems.net/downloads/AetherCloud-Setup.exe";

/** Internal anchor used by the "See pricing →" links on /aether-cloud. */
export const UPGRADE_URL = `${CHECKOUT_URL}/#pricing`;

/**
 * UI tier name → deep-link fragment on the checkout app.
 * The checkout page at app.aethersystems.net scrolls to the tier
 * and auto-focuses its Subscribe button. Keys match the tier.name
 * values in /aether-cloud page's pricing arrays.
 */
export const TIER_CHECKOUT_LINKS = {
  Free:         null,                                    // direct download, no checkout
  Solo:         `${CHECKOUT_URL}/#tier-solo`,
  Professional: `${CHECKOUT_URL}/#tier-pro`,
  Team:         `${CHECKOUT_URL}/#tier-team`,
};

/**
 * Plan slug passed to the Supabase edge function (create-checkout-session)
 * IF someone wires a direct call. Not used by the default href-based flow.
 * Keep in sync with PLAN_TO_ENV in supabase/functions/create-checkout-session.
 */
export const TIER_PLAN_SLUGS = {
  Free:         "free",
  Solo:         "aether_cloud_solo",
  Professional: "aether_cloud_pro",
  Team:         "aether_cloud_team",
};

/**
 * Public URLs the marketing SPA owns. Passed to the edge function
 * ONLY when checkoutApi.startCheckout() is called as a fallback path.
 */
export const SITE_ORIGIN =
  import.meta.env.VITE_SITE_ORIGIN ||
  (typeof window !== "undefined" ? window.location.origin : "https://aethersystems.net");

export const WELCOME_URL = `${SITE_ORIGIN}/welcome?session={CHECKOUT_SESSION_ID}`;
export const CANCEL_URL  = `${SITE_ORIGIN}/aether-cloud?canceled=1#ac-how-it-works`;
