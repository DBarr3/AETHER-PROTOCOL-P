// AetherCloud billing webhook.
// Verifies Stripe signature, writes to public.users, sends welcome email,
// emits PostHog server-side events for revenue tracking.

import Stripe from "https://esm.sh/stripe@14?target=deno";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import {
  generateLicenseKey,
  sendWelcomeEmail,
  captureServerEvent,
} from "../_shared/license.ts";

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY") ?? "", {
  apiVersion: "2024-06-20",
  httpClient: Stripe.createFetchHttpClient(),
});

const webhookSecretLive = Deno.env.get("STRIPE_WEBHOOK_SECRET") ?? "";
const webhookSecretTest = Deno.env.get("STRIPE_WEBHOOK_SECRET_TEST") ?? "";
const resendKey = Deno.env.get("RESEND_API_KEY") ?? "";
const appUrl = Deno.env.get("APP_URL") ?? "https://aethersystems.net";
const fromEmail = Deno.env.get("FROM_EMAIL") ?? "no-reply@aethersystems.net";
const posthogKey = Deno.env.get("POSTHOG_KEY") ?? "";
const posthogHost = Deno.env.get("POSTHOG_HOST") ?? "https://us.i.posthog.com";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL") ?? "",
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
  { auth: { persistSession: false } },
);

// Free tier is handled by the free-signup function, never by this webhook.
const PRICE_TO_TIER: Record<string, "solo" | "pro" | "team"> = {
  [Deno.env.get("PRICE_SOLO") ?? ""]: "solo",
  [Deno.env.get("PRICE_PRO") ?? ""]: "pro",
  [Deno.env.get("PRICE_TEAM") ?? ""]: "team",
};

function tierForPrice(priceId: string | null | undefined): "solo" | "pro" | "team" | null {
  if (!priceId) return null;
  return PRICE_TO_TIER[priceId] ?? null;
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
  const tier = tierForPrice(priceId);
  if (!tier) {
    console.error("unknown price_id in checkout.session.completed:", priceId, "— skipping upsert");
    return;
  }
  const customerId = typeof full.customer === "string" ? full.customer : full.customer?.id ?? null;
  const subscriptionId = typeof full.subscription === "string"
    ? full.subscription
    : full.subscription?.id ?? null;
  const mrr = (full.amount_total ?? 0) / 100;

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

  await sendWelcomeEmail(email, licenseKey, tier, { fromEmail, resendKey, appUrl });
  await captureServerEvent({
    posthogKey,
    posthogHost,
    distinctId: email,
    event: "checkout_completed",
    properties: { tier, price_id: priceId ?? "unknown", mrr },
  });
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
  // No PostHog event for tier changes in v1.
}

async function handleSubscriptionDeleted(sub: Stripe.Subscription) {
  const customerId = typeof sub.customer === "string" ? sub.customer : sub.customer.id;

  // Fetch the email so we can use it as distinctId in PostHog.
  const { data: existing } = await supabase
    .from("users")
    .select("email")
    .eq("stripe_customer_id", customerId)
    .maybeSingle();

  const { error } = await supabase
    .from("users")
    .update({ subscription_status: "canceled" })
    .eq("stripe_customer_id", customerId);
  if (error) console.error("subscription.deleted failed:", error);

  if (existing?.email) {
    await captureServerEvent({
      posthogKey,
      posthogHost,
      distinctId: existing.email,
      event: "subscription_canceled",
      properties: { stripe_customer_id: customerId },
    });
  }
}

async function handleInvoicePaymentFailed(invoice: Stripe.Invoice) {
  const customerId = typeof invoice.customer === "string"
    ? invoice.customer
    : invoice.customer?.id;
  if (!customerId) return;

  const { data: existing } = await supabase
    .from("users")
    .select("email")
    .eq("stripe_customer_id", customerId)
    .maybeSingle();

  const { error } = await supabase
    .from("users")
    .update({ subscription_status: "past_due" })
    .eq("stripe_customer_id", customerId);
  if (error) console.error("invoice.payment_failed failed:", error);

  if (existing?.email) {
    await captureServerEvent({
      posthogKey,
      posthogHost,
      distinctId: existing.email,
      event: "payment_failed",
      properties: {
        stripe_customer_id: customerId,
        attempt_count: invoice.attempt_count ?? null,
      },
    });
  }
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

  // Peek at event.livemode (unverified JSON) to pick the signing secret.
  // Safe: the chosen secret still has to verify the signature, so an attacker
  // cannot forge a valid event by spoofing livemode.
  let livemode: boolean;
  try {
    const peeked = JSON.parse(body) as { livemode?: unknown };
    if (typeof peeked.livemode !== "boolean") {
      return new Response("missing or invalid livemode", { status: 400 });
    }
    livemode = peeked.livemode;
  } catch (_err) {
    return new Response("invalid json body", { status: 400 });
  }

  const webhookSecret = livemode ? webhookSecretLive : webhookSecretTest;
  if (!webhookSecret) {
    const errorCode = livemode
      ? "webhook_secret_missing_for_mode_live"
      : "webhook_secret_missing_for_mode_test";
    console.error(errorCode);
    return new Response(JSON.stringify({ error: errorCode }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

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
