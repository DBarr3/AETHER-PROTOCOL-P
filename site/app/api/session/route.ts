import { NextResponse } from "next/server";
import { requireStripe } from "@/lib/stripe";
import { captureServerEvent } from "@/lib/posthog-server";

export const runtime = "nodejs";

// Static error-code enum for session_retrieve_failed. NEVER pass the
// raw Stripe exception string through PostHog.
type SessionErrorCode =
  | "missing_id"
  | "invalid_id_format"
  | "stripe_lookup_failed";

const ANON_DISTINCT = "anonymous";

/**
 * GET /api/session?id=cs_test_...
 *
 * Returns a redacted summary of a Stripe Checkout session so the
 * marketing site's /success page can render a personalized welcome
 * ("Welcome to Solo, {email}") without ever exposing the raw Stripe
 * session object to the client.
 *
 * This is a *read-only* passthrough. Fields returned:
 *   - status:   "complete" | "open" | "expired"
 *   - tier:     derived from the subscription's price nickname/metadata
 *   - email:    customer email if already collected
 *
 * Anything Stripe returns beyond these fields is intentionally dropped.
 */

const ALLOWED_ORIGINS = new Set([
  "https://aethersystems.net",
  "https://www.aethersystems.net",
  "https://aethersystems-web.vercel.app",
  "http://localhost:5173",
  "http://localhost:4173",
  "http://127.0.0.1:5173",
]);

function corsHeaders(req: Request): Record<string, string> {
  const origin = req.headers.get("origin") || "";
  const allow = ALLOWED_ORIGINS.has(origin) ? origin : "https://aethersystems.net";
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
  };
}

export async function OPTIONS(req: Request) {
  return new NextResponse(null, { status: 204, headers: corsHeaders(req) });
}

export async function GET(req: Request) {
  const requestId = crypto.randomUUID();
  const startMs = Date.now();
  const headers = corsHeaders(req);

  function log(status: number, extra?: Record<string, unknown>) {
    console.log(JSON.stringify({ requestId, route: "GET /api/session", status, latency_ms: Date.now() - startMs, ...extra }));
  }

  const emitFailed = (code: SessionErrorCode): void => {
    void captureServerEvent(ANON_DISTINCT, "session_retrieve_failed", {
      error_code: code,
      requestId,
    });
  };

  const url = new URL(req.url);
  const id = url.searchParams.get("id");
  if (!id) {
    log(400, { error: "missing_id" });
    emitFailed("missing_id");
    return NextResponse.json({ error: "missing id" }, { status: 400, headers });
  }
  // Defensive: Stripe session IDs start with "cs_". Reject anything else
  // to avoid accidentally exposing a lookup API for arbitrary resource ids.
  if (!id.startsWith("cs_")) {
    log(400, { error: "invalid_id_format" });
    emitFailed("invalid_id_format");
    return NextResponse.json({ error: "invalid id" }, { status: 400, headers });
  }

  try {
    const stripe = requireStripe();
    const session = await stripe.checkout.sessions.retrieve(id, {
      expand: ["line_items.data.price"],
    });

    // Pull the tier label from the expanded line item, falling back to metadata.
    const firstItem = session.line_items?.data?.[0];
    const price = firstItem?.price;
    const tier =
      price?.nickname ||
      price?.lookup_key ||
      (session.metadata?.tier as string | undefined) ||
      null;

    log(200, { session_status: session.status, tier: tier ?? "unknown" });
    // Emit only the 8-char prefix — NEVER the full Stripe session id.
    void captureServerEvent(ANON_DISTINCT, "session_retrieved", {
      session_id_prefix: id.slice(0, 8),
      latency_ms: Date.now() - startMs,
      requestId,
    });
    return NextResponse.json(
      {
        status: session.status,
        tier,
        email: session.customer_details?.email ?? null,
      },
      { headers }
    );
  } catch (e: unknown) {
    console.error("session retrieve failed:", e);
    log(404, { error: "stripe_lookup_failed" });
    emitFailed("stripe_lookup_failed");
    // Don't leak Stripe error internals to the client.
    return NextResponse.json({ error: "session lookup failed" }, { status: 404, headers });
  }
}
