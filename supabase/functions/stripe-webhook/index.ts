// Stripe webhook handler for AetherCloud licenses.
//
// Stripe Dashboard → Webhooks → add endpoint:
//   https://cjjcdwrnpzwlvradbros.supabase.co/functions/v1/stripe-webhook
// then copy the signing secret:
//   supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_...
//
// Events handled:
//   checkout.session.completed        → create or activate a license
//   customer.subscription.updated     → sync license status + expiry
//   customer.subscription.deleted     → revoke license
//   invoice.payment_failed            → mark license suspended
//   invoice.payment_succeeded         → renew license
//
// All handlers are idempotent — Stripe retries on non-2xx responses.

import { stripe, webhookSecret, priceToPlan } from "../_shared/stripe.ts";
import { serviceClient } from "../_shared/supabase.ts";
import { corsHeaders, jsonResponse, handleOptions } from "../_shared/cors.ts";
import {
  generateLicenseKey,
  hashLicenseKey,
  prefixFor,
} from "../_shared/license-key.ts";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return handleOptions();
  if (req.method !== "POST") {
    return jsonResponse({ error: "method_not_allowed" }, { status: 405 });
  }

  const signature = req.headers.get("stripe-signature");
  if (!signature) {
    return jsonResponse({ error: "missing_signature" }, { status: 400 });
  }

  const body = await req.text();

  let event;
  try {
    event = await stripe().webhooks.constructEventAsync(
      body,
      signature,
      webhookSecret(),
    );
  } catch (err) {
    console.error("[stripe-webhook] signature verification failed:", err);
    return jsonResponse(
      { error: "invalid_signature", message: (err as Error).message },
      { status: 400 },
    );
  }

  const sb = serviceClient();

  try {
    switch (event.type) {
      case "checkout.session.completed":
        await handleCheckoutCompleted(sb, event.data.object as any);
        break;

      case "customer.subscription.created":
      case "customer.subscription.updated":
        await handleSubscriptionChange(sb, event.data.object as any);
        break;

      case "customer.subscription.deleted":
        await handleSubscriptionDeleted(sb, event.data.object as any);
        break;

      case "invoice.payment_failed":
        await handleInvoicePaymentFailed(sb, event.data.object as any);
        break;

      case "invoice.payment_succeeded":
        await handleInvoicePaymentSucceeded(sb, event.data.object as any);
        break;

      default:
        console.log("[stripe-webhook] ignoring event:", event.type);
    }
  } catch (err) {
    console.error(`[stripe-webhook] handler error (${event.type}):`, err);
    return jsonResponse(
      { error: "handler_failed", message: (err as Error).message },
      { status: 500 },
    );
  }

  return jsonResponse({ received: true, type: event.type });
});

// ═══════════════════════════════════════════════════════════

async function findOrCreateProfile(
  sb: any,
  email: string,
  stripeCustomerId: string,
): Promise<string> {
  // 1. Try to find existing profile by stripe_customer_id
  const { data: byCustomer } = await sb
    .from("profiles")
    .select("id")
    .eq("stripe_customer_id", stripeCustomerId)
    .maybeSingle();

  if (byCustomer) return byCustomer.id;

  // 2. Try to find by email (user may have signed up first via auth.users)
  const { data: byEmail } = await sb
    .from("profiles")
    .select("id")
    .ilike("email", email)
    .maybeSingle();

  if (byEmail) {
    await sb
      .from("profiles")
      .update({ stripe_customer_id: stripeCustomerId })
      .eq("id", byEmail.id);
    return byEmail.id;
  }

  // 3. Invite via auth — creates auth.users row, trigger creates profile
  const { data: invited, error } = await sb.auth.admin.inviteUserByEmail(email);
  if (error || !invited?.user?.id) {
    throw new Error(
      `Failed to invite user ${email}: ${error?.message ?? "no user returned"}`,
    );
  }

  await sb
    .from("profiles")
    .update({ stripe_customer_id: stripeCustomerId })
    .eq("id", invited.user.id);

  return invited.user.id;
}

