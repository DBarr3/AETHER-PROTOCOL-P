// Free-tier signup: email-only, no Stripe.
// Rate-limited by IP (3/hour) and blocks disposable email domains.
// Emits PostHog signup_completed server-side.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import {
  generateLicenseKey,
  sendWelcomeEmail,
  captureServerEvent,
  isValidEmail,
  isDisposableEmail,
} from "../_shared/license.ts";

const resendKey = Deno.env.get("RESEND_API_KEY") ?? "";
const appUrl = Deno.env.get("APP_URL") ?? "https://aethersystems.net";
const fromEmail = Deno.env.get("FROM_EMAIL") ?? "no-reply@aethersystems.net";
const posthogKey = Deno.env.get("POSTHOG_KEY") ?? "";
const posthogHost = Deno.env.get("POSTHOG_HOST") ?? "https://us.i.posthog.com";
const allowedVercelOrigin = Deno.env.get("ALLOWED_ORIGIN_VERCEL") ?? "";
const allowLocalhost = Deno.env.get("ALLOW_LOCALHOST") === "true";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
  { auth: { persistSession: false } },
);

const STATIC_ALLOWED = [
  "https://aethersystems.net",
  "https://www.aethersystems.net",
];

function resolveOrigin(reqOrigin: string | null): string | null {
  if (!reqOrigin) return null;
  if (STATIC_ALLOWED.includes(reqOrigin)) return reqOrigin;
  if (allowedVercelOrigin && reqOrigin === allowedVercelOrigin) return reqOrigin;
  if (allowLocalhost && /^http:\/\/localhost(:\d+)?$/.test(reqOrigin)) return reqOrigin;
  return null;
}

function corsHeaders(origin: string | null): Record<string, string> {
  const base: Record<string, string> = {
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
  if (origin) base["Access-Control-Allow-Origin"] = origin;
  return base;
}

function json(status: number, body: unknown, origin: string | null) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders(origin) },
  });
}

function clientIp(req: Request): string {
  const fwd = req.headers.get("x-forwarded-for");
  if (fwd) return fwd.split(",")[0].trim();
  return req.headers.get("x-real-ip") ?? "unknown";
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin");
  const allowedOrigin = resolveOrigin(origin);

  if (req.method === "OPTIONS") {
    if (!allowedOrigin) {
      return new Response("origin not allowed", { status: 403 });
    }
    return new Response(null, { status: 200, headers: corsHeaders(allowedOrigin) });
  }

  if (req.method !== "POST") {
    return json(405, { error: "method not allowed" }, allowedOrigin);
  }

  let body: { email?: string };
  try {
    body = await req.json();
  } catch {
    return json(400, { error: "invalid JSON" }, allowedOrigin);
  }

  const email = (body.email ?? "").trim().toLowerCase();
  if (!isValidEmail(email)) {
    return json(400, { error: "invalid email" }, allowedOrigin);
  }
  if (isDisposableEmail(email)) {
    return json(400, { error: "disposable email addresses are not accepted" }, allowedOrigin);
  }

  // Rate limit: 3/hour/IP
  const ip = clientIp(req);
  const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
  const { count, error: countErr } = await supabase
    .from("signup_attempts")
    .select("id", { count: "exact", head: true })
    .eq("ip", ip)
    .gte("created_at", oneHourAgo);
  if (countErr) {
    console.error("rate-limit query failed:", countErr);
    // Fail open but log — a broken query shouldn't deny legit users.
  }
  if ((count ?? 0) >= 3) {
    return json(429, { error: "too many signups — please try again in an hour" }, allowedOrigin);
  }
  await supabase.from("signup_attempts").insert({ ip });

  // Check if email already exists — if so, don't downgrade paid tiers.
  const { data: existing } = await supabase
    .from("users")
    .select("tier, license_key")
    .eq("email", email)
    .maybeSingle();

  let licenseKey: string;
  let effectiveTier: string;

  if (existing && existing.tier !== "free" && existing.license_key) {
    // Paid user signing up for "free" — return their existing license without
    // changing tier, without re-emailing, and without firing a misleading
    // signup_completed event. Log for visibility.
    licenseKey = existing.license_key;
    effectiveTier = existing.tier;
    console.info("existing paid user pinged free-signup; skipping email + event:", email);
  } else {
    licenseKey = existing?.license_key ?? generateLicenseKey();
    effectiveTier = "free";
    const { error: upsertErr } = await supabase.from("users").upsert(
      {
        email,
        tier: "free",
        license_key: licenseKey,
        subscription_status: "active",
      },
      { onConflict: "email" },
    );
    if (upsertErr) {
      console.error("users upsert failed:", upsertErr);
      return json(500, { error: "internal error" }, allowedOrigin);
    }

    await sendWelcomeEmail(email, licenseKey, effectiveTier, { fromEmail, resendKey, appUrl });
    await captureServerEvent({
      posthogKey,
      posthogHost,
      distinctId: email,
      event: "signup_completed",
      properties: { tier: effectiveTier, method: "email" },
    });
  }

  return json(200, { ok: true }, allowedOrigin);
});
