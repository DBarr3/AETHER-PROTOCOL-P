// AetherCloud billing webhook.
// Receives Stripe events, writes to public.users, emails a license key via Resend.
//
// Deploy:  supabase functions deploy stripe-webhook --no-verify-jwt
// Secrets: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, RESEND_API_KEY,
//          SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, APP_URL, FROM_EMAIL,
//          PRICE_SOLO, PRICE_TEAM, PRICE_PRO

import Stripe from "https://esm.sh/stripe@14?target=deno";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY") ?? "", {
  apiVersion: "2024-06-20",
  httpClient: Stripe.createFetchHttpClient(),
});

const webhookSecret = Deno.env.get("STRIPE_WEBHOOK_SECRET") ?? "";
const resendKey = Deno.env.get("RESEND_API_KEY") ?? "";
const appUrl = Deno.env.get("APP_URL") ?? "https://aethersystems.net";
const fromEmail = Deno.env.get("FROM_EMAIL") ?? "no-reply@aethersystems.net";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
  { auth: { persistSession: false } },
);

const PRICE_TO_TIER: Record<string, "solo" | "team" | "pro"> = {
  [Deno.env.get("PRICE_SOLO") ?? ""]: "solo",
  [Deno.env.get("PRICE_TEAM") ?? ""]: "team",
  [Deno.env.get("PRICE_PRO") ?? ""]: "pro",
};

function tierForPrice(priceId: string | null | undefined): "solo" | "team" | "pro" | null {
  if (!priceId) return null;
  return PRICE_TO_TIER[priceId] ?? null;
}

// AETH-CLD-XXXX-XXXX-XXXX — matches license_client.py:23
function generateLicenseKey(): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  const chars = Array.from(bytes, (b) => alphabet[b % alphabet.length]);
  const g1 = chars.slice(0, 4).join("");
  const g2 = chars.slice(4, 8).join("");
  const g3 = chars.slice(8, 12).join("");
  return `AETH-CLD-${g1}-${g2}-${g3}`;
}

async function sendWelcomeEmail(to: string, licenseKey: string, tier: string) {
  if (!resendKey) {
    console.warn("RESEND_API_KEY not set, skipping email");
    return;
  }
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${resendKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: fromEmail,
      to,
      subject: "Welcome to AetherCloud — your license key",
      html: `
        <p>Thanks for subscribing to AetherCloud (<strong>${tier}</strong> tier).</p>
        <p>Your license key:</p>
        <p style="font-family:monospace;font-size:16px;padding:12px;background:#f4f4f4;border-radius:4px">${licenseKey}</p>
        <p>Paste this into the AetherCloud desktop app to activate, or visit <a href="${appUrl}">${appUrl}</a>.</p>
        <p>— Aether Systems</p>
      `,
    }),
  });
  if (!res.ok) {
    console.error("Resend failed:", res.status, await res.text());
  }
}

async function handleCheckoutCompleted(session: Stripe.Checkout.Session) {
  const full = await stripe.checkout.sessions.retrieve(session.id, {
    expand: ["line_items", "customer", "subscription"],
  });
  const email = full.customer_details?.email ?? full.customer_email;
  if (!email) {
    console.error("checkout.session.completed has no email");
    return;
  }
  const priceId = full.line_items?.data?.[0]?.price?.id ?? null;
  const tier = tierForPrice(priceId) ?? "solo";
  const customerId = typeof full.customer === "string" ? full.customer : full.customer?.id ?? null;
  const subscriptionId = typeof full.subscription === "string"
    ? full.subscription
    : full.subscription?.id ?? null;

  const licenseKey = generateLicenseKey();

  const { error } = await supabase.from("users").upsert(
    {
      email,
      stripe_customer_id: customerId,
      stripe_subscription_id: subscriptionId,
      tier,
      license_key: licenseKey,
      subscription_status: "active",
    },
    { onConflict: "email" },
  );
  if (error) {
    console.error("users upsert failed:", error);
    return;
  }

  await sendWelcomeEmail(email, licenseKey, tier);
}

async function handleSubscriptionUpdated(sub: Stripe.Subscription) {
  const priceId = sub.items.data[0]?.price?.id ?? null;
  const tier = tierForPrice(priceId);
  const customerId = typeof sub.customer === "string" ? sub.customer : sub.customer.id;
  const periodEnd = sub.current_period_end
    ? new Date(sub.current_period_end * 1000).toISOString()
    : null;

  const update: Record<string, unknown> = {
    subscription_status: sub.status,
    current_period_end: periodEnd,
    stripe_subscription_id: sub.id,
  };
  if (tier) update.tier = tier;

  const { error } = await supabase
    .from("users")
    .update(update)
    .eq("stripe_customer_id", customerId);
  if (error) console.error("subscription.updated failed:", error);
}

async function handleSubscriptionDeleted(sub: Stripe.Subscription) {
  const customerId = typeof sub.customer === "string" ? sub.customer : sub.customer.id;
  const { error } = await supabase
    .from("users")
    .update({ subscription_status: "canceled" })
    .eq("stripe_customer_id", customerId);
  if (error) console.error("subscription.deleted failed:", error);
}

async function handleInvoicePaymentFailed(invoice: Stripe.Invoice) {
  const customerId = typeof invoice.customer === "string"
    ? invoice.customer
    : invoice.customer?.id;
  if (!customerId) return;
  const { error } = await supabase
    .from("users")
    .update({ subscription_status: "past_due" })
    .eq("stripe_customer_id", customerId);
  if (error) console.error("invoice.payment_failed failed:", error);
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }
  const signature = req.headers.get("stripe-signature");
  if (!signature) {
    return new Response("missing stripe-signature", { status: 400 });
  }
  const body = await req.text();

  let event: Stripe.Event;
  try {
    event = await stripe.webhooks.constructEventAsync(body, signature, webhookSecret);
  } catch (err) {
    console.error("signature verification failed:", (err as Error).message);
    return new Response(`signature verification failed: ${(err as Error).message}`, {
      status: 400,
    });
  }

  try {
    switch (event.type) {
      case "checkout.session.completed":
        await handleCheckoutCompleted(event.data.object as Stripe.Checkout.Session);
        break;
      case "customer.subscription.updated":
        await handleSubscriptionUpdated(event.data.object as Stripe.Subscription);
        break;
      case "customer.subscription.deleted":
        await handleSubscriptionDeleted(event.data.object as Stripe.Subscription);
        break;
      case "invoice.payment_failed":
        await handleInvoicePaymentFailed(event.data.object as Stripe.Invoice);
        break;
      default:
        console.log("ignoring event:", event.type);
    }
  } catch (err) {
    console.error("handler error for", event.type, err);
    return new Response("handler error", { status: 500 });
  }

  return new Response(JSON.stringify({ received: true }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
