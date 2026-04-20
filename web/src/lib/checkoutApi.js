import {
  SUPABASE_FUNCTIONS_URL,
  WELCOME_URL,
  CANCEL_URL,
} from "./config.js";

/**
 * Start a Stripe Checkout session and redirect the browser to Stripe's
 * hosted checkout page.
 *
 * Calls the Supabase edge function `create-checkout-session` directly.
 * That function creates the session, passes our `success_url` /
 * `cancel_url` templates, and returns `{ ok, url, id }`.
 *
 * On success: `window.location.href` is replaced (no return).
 * On failure: throws with a user-readable message; caller decides how
 * to surface it.
 *
 * @param {string} plan  backend plan slug, e.g. "aether_cloud_pro"
 * @param {Object} [opts]
 * @param {string} [opts.email]   prefill Stripe Checkout email
 * @param {Object} [opts.utm]     attribution fields to attach as metadata
 */
export async function startCheckout(plan, opts = {}) {
  if (!plan || plan === "free") {
    throw new Error("free tier does not use Stripe checkout");
  }

  const res = await fetch(`${SUPABASE_FUNCTIONS_URL}/create-checkout-session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan,
      email: opts.email,
      success_url: WELCOME_URL,
      cancel_url: CANCEL_URL,
      utm: opts.utm,
    }),
    credentials: "omit",
  });

  let body;
  try {
    body = await res.json();
  } catch {
    throw new Error(`checkout endpoint returned non-JSON (${res.status})`);
  }

  if (!res.ok) {
    // Edge function returns { error: "unknown_plan" | "plan_not_configured" | "stripe_error", ... }
    const msg = body?.error === "unknown_plan"
      ? `plan "${plan}" not available yet — please contact support`
      : body?.message || body?.error || `checkout failed (${res.status})`;
    throw new Error(msg);
  }
  if (!body?.url) {
    throw new Error("checkout endpoint returned no redirect URL");
  }

  window.location.href = body.url;
  return new Promise(() => {});
}

/**
 * Submit an email for a free-tier license (email + license key delivery).
 *
 * Edge function `free-signup`:
 *   - validates email
 *   - blocks disposable domains
 *   - rate-limits 3/hour/IP
 *   - generates license key
 *   - upserts users row
 *   - sends welcome email via Resend
 *
 * @param {string} email
 * @returns {Promise<{ok: true}>}  resolves on 200, throws on error
 */
export async function submitFreeSignup(email) {
  const res = await fetch(`${SUPABASE_FUNCTIONS_URL}/free-signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim().toLowerCase() }),
    credentials: "omit",
  });
  let body;
  try { body = await res.json(); } catch {
    throw new Error(`free-signup returned non-JSON (${res.status})`);
  }
  if (!res.ok) {
    throw new Error(body?.error || `signup failed (${res.status})`);
  }
  return body;
}
