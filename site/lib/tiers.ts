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

export const TIERS: Tier[] = [
  {
    key: "free",
    name: "Free",
    price: "$0/mo",
    priceNumeric: 0,
    tagline: "Try AetherCloud — no card, no commitment.",
    features: [
      "15,000 tokens/month",
      "1 connected MCP",
      "Community support",
    ],
    cta: "Get started free",
    isFree: true,
  },
  {
    key: "solo",
    name: "Solo",
    price: "$19/mo",
    priceNumeric: 19,
    tagline: "For individuals running daily agent workflows.",
    features: [
      "500,000 tokens/month",
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
    price: "$49/mo",
    priceNumeric: 49,
    tagline: "For power users and small teams.",
    features: [
      "2,000,000 tokens/month",
      "Everything in Solo",
      "Agent pipelines",
      "Priority support",
    ],
    cta: "Subscribe",
    isFree: false,
  },
  {
    key: "team",
    name: "Team",
    price: "$89/mo",
    priceNumeric: 89,
    tagline: "For teams running shared automations.",
    features: [
      "5,000,000 tokens/month",
      "Everything in Pro",
      "Shared agent library",
      "Dedicated support",
    ],
    cta: "Subscribe",
    isFree: false,
  },
];

// Server-side only — reads STRIPE_PRICE_* env vars.
// Never call from a client component.
export function priceIdForTier(key: Exclude<TierKey, "free">): string {
  switch (key) {
    case "solo": return process.env.STRIPE_PRICE_SOLO ?? "";
    case "pro":  return process.env.STRIPE_PRICE_PRO  ?? "";
    case "team": return process.env.STRIPE_PRICE_TEAM ?? "";
  }
}
