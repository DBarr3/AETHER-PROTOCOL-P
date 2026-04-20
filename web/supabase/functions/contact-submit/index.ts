import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL     = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SLACK_WEBHOOK    = Deno.env.get("SLACK_WEBHOOK_URL") ?? "";
const DAILY_SALT       = Deno.env.get("DAILY_SALT") ?? new Date().toISOString().slice(0, 10);

const ALLOWED_ORIGINS = new Set([
  "https://aethersecurity.io",
  "https://www.aethersecurity.io",
  "http://localhost:5173",
]);

const ALLOWED_INTENTS  = new Set(["sales","support","security","press","beta","careers","general"]);
const ALLOWED_PRODUCTS = new Set(["aether_security","aether_protocol","aether_cloud","site_wide"]);

async function sha256(s: string) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
}

serve(async (req) => {
  const origin = req.headers.get("origin") ?? "";
  const cors = {
    "Access-Control-Allow-Origin": ALLOWED_ORIGINS.has(origin) ? origin : "",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type",
    "Vary": "Origin",
  };

  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST")
    return new Response("method not allowed", { status: 405, headers: cors });

  let body: Record<string, unknown>;
  try { body = await req.json(); }
  catch { return new Response("bad json", { status: 400, headers: cors }); }

  // Honeypot — silently accept + drop
  if (typeof body.honeypot === "string" && body.honeypot.length > 0) {
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: cors });
  }

  const name    = String(body.name ?? "").trim();
  const email   = String(body.email ?? "").trim();
  const message = String(body.message ?? "").trim();
  const intent  = String(body.intent ?? "general");
  const product = String(body.product ?? "site_wide");

  if (!name || name.length > 120)                       return fail("name", 422);
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email))       return fail("email", 422);
  if (message.length < 10 || message.length > 4000)      return fail("message", 422);
  if (!ALLOWED_INTENTS.has(intent))                      return fail("intent", 422);
  if (!ALLOWED_PRODUCTS.has(product))                    return fail("product", 422);

  // Hash IP with daily-rotating salt — rate limit without storing PII
  const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "0.0.0.0";
  const ipHash = await sha256(ip + "|" + DAILY_SALT);

  const admin = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, { auth: { persistSession: false } });

  // Rate limit: max 5 per IP per day
  const { count } = await admin
    .from("contact_submissions")
    .select("*", { count: "exact", head: true })
    .eq("ip_hash", ipHash)
    .gte("created_at", new Date(Date.now() - 24 * 3600 * 1000).toISOString());
  if ((count ?? 0) >= 5) return fail("rate_limited", 429);

  const { data, error } = await admin
    .from("contact_submissions")
    .insert({
      intent, product, name, email,
      company:     body.company ? String(body.company).slice(0, 160) : null,
      role:        body.role    ? String(body.role).slice(0, 120)    : null,
      message,
      source_path: body.source_path ? String(body.source_path).slice(0, 200) : null,
      source_cta:  body.source_cta  ? String(body.source_cta).slice(0, 120)  : null,
      utm:         (body.utm && typeof body.utm === "object") ? body.utm : {},
      user_agent:  req.headers.get("user-agent")?.slice(0, 500) ?? null,
      ip_hash:     ipHash,
    })
    .select("id")
    .single();

  if (error) return fail("db_error", 500);

  // Slack notification — fire-and-forget
  if (SLACK_WEBHOOK) {
    queueMicrotask(async () => {
      try {
        await fetch(SLACK_WEBHOOK, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            text: `New *${intent}* lead on *${product}* from ${name} <${email}>\n> ${message.slice(0, 300)}`,
          }),
        });
      } catch { /* swallow */ }
    });
  }

  return new Response(JSON.stringify({ ok: true, id: data.id }), {
    status: 200, headers: { ...cors, "content-type": "application/json" },
  });

  function fail(reason: string, code: number) {
    return new Response(JSON.stringify({ ok: false, error: reason }),
      { status: code, headers: { ...cors, "content-type": "application/json" } });
  }
});
