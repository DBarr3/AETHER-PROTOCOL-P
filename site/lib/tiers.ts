export type TierKey = "free" | "solo" | "pro" | "team";

export interface Tier {
  key: TierKey;
  name: string;
  price: string;            // display string, e.g. "$19/mo"
  priceNumeric: number;     // for PostHog MRR tracking
  tagline: string;
  features: string[];
  cta: string;
  isFree: boolean;
}

// Display values below MUST match the seeded rows in public.plans in Supabase.
// Source of truth at runtime is the plans table — this file is the static copy
// the marketing page bundles. Migration: 20260421_uvt_accounting.sql.
// Tier keys stay `free/solo/pro/team` in DB; `solo` displays as "Starter".
export const TIERS: Tier[] = [
  {
    key: "free",
    name: "Free",
    price: "$0/mo",
    priceNumeric: 0,
    tagline: "Try AetherCloud — no card, no commitment.",
    features: [
      "15,000 UVT/month",
      "1 connected MCP",
      "Haiku orchestrator",
      "Community support",
    ],
    cta: "Get started free",
    isFree: true,
  },
  {
    key: "solo",
    name: "Starter",
    price: "$19.99/mo",
    priceNumeric: 19.99,
    tagline: "For individuals running daily agent workflows.",
    features: [
      "400,000 UVT/month",
      "Haiku → Sonnet escalation (QOPC)",
      "Unlimited MCPs",
      "Voice-match on Gmail",
      "Email support",
    ],
    cta: "Subscribe",
    isFree: false,
  },
  {
    key: "pro",
    name: "Pro",
    price: "$49.99/mo",
    priceNumeric: 49.99,
    tagline: "For power users and small teams.",
    features: [
      "1,500,000 UVT/month",
      "Haiku → Sonnet → Opus (10% cap)",
      "3 concurrent tasks",
      "Agent pipelines",
      "Priority support",
    ],
    cta: "Subscribe",
    isFree: false,
  },
  {
    key: "team",
    name: "Team",
    price: "$89.99/mo",
    priceNumeric: 89.99,
    tagline: "For teams running shared automations.",
    features: [
      "3,000,000 UVT/month",
      "Opus up to 25% of quota",
      "10 concurrent tasks",
      "Shared agent library",
      "Dedicated support",
    ],
    cta: "Subscribe",
    isFree: false,
  },
];

// Server-side only — reads STRIPE_PRICE_AETHER_CLOUD_* env vars.
// Never call from a client component.
//
// Unified naming across the stack (2026-04-20): the Supabase edge functions
// (stripe-webhook, create-checkout-session) and this Next.js app all read
// the same env var name per tier. Set once on each platform (Supabase
// secrets + Vercel env), same Stripe price ID value. See docs/superpowers/
// specs/2026-04-20-aethersystems-net-checkout-wiring-design.md.
//
// Legacy fallback: if STRIPE_PRICE_AETHER_CLOUD_{TIER} is unset we fall
// back to the older STRIPE_PRICE_{TIER} name so an existing deploy keeps
// working until the operator renames env vars.
export function priceIdForTier(key: Exclude<TierKey, "free">): string {
  const envByTier = {
    solo: ["STRIPE_PRICE_AETHER_CLOUD_SOLO", "STRIPE_PRICE_SOLO"],
    pro:  ["STRIPE_PRICE_AETHER_CLOUD_PRO",  "STRIPE_PRICE_PRO"],
    team: ["STRIPE_PRICE_AETHER_CLOUD_TEAM", "STRIPE_PRICE_TEAM"],
  } as const;
  for (const name of envByTier[key]) {
    const v = process.env[name];
    if (v) return v;
  }
  return "";
}
