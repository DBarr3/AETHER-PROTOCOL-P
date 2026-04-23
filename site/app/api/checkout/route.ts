import { NextResponse } from "next/server";
import { requireStripe } from "@/lib/stripe";
import { priceIdForTier, type TierKey } from "@/lib/tiers";

export const runtime = "nodejs";

const PAID_TIERS: ReadonlySet<TierKey> = new Set(["solo", "pro", "team"]);

// Origins allowed to call this endpoint cross-origin. The marketing SPA
// (aethersystems.net / vercel preview / local dev) lives on a different
// origin than this Next.js app (expected to deploy at app.aethersystems.net).
// We don't need credentialed CORS (no cookies cross the boundary), just
// the basic preflight + origin allowlist.
const ALLOWED_ORIGINS = new Set([
  "https://aethersystems.net",
  "https://www.aethersystems.net",
  // Vercel preview deploys of the marketing SPA
  "https://aethersystems-web.vercel.app",
  // Local dev
  "http://localhost:5173",
  "http://localhost:4173",
  "http://127.0.0.1:5173",
]);

function corsHeaders(req: Request): Record<string, string> {
  const origin = req.headers.get("origin") || "";
  const allow = ALLOWED_ORIGINS.has(origin) ? origin : "https://aethersystems.net";
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
  };
}

export async function OPTIONS(req: Request) {
  return new NextResponse(null, { status: 204, headers: corsHeaders(req) });
}

export async function POST(req: Request) {
  const requestId = crypto.randomUUID();
  const startMs = Date.now();
  const headers = corsHeaders(req);

  function log(status: number, extra?: Record<string, unknown>) {
    console.log(JSON.stringify({ requestId, route: "POST /api/checkout", status, latency_ms: Date.now() - startMs, ...extra }));
  }

  let body: { tier?: string };
  try {
    body = await req.json();
  } catch {
    log(400, { error: "invalid_json" });
    return NextResponse.json({ error: "invalid JSON" }, { status: 400, headers });
  }

  const tier = body.tier as TierKey | undefined;
  if (!tier || !PAID_TIERS.has(tier)) {
    log(400, { error: "invalid_tier" });
    return NextResponse.json({ error: "invalid tier" }, { status: 400, headers });
  }

  const priceId = priceIdForTier(tier as Exclude<TierKey, "free">);
  if (!priceId) {
    log(500, { error: "price_not_configured", tier });
    return NextResponse.json({ error: `price ID for ${tier} not configured` }, { status: 500, headers });
  }

  // Stripe redirects back into THIS Next.js app's /success and /canceled
  // routes (they live in site/app/success and site/app/canceled). The
  // canonical deployment is app.aethersystems.net, so default there.
  // Override via NEXT_PUBLIC_APP_URL when running locally or on a preview.
  const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? "https://app.aethersystems.net";
  const stripe = requireStripe();

  try {
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      // Include tier hint so the success page can render "Welcome to Solo"
      // immediately, before (or even without) the session lookup.
      success_url: `${appUrl}/success?session_id={CHECKOUT_SESSION_ID}&tier=${tier}`,
      cancel_url: `${appUrl}/canceled`,
      allow_promotion_codes: true,
    });
    log(200, { tier });
    return NextResponse.json({ url: session.url }, { headers });
  } catch (e) {
    console.error("checkout session create failed:", e);
    log(500, { error: "stripe_error", tier });
    return NextResponse.json({ error: "could not create checkout session" }, { status: 500, headers });
  }
}
