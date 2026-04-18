import { NextResponse } from "next/server";
import { requireStripe } from "@/lib/stripe";
import { priceIdForTier, type TierKey } from "@/lib/tiers";

export const runtime = "nodejs";

const PAID_TIERS: ReadonlySet<TierKey> = new Set(["solo", "pro", "team"]);

export async function POST(req: Request) {
  let body: { tier?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }

  const tier = body.tier as TierKey | undefined;
  if (!tier || !PAID_TIERS.has(tier)) {
    return NextResponse.json({ error: "invalid tier" }, { status: 400 });
  }

  const priceId = priceIdForTier(tier as Exclude<TierKey, "free">);
  if (!priceId) {
    return NextResponse.json({ error: `price ID for ${tier} not configured` }, { status: 500 });
  }

  const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? "https://aethersystems.net";
  const stripe = requireStripe();

  try {
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: `${appUrl}/success?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${appUrl}/canceled`,
      allow_promotion_codes: true,
    });
    return NextResponse.json({ url: session.url });
  } catch (e) {
    console.error("checkout session create failed:", e);
    return NextResponse.json({ error: "could not create checkout session" }, { status: 500 });
  }
}
