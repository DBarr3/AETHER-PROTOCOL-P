// Stripe client factory for edge functions.
// Uses the esm.sh build with Web Crypto + native fetch (Deno-compatible).

import Stripe from "https://esm.sh/stripe@16.12.0?target=deno";

let _stripe: Stripe | null = null;

export function stripe(): Stripe {
  if (_stripe) return _stripe;

  const key = Deno.env.get("STRIPE_SECRET_KEY");
  if (!key) throw new Error("Missing STRIPE_SECRET_KEY env var");

  _stripe = new Stripe(key, {
    apiVersion: "2024-06-20",
    httpClient: Stripe.createFetchHttpClient(),
  });

  return _stripe;
}

export function webhookSecret(): string {
  const secret = Deno.env.get("STRIPE_WEBHOOK_SECRET");
  if (!secret) throw new Error("Missing STRIPE_WEBHOOK_SECRET env var");
  return secret;
}

/** Map a Stripe price ID → AetherCloud (product, plan) pair.
 *  Configure via env vars; falls back to metadata on the Stripe price. */
export function priceToPlan(priceId: string | null | undefined): {
  product: "aether_cloud" | "aether_security" | "aether_protocol";
  plan: "free" | "pro" | "team" | "enterprise";
} | null {
  if (!priceId) return null;

  const map: Record<string, { product: any; plan: any }> = {};

  const add = (envVar: string, product: string, plan: string) => {
    const id = Deno.env.get(envVar);
    if (id) map[id] = { product, plan };
  };

  add("STRIPE_PRICE_AETHER_CLOUD_PRO", "aether_cloud", "pro");
  add("STRIPE_PRICE_AETHER_CLOUD_TEAM", "aether_cloud", "team");
  add("STRIPE_PRICE_AETHER_CLOUD_ENTERPRISE", "aether_cloud", "enterprise");
  add("STRIPE_PRICE_AETHER_SECURITY_PRO", "aether_security", "pro");
  add("STRIPE_PRICE_AETHER_SECURITY_TEAM", "aether_security", "team");
  add("STRIPE_PRICE_AETHER_PROTOCOL_PRO", "aether_protocol", "pro");

  return map[priceId] ?? null;
}
