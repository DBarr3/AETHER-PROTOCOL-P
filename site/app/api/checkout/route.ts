import { NextResponse } from "next/server";
import { requireStripe } from "@/lib/stripe";
import { priceIdForTier, type TierKey } from "@/lib/tiers";
import { captureServerEvent } from "@/lib/posthog-server";

export const runtime = "nodejs";

// Static error-code enum for checkout_failed. NEVER pass a raw
// Stripe exception message through PostHog — map to one of these
// stable codes first so dashboards stay clean and attacker-shaped
// strings can't land in properties.
type CheckoutErrorCode =
  | "invalid_json"
  | "invalid_tier"
  | "price_not_configured"
  | "stripe_error";

// DistinctId used for anonymous checkout — the checkout route does
// NOT authenticate users (the session is created pre-signup), so we
// have no UUID to attribute the event to. requestId is the correlator
// we pass through as a property; distinctId of "anonymous" keeps the
// funnel intact in PostHog.
const ANON_DISTINCT = "anonymous";

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

  // Fire "checkout_failed" with a pre-mapped enum code (never a raw
  // Stripe error string or exception message).
  const emitFailed = (tierForEvent: string | null, code: CheckoutErrorCode): void => {
    void captureServerEvent(ANON_DISTINCT, "checkout_failed", {
      tier: tierForEvent,
      error_code: code,
      requestId,
    });
  };

  let body: { tier?: string };
  try {
    body = await req.json();
  } catch {
    log(400, { error: "invalid_json" });
    emitFailed(null, "invalid_json");
    return NextResponse.json({ error: "invalid JSON" }, { status: 400, headers });
  }

  const tier = body.tier as TierKey | undefined;
  if (!tier || !PAID_TIERS.has(tier)) {
    log(400, { error: "invalid_tier" });
    // `tier` may be an attacker-supplied string here; do NOT pass the
    // raw value to PostHog. Pass null — the error_code tells the
    // dashboard which failure mode this was.
    emitFailed(null, "invalid_tier");
    return NextResponse.json({ error: "invalid tier" }, { status: 400, headers });
  }

  // Past this point `tier` is a PAID_TIERS member — safe to emit.
  void captureServerEvent(ANON_DISTINCT, "checkout_started", {
    tier,
    requestId,
  });

  const priceId = priceIdForTier(tier as Exclude<TierKey, "free">);
  if (!priceId) {
    log(500, { error: "price_not_configured", tier });
    emitFailed(tier, "price_not_configured");
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
    // Only the first 8 chars of the Stripe session id — never the
    // full id (treat Stripe ids as credentials for PII safety).
    void captureServerEvent(ANON_DISTINCT, "checkout_completed", {
      tier,
      latency_ms: Date.now() - startMs,
      session_id_prefix: session.id.slice(0, 8),
      requestId,
    });
    return NextResponse.json({ url: session.url }, { headers });
  } catch (e) {
    console.error("checkout session create failed:", e);
    log(500, { error: "stripe_error", tier });
    emitFailed(tier, "stripe_error");
    return NextResponse.json({ error: "could not create checkout session" }, { status: 500, headers });
  }
}
