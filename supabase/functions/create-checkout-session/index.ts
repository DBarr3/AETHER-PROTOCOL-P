// Create a Stripe Checkout session for a given plan.
//
// Called from the website pricing page:
//   fetch('/functions/v1/create-checkout-session', {
//     method: 'POST',
//     headers: { 'Content-Type': 'application/json' },
//     body: JSON.stringify({ plan: 'aether_cloud_pro', email: 'user@example.com' })
//   })
//
// Returns { url } → redirect the browser to it.

import { stripe } from "../_shared/stripe.ts";
import { jsonResponse, handleOptions } from "../_shared/cors.ts";

const PLAN_TO_ENV: Record<string, string> = {
  aether_cloud_pro: "STRIPE_PRICE_AETHER_CLOUD_PRO",
  aether_cloud_team: "STRIPE_PRICE_AETHER_CLOUD_TEAM",
  aether_cloud_enterprise: "STRIPE_PRICE_AETHER_CLOUD_ENTERPRISE",
  aether_security_pro: "STRIPE_PRICE_AETHER_SECURITY_PRO",
  aether_security_team: "STRIPE_PRICE_AETHER_SECURITY_TEAM",
  aether_protocol_pro: "STRIPE_PRICE_AETHER_PROTOCOL_PRO",
};

const DEFAULT_SUCCESS_URL = "https://aethersystems.net/welcome?session={CHECKOUT_SESSION_ID}";
const DEFAULT_CANCEL_URL = "https://aethersystems.net/pricing?canceled=1";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return handleOptions();
  if (req.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, { status: 405 });
  }

  let payload: any;
  try {
    payload = await req.json();
  } catch {
    return jsonResponse({ error: "invalid_json" }, { status: 400 });
  }

  const { plan, email, success_url, cancel_url, utm } = payload;

  const priceEnvVar = PLAN_TO_ENV[plan];
  if (!priceEnvVar) {
    return jsonResponse(
      { error: "unknown_plan", plan, valid: Object.keys(PLAN_TO_ENV) },
      { status: 400 },
    );
  }

  const priceId = Deno.env.get(priceEnvVar);
  if (!priceId) {
    return jsonResponse(
      {
        error: "plan_not_configured",
        hint: `Set ${priceEnvVar} via: supabase secrets set ${priceEnvVar}=price_xxx`,
      },
      { status: 500 },
    );
  }

  try {
    const session = await stripe().checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      customer_email: email,
      allow_promotion_codes: true,
      billing_address_collection: "required",
      success_url: success_url ?? DEFAULT_SUCCESS_URL,
      cancel_url: cancel_url ?? DEFAULT_CANCEL_URL,
      subscription_data: {
        metadata: {
          aether_plan: plan,
          ...(utm ?? {}),
        },
      },
      metadata: {
        aether_plan: plan,
        ...(utm ?? {}),
      },
    });

    return jsonResponse({ ok: true, url: session.url, id: session.id });
  } catch (err) {
    console.error("[create-checkout-session]", err);
    return jsonResponse(
      { error: "stripe_error", message: (err as Error).message },
      { status: 500 },
    );
  }
});