async function handleCheckoutCompleted(sb: any, session: any) {
  if (session.mode !== "subscription") {
    console.log("[stripe-webhook] ignoring non-subscription checkout");
    return;
  }

  const subscription = await stripe().subscriptions.retrieve(
    session.subscription as string,
    { expand: ["items.data.price"] },
  );

  const email = session.customer_details?.email ?? session.customer_email;
  if (!email) throw new Error("checkout.session missing email");

  const userId = await findOrCreateProfile(
    sb,
    email,
    session.customer as string,
  );

  await upsertLicenseFromSubscription(sb, userId, subscription);
}

async function handleSubscriptionChange(sb: any, subscription: any) {
  const { data: existing } = await sb
    .from("licenses")
    .select("user_id")
    .eq("stripe_subscription_id", subscription.id)
    .maybeSingle();

  if (!existing) {
    console.log(
      "[stripe-webhook] subscription update for unknown sub — skipping",
      subscription.id,
    );
    return;
  }

  await upsertLicenseFromSubscription(sb, existing.user_id, subscription);
}

async function handleSubscriptionDeleted(sb: any, subscription: any) {
  await sb
    .from("licenses")
    .update({
      status: "revoked",
      revoked_at: new Date().toISOString(),
      revoked_reason: "stripe_subscription_deleted",
    })
    .eq("stripe_subscription_id", subscription.id);
}

async function handleInvoicePaymentFailed(sb: any, invoice: any) {
  if (!invoice.subscription) return;
  await sb
    .from("licenses")
    .update({ status: "suspended" })
    .eq("stripe_subscription_id", invoice.subscription);
}

async function handleInvoicePaymentSucceeded(sb: any, invoice: any) {
  if (!invoice.subscription) return;
  await sb
    .from("licenses")
    .update({
      status: "active",
      last_renewed_at: new Date().toISOString(),
    })
    .eq("stripe_subscription_id", invoice.subscription);
}

async function upsertLicenseFromSubscription(
  sb: any,
  userId: string,
  subscription: any,
) {
  const priceId = subscription.items?.data?.[0]?.price?.id;
  const mapped = priceToPlan(priceId);

  if (!mapped) {
    throw new Error(
      `No product/plan mapping for Stripe price ${priceId}. ` +
        `Set STRIPE_PRICE_AETHER_CLOUD_* env vars on the edge function.`,
    );
  }

  const { product, plan } = mapped;
  const expiresAt = subscription.current_period_end
    ? new Date(subscription.current_period_end * 1000).toISOString()
    : null;

  const status = subscription.status === "active" || subscription.status === "trialing"
    ? "active"
    : subscription.status === "past_due" || subscription.status === "unpaid"
      ? "suspended"
      : "revoked";

  // Upsert by stripe_subscription_id
  const { data: existing } = await sb
    .from("licenses")
    .select("id, license_key")
    .eq("stripe_subscription_id", subscription.id)
    .maybeSingle();

  if (existing) {
    await sb
      .from("licenses")
      .update({
        product,
        plan,
        status,
        expires_at: expiresAt,
        stripe_price_id: priceId,
        stripe_customer_id: subscription.customer,
        activated_at: new Date().toISOString(),
      })
      .eq("id", existing.id);
    return existing;
  }

  // New license — generate key
  const licenseKey = generateLicenseKey(prefixFor(product));
  const keyHash = await hashLicenseKey(licenseKey);

  const { data, error } = await sb
    .from("licenses")
    .insert({
      user_id: userId,
      product,
      plan,
      license_key: licenseKey,
      key_hash: keyHash,
      status,
      source: "stripe",
      stripe_customer_id: subscription.customer,
      stripe_subscription_id: subscription.id,
      stripe_price_id: priceId,
      expires_at: expiresAt,
      activated_at: new Date().toISOString(),
    })
    .select()
    .single();

  if (error) throw error;
  return data;
}
