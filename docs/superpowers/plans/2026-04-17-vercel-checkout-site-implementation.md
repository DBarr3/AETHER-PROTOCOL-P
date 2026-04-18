# Vercel Checkout Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a 4-tier pricing/checkout site on Vercel that routes Solo/Pro/Team through Stripe Checkout and Free through a rate-limited Supabase edge function, with PostHog analytics and complete integration with the existing `aethercloud/` webhook package.

**Architecture:** Next.js 14 (App Router) + Tailwind at `site/`; new Supabase edge function `free-signup` with CORS, IP rate limit, disposable-email block; shared license helpers at `aethercloud/supabase/functions/_shared/license.ts`; PostHog server-side events via fetch (Deno-compatible) in both webhook functions.

**Tech Stack:** Next.js 14, React 18, TypeScript, Tailwind CSS, Stripe SDK v14, Supabase JS v2, Supabase Edge Functions (Deno), Resend API, PostHog (posthog-js + posthog-node + fetch capture).

**Spec:** `docs/superpowers/specs/2026-04-17-vercel-checkout-site-design.md`

---

## Pre-flight

Existing state of the worktree (branch `claude/modest-galileo-7ce3d1`):
- `aethercloud/` folder created with 6 files but **not yet committed** — contains the original 3-tier design that this plan will correct.
- `docs/superpowers/specs/2026-04-17-vercel-checkout-site-design.md` committed as `d12da3f`.
- Repo root has `lib/posthog.ts`, `lib/track.ts`, `lib/server.ts`, `components/PostHogProvider.tsx` (the "drops" from the user) — these will be copied into `site/` and the originals deleted.

Baseline commit first, then all subsequent modifications produce clean diffs.

---

## File Structure Overview

**Modified files (in `aethercloud/`):**
- `aethercloud/supabase/migrations/20260417_users_billing.sql` — tier CHECK constraint + `signup_attempts` table
- `aethercloud/supabase/functions/stripe-webhook/index.ts` — extract helpers, add PostHog, exclude Free
- `aethercloud/deploy.sh` — real price IDs, new secrets, deploy free-signup
- `aethercloud/DEPLOY_WALKTHROUGH.md` — 3→4 tiers, new secrets
- `aethercloud/VERCEL_ENV_VARS.md` — full rewrite per spec corrections

**New files (in `aethercloud/`):**
- `aethercloud/supabase/functions/_shared/license.ts` — shared helpers (generateLicenseKey, sendWelcomeEmail, captureServerEvent)
- `aethercloud/supabase/functions/_shared/license_test.ts` — unit tests (Deno built-in runner)
- `aethercloud/supabase/functions/free-signup/index.ts` — new function

**New files (in `site/`):**
- Config: `package.json`, `next.config.js`, `tsconfig.json`, `tailwind.config.ts`, `postcss.config.js`, `.env.example`
- App: `app/layout.tsx`, `app/globals.css`, `app/page.tsx`, `app/success/page.tsx`, `app/canceled/page.tsx`, `app/api/checkout/route.ts`
- Components: `components/PostHogProvider.tsx`, `components/PricingCard.tsx`, `components/FreeSignupForm.tsx`
- Lib: `lib/posthog.ts`, `lib/track.ts`, `lib/server.ts`, `lib/stripe.ts`, `lib/tiers.ts`

**Deleted files (after copy into `site/`):**
- `lib/posthog.ts`, `lib/track.ts`, `lib/server.ts`, `components/PostHogProvider.tsx` (repo-root drops)

---

## Task 0: Commit aethercloud/ baseline

**Rationale:** The aethercloud/ folder exists in the working tree but hasn't been committed. Committing it as-is produces clean diffs for all subsequent modifications.

**Files:**
- Add: all files under `aethercloud/`

- [ ] **Step 1: Verify state**

```bash
cd /path/to/worktree
git status
```

Expected: `aethercloud/` listed under "Untracked files", plus possibly the repo-root `lib/` and `components/`.

- [ ] **Step 2: Stage and commit aethercloud/ only**

```bash
git add aethercloud/
git commit -m "feat(aethercloud): initial billing deployment package (3-tier baseline)

Stripe webhook + Supabase migration + Resend welcome email scaffolding.
Will be corrected in follow-up commits to support 4 tiers, PostHog, and
the Free signup flow.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 3: Verify**

```bash
git log -1 --oneline
git status
```

Expected: new commit visible; `aethercloud/` no longer listed as untracked. Repo-root `lib/` and `components/` may still be untracked — that's fine, they're handled in Task 10.

---

## Task 1: Migration update (4-tier CHECK + signup_attempts table)

**Files:**
- Modify: `aethercloud/supabase/migrations/20260417_users_billing.sql`

- [ ] **Step 1: Append to migration file**

Append after the existing trigger definition (before the `enable row level security` line is fine since the trigger is idempotent and the new ALTER statements are too). Open `aethercloud/supabase/migrations/20260417_users_billing.sql` and add at the bottom:

```sql

-- ───────────────────────────────────────────────────────────
-- Added 2026-04-17: 4-tier support + rate-limit table
-- ───────────────────────────────────────────────────────────

-- Allow 'free' tier (original CHECK was 'solo','team','pro')
alter table public.users drop constraint if exists users_tier_check;
alter table public.users add constraint users_tier_check
  check (tier in ('free','solo','pro','team'));
alter table public.users alter column tier set default 'free';

-- Signup attempts (IP rate limit for free-signup)
create table if not exists public.signup_attempts (
  id uuid primary key default gen_random_uuid(),
  ip text not null,
  created_at timestamptz not null default now()
);
create index if not exists signup_attempts_ip_created_idx
  on public.signup_attempts(ip, created_at desc);

alter table public.signup_attempts enable row level security;
-- Service role bypasses RLS; no user-facing policies.
```

- [ ] **Step 2: Lint the SQL (optional — relies on locally installed postgres)**

If `psql` is available locally, dry-run:

```bash
psql --help | head -1  # check installed
# if yes: cat the file and visually verify syntax, or:
# psql -c "$(cat aethercloud/supabase/migrations/20260417_users_billing.sql)" --dry-run  # not supported in psql, skip
```

Otherwise: visual review only. Supabase CLI will validate on `db push`.

- [ ] **Step 3: Commit**

```bash
git add aethercloud/supabase/migrations/20260417_users_billing.sql
git commit -m "fix(migrations): add free tier + signup_attempts rate-limit table

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Create _shared/license.ts

**Files:**
- Create: `aethercloud/supabase/functions/_shared/license.ts`

The `_shared/` directory's underscore prefix is load-bearing: Supabase will not attempt to deploy it as a function, but sibling functions can import from it with `../_shared/license.ts`.

- [ ] **Step 1: Create the file**

```typescript
// Shared helpers used by both stripe-webhook and free-signup functions.
// DO NOT deploy as a function — the leading underscore on the directory
// tells Supabase to skip it.

export function generateLicenseKey(): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  const chars = Array.from(bytes, (b) => alphabet[b % alphabet.length]);
  const g1 = chars.slice(0, 4).join("");
  const g2 = chars.slice(4, 8).join("");
  const g3 = chars.slice(8, 12).join("");
  return `AETH-CLD-${g1}-${g2}-${g3}`;
}

export interface SendEmailOpts {
  fromEmail: string;
  resendKey: string;
  appUrl: string;
}

export async function sendWelcomeEmail(
  to: string,
  licenseKey: string,
  tier: string,
  opts: SendEmailOpts,
): Promise<void> {
  if (!opts.resendKey) {
    console.warn("RESEND_API_KEY not set, skipping email");
    return;
  }
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${opts.resendKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: opts.fromEmail,
      to,
      subject: "Welcome to AetherCloud — your license key",
      html: `
        <p>Thanks for subscribing to AetherCloud (<strong>${tier}</strong> tier).</p>
        <p>Your license key:</p>
        <p style="font-family:monospace;font-size:16px;padding:12px;background:#f4f4f4;border-radius:4px">${licenseKey}</p>
        <p>Paste this into the AetherCloud desktop app to activate, or visit <a href="${opts.appUrl}">${opts.appUrl}</a>.</p>
        <p>— Aether Systems</p>
      `,
    }),
  });
  if (!res.ok) {
    console.error("Resend failed:", res.status, await res.text());
  }
}

export interface CaptureEventOpts {
  posthogKey: string;
  posthogHost: string;
  distinctId: string;
  event: string;
  properties?: Record<string, unknown>;
}

// Fires a server-side PostHog event via fetch.
// Works in Deno runtime where posthog-node does not.
// Never throws — analytics must not break webhooks.
export async function captureServerEvent(opts: CaptureEventOpts): Promise<void> {
  if (!opts.posthogKey) {
    console.warn("POSTHOG_KEY not set, skipping server event");
    return;
  }
  try {
    const url = `${opts.posthogHost.replace(/\/$/, "")}/capture/`;
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: opts.posthogKey,
        event: opts.event,
        distinct_id: opts.distinctId,
        properties: opts.properties ?? {},
        timestamp: new Date().toISOString(),
      }),
    });
    if (!res.ok) {
      console.error("PostHog capture failed:", res.status, await res.text());
    }
  } catch (err) {
    console.error("PostHog capture threw:", err);
  }
}

// Commonly abused throwaway email domains. Hardcoded for speed.
// Extend as needed; not exhaustive.
export const DISPOSABLE_EMAIL_DOMAINS = new Set<string>([
  "mailinator.com", "guerrillamail.com", "guerrillamail.info", "guerrillamail.net",
  "guerrillamail.org", "10minutemail.com", "10minutemail.net", "tempmail.org",
  "tempmail.com", "temp-mail.org", "trashmail.com", "trashmail.net",
  "yopmail.com", "yopmail.net", "yopmail.fr", "throwawaymail.com",
  "throwaway.email", "sharklasers.com", "maildrop.cc", "mintemail.com",
  "fakeinbox.com", "getnada.com", "nada.email", "mohmal.com",
  "tempail.com", "dispostable.com", "emailondeck.com", "mytemp.email",
  "inboxbear.com", "incognitomail.org", "mailnesia.com", "mytrashmail.com",
  "spamgourmet.com", "spamex.com", "spambox.us", "spambog.com",
  "tempmailo.com", "tempinbox.com", "tempmail.ninja", "throwawaymailbox.com",
  "mailcatch.com", "burnermail.io", "mailtemp.info", "email-temp.com",
  "anonaddy.me",
  "mailnull.com", "emailsensei.com", "tempr.email", "tmail.ws",
  "getairmail.com", "mail-temp.com", "discard.email", "mailforspam.com",
  "mvrht.net", "cool.fr.nf", "jetable.fr.nf", "nospam.ze.tc",
  "spam.la", "speed.1s.fr", "oosi.ru",
]);

export function isDisposableEmail(email: string): boolean {
  const at = email.lastIndexOf("@");
  if (at < 0) return false;
  const domain = email.slice(at + 1).toLowerCase().trim();
  return DISPOSABLE_EMAIL_DOMAINS.has(domain);
}

export function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}
```

**Note on allowlist choices:** `proton.me` and `duck.com` are intentionally NOT in this block list. They're privacy-focused but not disposable; paying customers legitimately use them.

- [ ] **Step 2: Commit**

```bash
git add aethercloud/supabase/functions/_shared/license.ts
git commit -m "feat(shared): license/email/posthog helpers for edge functions

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Unit tests for _shared/license.ts

**Files:**
- Create: `aethercloud/supabase/functions/_shared/license_test.ts`

Deno has a built-in test runner — no framework install needed.

- [ ] **Step 1: Write the failing tests**

```typescript
import {
  generateLicenseKey,
  isValidEmail,
  isDisposableEmail,
} from "./license.ts";

Deno.test("generateLicenseKey produces AETH-CLD-XXXX-XXXX-XXXX format", () => {
  const key = generateLicenseKey();
  const re = /^AETH-CLD-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/;
  if (!re.test(key)) throw new Error(`Bad format: ${key}`);
});

Deno.test("generateLicenseKey produces different keys on successive calls", () => {
  const a = generateLicenseKey();
  const b = generateLicenseKey();
  if (a === b) throw new Error("Collision in 2 calls — not random enough");
});

Deno.test("isValidEmail accepts valid addresses", () => {
  for (const e of ["a@b.c", "user@example.com", "first.last+tag@sub.domain.io"]) {
    if (!isValidEmail(e)) throw new Error(`Rejected valid: ${e}`);
  }
});

Deno.test("isValidEmail rejects malformed addresses", () => {
  for (const e of ["", "foo", "foo@", "@bar", "foo bar@baz.com", "foo@bar"]) {
    if (isValidEmail(e)) throw new Error(`Accepted invalid: ${e}`);
  }
});

Deno.test("isDisposableEmail blocks mailinator.com", () => {
  if (!isDisposableEmail("x@mailinator.com")) throw new Error("Should block");
});

Deno.test("isDisposableEmail is case-insensitive on domain", () => {
  if (!isDisposableEmail("x@MAILINATOR.COM")) throw new Error("Should block uppercase");
});

Deno.test("isDisposableEmail allows gmail.com", () => {
  if (isDisposableEmail("x@gmail.com")) throw new Error("Should allow");
});

Deno.test("isDisposableEmail allows proton.me (paid users allowed)", () => {
  if (isDisposableEmail("x@proton.me")) throw new Error("Should allow Proton");
});
```

- [ ] **Step 2: Run and verify they fail (they won't — `_shared/license.ts` already exists). Instead verify they PASS:**

```bash
cd aethercloud/supabase/functions/_shared
deno test --allow-none license_test.ts
```

Expected: `ok | 8 passed | 0 failed`.

If Deno isn't installed: `brew install deno` (macOS) or `iwr https://deno.land/install.ps1 -useb | iex` (Windows). If the user can't install Deno, skip this task and rely on end-to-end verification.

- [ ] **Step 3: Commit**

```bash
git add aethercloud/supabase/functions/_shared/license_test.ts
git commit -m "test(shared): unit tests for license/email helpers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Refactor stripe-webhook to use _shared + add PostHog

**Files:**
- Modify: `aethercloud/supabase/functions/stripe-webhook/index.ts` (full rewrite — see below)

- [ ] **Step 1: Replace the file content**

Replace the entire contents of `aethercloud/supabase/functions/stripe-webhook/index.ts` with:

```typescript
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

const webhookSecret = Deno.env.get("STRIPE_WEBHOOK_SECRET") ?? "";
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
  const tier = tierForPrice(priceId) ?? "solo";
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
```

- [ ] **Step 2: Commit**

```bash
git add aethercloud/supabase/functions/stripe-webhook/index.ts
git commit -m "refactor(stripe-webhook): use _shared helpers, add PostHog, drop free tier

Extracts generateLicenseKey/sendWelcomeEmail/captureServerEvent into
../_shared/license.ts. PRICE_TO_TIER now covers only paid tiers (Free
is handled by the free-signup function). Adds server-side PostHog events
for checkout_completed, subscription_canceled, and payment_failed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Create free-signup edge function

**Files:**
- Create: `aethercloud/supabase/functions/free-signup/index.ts`

- [ ] **Step 1: Create the file**

```typescript
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
    // Paid user signing up for "free" — return their existing license without changing tier.
    licenseKey = existing.license_key;
    effectiveTier = existing.tier;
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
  }

  await sendWelcomeEmail(email, licenseKey, effectiveTier, { fromEmail, resendKey, appUrl });
  await captureServerEvent({
    posthogKey,
    posthogHost,
    distinctId: email,
    event: "signup_completed",
    properties: { tier: effectiveTier, method: "email" },
  });

  return json(200, { ok: true }, allowedOrigin);
});
```

- [ ] **Step 2: Commit**

```bash
git add aethercloud/supabase/functions/free-signup/index.ts
git commit -m "feat(free-signup): new edge function with CORS, rate limit, PostHog

Rate-limited 3/hour/IP via public.signup_attempts. Blocks disposable
email domains. Issues AETH-CLD-* license and sends welcome email
via Resend. Fires PostHog signup_completed server-side. Paid users
signing up for Free return their existing license without downgrade.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Update deploy.sh with real IDs, new secrets, free-signup deploy

**Files:**
- Modify: `aethercloud/deploy.sh` (full rewrite)

- [ ] **Step 1: Replace deploy.sh**

```bash
#!/usr/bin/env bash
# AetherCloud billing — one-shot deploy.
# Fill in the values below, then:  ./deploy.sh
set -euo pipefail

# ─────────────────────────────────────────────────────────────
# Fill these in. All are REQUIRED.
# ─────────────────────────────────────────────────────────────
PROJECT_REF="REPLACE_ME_supabase_project_ref"   # e.g. abcdefghijklmnop
STRIPE_SECRET_KEY="sk_live_REPLACE_ME"
RESEND_API_KEY="re_REPLACE_ME"
SUPABASE_SERVICE_ROLE_KEY="sb_secret_REPLACE_ME"  # Supabase → Settings → API Keys → Secret keys
FROM_EMAIL="no-reply@aethersystems.net"

# Stripe price IDs — already created in Live mode, do not recreate.
PRICE_SOLO="price_1TNKCm3TqWOqdd87AngxY9ks"   # $19/mo
PRICE_PRO="price_1TNKCm3TqWOqdd87vSXEHnVW"    # $49/mo
PRICE_TEAM="price_1TNKCm3TqWOqdd87FJIdQFI1"   # $89/mo
# Free tier's Stripe price exists but isn't used here:
#   price_1TNKCm3TqWOqdd879Ih03NVe  ($0)

# PostHog — project 386803, US cloud.
POSTHOG_KEY="phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR"
POSTHOG_HOST="https://us.i.posthog.com"

# CORS allowlist for free-signup. Set to your Vercel URL after first deploy.
# Can be updated later with: supabase secrets set ALLOWED_ORIGIN_VERCEL=...
ALLOWED_ORIGIN_VERCEL="REPLACE_ME_after_vercel_first_deploy"   # e.g. https://aether-cloud-xxx.vercel.app

APP_URL="https://aethersystems.net"
SUPABASE_URL="https://${PROJECT_REF}.supabase.co"
# ─────────────────────────────────────────────────────────────

guard() {
  local name="$1" value="$2"
  if [[ "$value" == *REPLACE_ME* ]]; then
    echo "error: $name still has a REPLACE_ME placeholder. Edit deploy.sh and fill it in." >&2
    exit 1
  fi
}

guard PROJECT_REF "$PROJECT_REF"
guard STRIPE_SECRET_KEY "$STRIPE_SECRET_KEY"
guard RESEND_API_KEY "$RESEND_API_KEY"
guard SUPABASE_SERVICE_ROLE_KEY "$SUPABASE_SERVICE_ROLE_KEY"
# ALLOWED_ORIGIN_VERCEL intentionally not guarded — first deploy runs before Vercel exists.
# Re-run deploy.sh (or just set the secret manually) after you have the Vercel URL.

if ! command -v supabase >/dev/null 2>&1; then
  echo "error: supabase CLI not found. Install: https://supabase.com/docs/guides/cli" >&2
  exit 1
fi

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "▸ Linking Supabase project ($PROJECT_REF)..."
supabase link --project-ref "$PROJECT_REF" || true

echo "▸ Applying migration (creates public.users + public.signup_attempts)..."
supabase db push

echo "▸ Setting secrets..."
SECRET_ARGS=(
  STRIPE_SECRET_KEY="$STRIPE_SECRET_KEY"
  RESEND_API_KEY="$RESEND_API_KEY"
  SUPABASE_URL="$SUPABASE_URL"
  SUPABASE_SERVICE_ROLE_KEY="$SUPABASE_SERVICE_ROLE_KEY"
  APP_URL="$APP_URL"
  FROM_EMAIL="$FROM_EMAIL"
  PRICE_SOLO="$PRICE_SOLO"
  PRICE_PRO="$PRICE_PRO"
  PRICE_TEAM="$PRICE_TEAM"
  POSTHOG_KEY="$POSTHOG_KEY"
  POSTHOG_HOST="$POSTHOG_HOST"
)
if [[ "$ALLOWED_ORIGIN_VERCEL" != *REPLACE_ME* ]]; then
  SECRET_ARGS+=(ALLOWED_ORIGIN_VERCEL="$ALLOWED_ORIGIN_VERCEL")
fi
supabase secrets set "${SECRET_ARGS[@]}"

echo "▸ Deploying stripe-webhook edge function..."
supabase functions deploy stripe-webhook --no-verify-jwt

echo "▸ Deploying free-signup edge function..."
supabase functions deploy free-signup --no-verify-jwt

WEBHOOK_URL="${SUPABASE_URL}/functions/v1/stripe-webhook"
FREE_SIGNUP_URL="${SUPABASE_URL}/functions/v1/free-signup"

cat <<EOF

─────────────────────────────────────────────────────────────
✓ Deployed.

Stripe webhook URL (register in Stripe dashboard):
  $WEBHOOK_URL

Free signup URL (set as NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL on Vercel):
  $FREE_SIGNUP_URL

Next steps:
  1. Open https://dashboard.stripe.com/webhooks (Live mode).
  2. Add endpoint with the stripe-webhook URL above.
  3. Select events: checkout.session.completed, customer.subscription.updated,
     customer.subscription.deleted, invoice.payment_failed.
  4. Copy the signing secret (whsec_...) and run:
       supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_...
  5. Deploy site/ to Vercel (see site/README.md or the spec) and, after first
     deploy, come back and run:
       supabase secrets set ALLOWED_ORIGIN_VERCEL=https://<your-vercel-url>.vercel.app
─────────────────────────────────────────────────────────────
EOF
```

- [ ] **Step 2: Verify bash syntax**

```bash
bash -n aethercloud/deploy.sh
```

Expected: no output (clean exit).

- [ ] **Step 3: Commit**

```bash
git add aethercloud/deploy.sh
git commit -m "feat(deploy): pre-fill price IDs, add PostHog + CORS secrets, deploy free-signup

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Update DEPLOY_WALKTHROUGH.md and VERCEL_ENV_VARS.md

**Files:**
- Modify: `aethercloud/DEPLOY_WALKTHROUGH.md`
- Modify: `aethercloud/VERCEL_ENV_VARS.md` (full rewrite)

- [ ] **Step 1: Edit DEPLOY_WALKTHROUGH.md — change "three systems" and tier counts**

Open `aethercloud/DEPLOY_WALKTHROUGH.md` and make these edits:

1. In Step 2's `supabase secrets set` example, replace the existing secrets list with:

```bash
supabase secrets set \
  STRIPE_SECRET_KEY=sk_live_REPLACE_ME \
  RESEND_API_KEY=re_REPLACE_ME \
  SUPABASE_URL=https://YOUR-PROJECT-REF.supabase.co \
  SUPABASE_SERVICE_ROLE_KEY=sb_secret_REPLACE_ME \
  APP_URL=https://aethersystems.net \
  FROM_EMAIL=no-reply@aethersystems.net \
  PRICE_SOLO=price_1TNKCm3TqWOqdd87AngxY9ks \
  PRICE_PRO=price_1TNKCm3TqWOqdd87vSXEHnVW \
  PRICE_TEAM=price_1TNKCm3TqWOqdd87FJIdQFI1 \
  POSTHOG_KEY=phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR \
  POSTHOG_HOST=https://us.i.posthog.com \
  ALLOWED_ORIGIN_VERCEL=https://your-vercel-url.vercel.app
```

2. Replace the section header "Set secrets on Supabase" explanatory paragraph — add: "Price IDs are already pre-filled because the 4 products exist in Stripe Live mode."

3. In Step 3, after the existing webhook deploy note, add:

```bash
supabase functions deploy free-signup --no-verify-jwt
```

4. In Step 8's "Expected outcome" section, change any mention of tier counts from "three" to "four" and ensure the license format is `AETH-CLD-XXXX-XXXX-XXXX` (already correct).

- [ ] **Step 2: Full rewrite of VERCEL_ENV_VARS.md**

Replace the entire contents of `aethercloud/VERCEL_ENV_VARS.md` with:

```markdown
# Vercel environment variables

Paste these into your Vercel project (**Settings → Environment Variables**) so the Subscribe buttons and Checkout Session creation work. Scope every row to **Production + Preview + Development**.

## Required

| Name | Scope | Value |
|---|---|---|
| `STRIPE_SECRET_KEY` | Server | `sk_live_...` |
| `STRIPE_PRICE_SOLO` | Server | `price_1TNKCm3TqWOqdd87AngxY9ks` ($19/mo) |
| `STRIPE_PRICE_PRO` | Server | `price_1TNKCm3TqWOqdd87vSXEHnVW` ($49/mo) |
| `STRIPE_PRICE_TEAM` | Server | `price_1TNKCm3TqWOqdd87FJIdQFI1` ($89/mo) |
| `NEXT_PUBLIC_APP_URL` | Client | `https://<your-vercel-url>.vercel.app` → later `https://aethersystems.net` |
| `NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL` | Client | `https://<PROJECT_REF>.supabase.co/functions/v1/free-signup` |
| `NEXT_PUBLIC_POSTHOG_KEY` | Client | `phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR` |
| `NEXT_PUBLIC_POSTHOG_HOST` | Client | `https://us.i.posthog.com` |
| `POSTHOG_KEY` | Server | `phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR` |
| `POSTHOG_HOST` | Server | `https://us.i.posthog.com` |

## Where to get each value

- **`STRIPE_SECRET_KEY`** → Stripe dashboard → **Developers → API keys** → *Secret key*. Live mode only.
- **`STRIPE_PRICE_*`** → Already listed above. Don't re-create — they exist in Live mode.
- **`NEXT_PUBLIC_APP_URL`** → Blank on first deploy; Vercel gives you a `.vercel.app` URL. Paste it back as `NEXT_PUBLIC_APP_URL` and redeploy. Later swap for `https://aethersystems.net` after adding the custom domain.
- **`NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL`** → After running `aethercloud/deploy.sh`, the script prints this URL.
- **`POSTHOG_*`** → Already listed above. Project 386803 (US cloud).

## Security notes

- `NEXT_PUBLIC_*` variables are bundled into client JavaScript — safe to expose. The PostHog project key, publishable Stripe price IDs, and public Supabase function URL are all designed for browser exposure.
- `STRIPE_SECRET_KEY` must stay server-only. Never prefix it with `NEXT_PUBLIC_`.
- `POSTHOG_KEY` is the same value on client and server; PostHog uses the project API key for both. The `NEXT_PUBLIC_` distinction only controls which runtime reads it.

## Checklist

- [ ] All 10 rows added
- [ ] Every row scoped to Production, Preview, and Development
- [ ] Stripe account toggle was set to **Live** when copying the secret key
- [ ] Project redeployed after saving (env changes don't take effect until redeploy)
- [ ] After first deploy, ran `supabase secrets set ALLOWED_ORIGIN_VERCEL=https://<your-vercel-url>.vercel.app` so CORS on `free-signup` allows the site
```

- [ ] **Step 3: Commit**

```bash
git add aethercloud/DEPLOY_WALKTHROUGH.md aethercloud/VERCEL_ENV_VARS.md
git commit -m "docs(aethercloud): 4-tier walkthrough + new env vars (PostHog, CORS)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Scaffold site/ — package.json and configs

**Files:**
- Create: `site/package.json`
- Create: `site/next.config.js`
- Create: `site/tsconfig.json`
- Create: `site/tailwind.config.ts`
- Create: `site/postcss.config.js`
- Create: `site/.gitignore`

- [ ] **Step 1: Create `site/package.json`**

```json
{
  "name": "aethercloud-site",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint"
  },
  "dependencies": {
    "next": "^14.2.15",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "stripe": "^14.25.0",
    "posthog-js": "^1.161.6",
    "posthog-node": "^4.2.1"
  },
  "devDependencies": {
    "@types/node": "^20.12.12",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "autoprefixer": "^10.4.19",
    "eslint": "^8.57.0",
    "eslint-config-next": "^14.2.15",
    "postcss": "^8.4.38",
    "tailwindcss": "^3.4.4",
    "typescript": "^5.4.5"
  }
}
```

- [ ] **Step 2: Create `site/next.config.js`**

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
};

module.exports = nextConfig;
```

- [ ] **Step 3: Create `site/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 4: Create `site/tailwind.config.ts`**

```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};

export default config;
```

- [ ] **Step 5: Create `site/postcss.config.js`**

```javascript
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 6: Create `site/.gitignore`**

```
node_modules/
.next/
out/
.env
.env.local
.env.*.local
next-env.d.ts
*.tsbuildinfo
```

- [ ] **Step 7: Install and verify**

```bash
cd site && npm install && cd ..
```

Expected: installs without errors. Creates `site/node_modules/` and `site/package-lock.json`.

- [ ] **Step 8: Commit**

```bash
git add site/package.json site/next.config.js site/tsconfig.json site/tailwind.config.ts site/postcss.config.js site/.gitignore site/package-lock.json
git commit -m "chore(site): scaffold Next.js 14 + Tailwind config

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Create site/.env.example

**Files:**
- Create: `site/.env.example`

- [ ] **Step 1: Create `site/.env.example`**

```bash
# Server-only (never exposed to client)
STRIPE_SECRET_KEY=sk_live_REPLACE_ME
STRIPE_PRICE_SOLO=price_1TNKCm3TqWOqdd87AngxY9ks
STRIPE_PRICE_PRO=price_1TNKCm3TqWOqdd87vSXEHnVW
STRIPE_PRICE_TEAM=price_1TNKCm3TqWOqdd87FJIdQFI1

POSTHOG_KEY=phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR
POSTHOG_HOST=https://us.i.posthog.com

# Client-exposed (NEXT_PUBLIC_* shipped to browser)
NEXT_PUBLIC_APP_URL=http://localhost:3000
NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL=https://YOUR-PROJECT-REF.supabase.co/functions/v1/free-signup

NEXT_PUBLIC_POSTHOG_KEY=phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR
NEXT_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com
```

- [ ] **Step 2: Commit**

```bash
git add site/.env.example
git commit -m "chore(site): document required env vars in .env.example

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Copy PostHog drops into site/ and delete originals

**Files:**
- Create: `site/lib/posthog.ts` (copy of repo-root `lib/posthog.ts`)
- Create: `site/lib/track.ts` (copy of repo-root `lib/track.ts`)
- Create: `site/lib/server.ts` (copy of repo-root `lib/server.ts`)
- Create: `site/components/PostHogProvider.tsx` (copy of repo-root `components/PostHogProvider.tsx`)
- Delete: repo-root `lib/posthog.ts`, `lib/track.ts`, `lib/server.ts`, `components/PostHogProvider.tsx` (and parent dirs if empty)

- [ ] **Step 1: Copy all 4 files verbatim**

```bash
mkdir -p site/lib site/components
cp lib/posthog.ts site/lib/posthog.ts
cp lib/track.ts site/lib/track.ts
cp lib/server.ts site/lib/server.ts
cp components/PostHogProvider.tsx site/components/PostHogProvider.tsx
```

- [ ] **Step 2: Verify contents match**

```bash
diff lib/posthog.ts site/lib/posthog.ts
diff lib/track.ts site/lib/track.ts
diff lib/server.ts site/lib/server.ts
diff components/PostHogProvider.tsx site/components/PostHogProvider.tsx
```

Expected: all four diffs produce no output (identical).

- [ ] **Step 3: Delete originals**

```bash
rm lib/posthog.ts lib/track.ts lib/server.ts
rm components/PostHogProvider.tsx
# Remove parent dirs if now empty:
rmdir lib 2>/dev/null || true
rmdir components 2>/dev/null || true
```

- [ ] **Step 4: Commit**

```bash
git add site/lib/posthog.ts site/lib/track.ts site/lib/server.ts site/components/PostHogProvider.tsx
git add -u lib/ components/
git commit -m "chore(site): move PostHog drop files from repo root into site/

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Create app shell (layout + globals)

**Files:**
- Create: `site/app/layout.tsx`
- Create: `site/app/globals.css`

- [ ] **Step 1: Create `site/app/globals.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
```

- [ ] **Step 2: Create `site/app/layout.tsx`**

```tsx
import type { Metadata } from "next";
import { Suspense } from "react";
import { PostHogProvider } from "@/components/PostHogProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "AetherCloud — autonomous agents, paid by the task",
  description: "Voice-matched AI agents for Gmail, filesystem, and more. Four tiers, start free.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-white text-gray-900">
        <Suspense fallback={null}>
          <PostHogProvider>{children}</PostHogProvider>
        </Suspense>
      </body>
    </html>
  );
}
```

The `<Suspense>` wrap is required because `PostHogProvider` uses `useSearchParams` from `next/navigation`, which needs a Suspense boundary in App Router.

- [ ] **Step 3: Create a placeholder `site/app/page.tsx` so the build works (will be replaced in Task 14)**

```tsx
export default function Home() {
  return <main className="p-8"><h1 className="text-3xl font-bold">AetherCloud</h1></main>;
}
```

- [ ] **Step 4: Verify build**

```bash
cd site && npm run build && cd ..
```

Expected: `✓ Compiled successfully` and a summary with `/` route.

- [ ] **Step 5: Commit**

```bash
git add site/app/layout.tsx site/app/globals.css site/app/page.tsx
git commit -m "feat(site): app shell with PostHogProvider wrapping layout

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Create lib/tiers.ts (tier metadata)

**Files:**
- Create: `site/lib/tiers.ts`

- [ ] **Step 1: Create the file**

```typescript
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
```

- [ ] **Step 2: Commit**

```bash
git add site/lib/tiers.ts
git commit -m "feat(site): tier metadata and server-side price ID lookup

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Create PricingCard and FreeSignupForm components

**Files:**
- Create: `site/components/PricingCard.tsx`
- Create: `site/components/FreeSignupForm.tsx`

- [ ] **Step 1: Create `site/components/PricingCard.tsx`**

```tsx
"use client";

import { useState } from "react";
import { track } from "@/lib/track";
import type { Tier } from "@/lib/tiers";
import { FreeSignupForm } from "./FreeSignupForm";

export function PricingCard({ tier }: { tier: Tier }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onPaidSubscribe() {
    setLoading(true);
    setError(null);
    track.checkoutStarted({ tier: tier.key, price_id: "unknown" });
    try {
      const res = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier: tier.key }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? `checkout failed (${res.status})`);
      }
      const { url } = await res.json();
      if (!url) throw new Error("missing checkout url");
      window.location.href = url;
    } catch (e) {
      setError((e as Error).message);
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col border border-gray-200 rounded-xl p-6 bg-white shadow-sm">
      <div className="mb-4">
        <h3 className="text-lg font-semibold">{tier.name}</h3>
        <p className="text-3xl font-bold mt-1">{tier.price}</p>
        <p className="text-sm text-gray-500 mt-1">{tier.tagline}</p>
      </div>
      <ul className="flex-1 space-y-2 mb-6 text-sm">
        {tier.features.map((f) => (
          <li key={f} className="flex items-start">
            <span className="mr-2">•</span>
            <span>{f}</span>
          </li>
        ))}
      </ul>
      {tier.isFree ? (
        <FreeSignupForm />
      ) : (
        <>
          <button
            onClick={onPaidSubscribe}
            disabled={loading}
            className="w-full py-2 px-4 rounded-lg bg-black text-white font-medium hover:bg-gray-800 disabled:opacity-50"
          >
            {loading ? "Redirecting…" : tier.cta}
          </button>
          {error && <p className="text-xs text-red-600 mt-2">{error}</p>}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create `site/components/FreeSignupForm.tsx`**

```tsx
"use client";

import { useState } from "react";
import { track } from "@/lib/track";

export function FreeSignupForm() {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "submitting" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const freeSignupUrl = process.env.NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL ?? "";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (state === "submitting") return;
    if (!freeSignupUrl) {
      setError("signup endpoint not configured");
      setState("error");
      return;
    }

    track.signupStarted("pricing_page");
    setState("submitting");
    setError(null);

    try {
      const res = await fetch(freeSignupUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim().toLowerCase() }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error ?? `signup failed (${res.status})`);

      track.signupCompleted({ method: "email" });
      window.location.href = "/success";
    } catch (e) {
      setError((e as Error).message);
      setState("error");
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <input
        type="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@example.com"
        className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-black"
        disabled={state === "submitting"}
      />
      <button
        type="submit"
        disabled={state === "submitting" || !email}
        className="w-full py-2 px-4 rounded-lg bg-black text-white font-medium hover:bg-gray-800 disabled:opacity-50"
      >
        {state === "submitting" ? "Signing up…" : "Get started free"}
      </button>
      {error && <p className="text-xs text-red-600 mt-1">{error}</p>}
    </form>
  );
}
```

- [ ] **Step 3: Verify the components type-check**

```bash
cd site && npx tsc --noEmit && cd ..
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add site/components/PricingCard.tsx site/components/FreeSignupForm.tsx
git commit -m "feat(site): PricingCard (paid+free variants) and FreeSignupForm

FreeSignupForm reads NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL from env.
Both components fire the appropriate PostHog events via lib/track.ts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Build the pricing page

**Files:**
- Modify: `site/app/page.tsx` (replace placeholder from Task 11)

- [ ] **Step 1: Replace `site/app/page.tsx`**

```tsx
import { PricingCard } from "@/components/PricingCard";
import { TIERS } from "@/lib/tiers";

export default function Home() {
  return (
    <main className="max-w-6xl mx-auto px-4 py-16">
      <section className="text-center mb-12">
        <h1 className="text-4xl md:text-5xl font-bold tracking-tight">AetherCloud</h1>
        <p className="mt-4 text-lg text-gray-600 max-w-2xl mx-auto">
          Autonomous agents that match your voice, connect to your tools, and ship work while you sleep.
        </p>
      </section>

      <section>
        <h2 className="text-2xl font-semibold mb-6 text-center">Choose a plan</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {TIERS.map((tier) => <PricingCard key={tier.key} tier={tier} />)}
        </div>
      </section>

      <footer className="mt-16 text-center text-sm text-gray-500">
        Questions? <a href="mailto:support@aethersystems.net" className="underline">Email us</a>.
      </footer>
    </main>
  );
}
```

- [ ] **Step 2: Verify build**

```bash
cd site && npm run build && cd ..
```

Expected: `✓ Compiled successfully`.

- [ ] **Step 3: Commit**

```bash
git add site/app/page.tsx
git commit -m "feat(site): 4-tier pricing page

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Create lib/stripe.ts

**Files:**
- Create: `site/lib/stripe.ts`

- [ ] **Step 1: Create the file**

```typescript
// Server-only Stripe client. Never import from a client component.
import Stripe from "stripe";

const secretKey = process.env.STRIPE_SECRET_KEY;

export const stripe = secretKey
  ? new Stripe(secretKey, { apiVersion: "2024-06-20" })
  : (null as unknown as Stripe);

export function requireStripe(): Stripe {
  if (!stripe) throw new Error("STRIPE_SECRET_KEY is not set");
  return stripe;
}
```

- [ ] **Step 2: Commit**

```bash
git add site/lib/stripe.ts
git commit -m "feat(site): server-only Stripe client helper

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Create /api/checkout route

**Files:**
- Create: `site/app/api/checkout/route.ts`

- [ ] **Step 1: Create the file**

```typescript
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

  const priceId = priceIdForTier(tier);
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
```

The `export const runtime = "nodejs"` is important — Stripe's SDK uses Node crypto internally. The default edge runtime on Vercel would fail.

- [ ] **Step 2: Verify build**

```bash
cd site && npm run build && cd ..
```

Expected: `✓ Compiled successfully` with `/api/checkout` route listed.

- [ ] **Step 3: Commit**

```bash
git add site/app/api/checkout/route.ts
git commit -m "feat(site): /api/checkout route creates Stripe Checkout Session

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: Create /success and /canceled pages

**Files:**
- Create: `site/app/success/page.tsx`
- Create: `site/app/canceled/page.tsx`

- [ ] **Step 1: Create `site/app/success/page.tsx`**

```tsx
export const metadata = { title: "Welcome to AetherCloud" };

export default function SuccessPage() {
  return (
    <main className="max-w-2xl mx-auto px-4 py-24 text-center">
      <h1 className="text-3xl font-bold">You're in.</h1>
      <p className="mt-4 text-gray-600">
        Check your email for your license key. It should arrive within a minute from{" "}
        <strong>no-reply@aethersystems.net</strong>.
      </p>
      <p className="mt-6 text-sm text-gray-500">
        Didn't get it? Check spam, or{" "}
        <a href="mailto:support@aethersystems.net" className="underline">email support</a>.
      </p>
      <p className="mt-12">
        <a href="/" className="text-sm underline text-gray-600">Back to pricing</a>
      </p>
    </main>
  );
}
```

- [ ] **Step 2: Create `site/app/canceled/page.tsx`**

```tsx
export const metadata = { title: "Checkout canceled" };

export default function CanceledPage() {
  return (
    <main className="max-w-2xl mx-auto px-4 py-24 text-center">
      <h1 className="text-3xl font-bold">Checkout canceled.</h1>
      <p className="mt-4 text-gray-600">No charge was made. Come back anytime.</p>
      <p className="mt-12">
        <a href="/" className="text-sm underline text-gray-600">Back to pricing</a>
      </p>
    </main>
  );
}
```

- [ ] **Step 3: Verify build**

```bash
cd site && npm run build && cd ..
```

Expected: `✓ Compiled successfully` with `/success` and `/canceled` routes.

- [ ] **Step 4: Commit**

```bash
git add site/app/success/page.tsx site/app/canceled/page.tsx
git commit -m "feat(site): /success and /canceled pages

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 18: End-to-end local verification

**Goal:** Prove the site renders and the pricing page interaction works before deploying.

- [ ] **Step 1: Create a local `site/.env.local` (not committed)**

Fill in real Stripe test-mode keys and the deployed Supabase free-signup URL (if deployed) or a mock:

```bash
# site/.env.local (DO NOT COMMIT)
STRIPE_SECRET_KEY=sk_test_...              # TEST mode for local dev
STRIPE_PRICE_SOLO=price_...                # TEST mode Solo price — create in Stripe test mode
STRIPE_PRICE_PRO=price_...
STRIPE_PRICE_TEAM=price_...
POSTHOG_KEY=phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR
POSTHOG_HOST=https://us.i.posthog.com
NEXT_PUBLIC_APP_URL=http://localhost:3000
NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL=https://YOUR-REF.supabase.co/functions/v1/free-signup
NEXT_PUBLIC_POSTHOG_KEY=phc_yBVAN9NdLngv5A34awLWQqgg9eyVGELsn9hdWFzqNwhR
NEXT_PUBLIC_POSTHOG_HOST=https://us.i.posthog.com
```

For the local test, use Stripe **test-mode** keys and test-mode price IDs to avoid real charges.

- [ ] **Step 2: Run dev server**

```bash
cd site && npm run dev
```

Expected: dev server starts on `http://localhost:3000`.

- [ ] **Step 3: Manual check — pricing page**

Open `http://localhost:3000` in a browser. Verify:
- 4 cards render: Free / Solo / Pro / Team at $0 / $19 / $49 / $89
- Free card has an email input + "Get started free" button
- Paid cards have "Subscribe" buttons

- [ ] **Step 4: Manual check — Subscribe click fires PostHog + redirects to Stripe**

Open browser devtools → Network tab. Click **Subscribe** on Solo.
- Expected: POST to `/api/checkout` → 200 with `{ url: "https://checkout.stripe.com/..." }` → browser navigates to Stripe's hosted Checkout.
- In PostHog Live Events tab: `checkout_started` event with `tier=solo`.

Close the Stripe tab without paying.

- [ ] **Step 5: Manual check — Free signup flow (requires deployed free-signup function)**

If the Supabase free-signup function is deployed (Task 5 + deploy.sh run): type your email → click Get started free.
- Expected: 200 response → redirect to `/success`.
- Check email inbox for license.
- In PostHog: `signup_started` (client) and `signup_completed` (both client + server, same distinctId = email).

If free-signup isn't deployed yet: skip this step until you've run `aethercloud/deploy.sh`.

- [ ] **Step 6: No commit — this task is verification only**

---

## Task 19: Deploy

This task is performed manually by the user, not by an executing agent. Document steps so the user has a single checklist.

- [ ] **Step 1: Supabase side**

```bash
cd aethercloud
# Edit deploy.sh — fill PROJECT_REF, STRIPE_SECRET_KEY, RESEND_API_KEY, SUPABASE_SERVICE_ROLE_KEY
./deploy.sh
```

Follow the printed instructions to register the Stripe webhook in the dashboard and set `STRIPE_WEBHOOK_SECRET`.

- [ ] **Step 2: Vercel side — import project**

1. vercel.com/new → import `AETHER-CLOUD` repo.
2. Root Directory → `site`.
3. Framework Preset → Next.js (auto).
4. Add the 10 env vars from `aethercloud/VERCEL_ENV_VARS.md`. `NEXT_PUBLIC_APP_URL` blank for now; `NEXT_PUBLIC_SUPABASE_FREE_SIGNUP_URL` uses the URL printed by `deploy.sh`.
5. Deploy.

- [ ] **Step 3: Close the loop**

```bash
# After Vercel gives you aether-cloud-xxxxx.vercel.app:
# In Vercel: set NEXT_PUBLIC_APP_URL to that URL → redeploy.
# In terminal:
supabase secrets set \
  APP_URL=https://aether-cloud-xxxxx.vercel.app \
  ALLOWED_ORIGIN_VERCEL=https://aether-cloud-xxxxx.vercel.app
```

- [ ] **Step 4: Register webhook in Stripe dashboard**

Follow `aethercloud/STRIPE_WEBHOOK_SETUP.md`. Paste the webhook URL printed by `deploy.sh`. Select 4 events. Copy `whsec_...` → `supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_...`.

- [ ] **Step 5: Run full verification (from the spec)**

- **Paid flow.** Incognito → click Subscribe on Solo → pay $19 with real card → `/success`. Within 5s: `public.users` row (tier='solo'), Resend email, `checkout_completed` in PostHog, Stripe delivery 200. Refund.
- **Free flow.** Enter email in Free card → Get started free → `/success`. Within 5s: `public.users` row (tier='free'), Resend email, `signup_started` + `signup_completed` in PostHog.
- **Rate limit.** Submit 4× rapidly from same IP. 4th returns 429.
- **Disposable email.** Submit `x@mailinator.com` → 400.
- **CORS.** `curl -X OPTIONS -H "Origin: https://evil.com" <free-signup-url>` → 403.

---

## Task 20: Custom domain (later, optional)

- [ ] **Step 1: Vercel domain**

Vercel → Settings → Domains → add `aethersystems.net`. Follow DNS instructions.

- [ ] **Step 2: Update env vars**

```bash
# Vercel dashboard: NEXT_PUBLIC_APP_URL=https://aethersystems.net → redeploy
supabase secrets set APP_URL=https://aethersystems.net
# ALLOWED_ORIGIN_VERCEL can stay at .vercel.app URL (both are allowlisted).
```

---

## Post-implementation

Once all tasks above are green:

- Current branch is `claude/modest-galileo-7ce3d1` in a worktree. The user decides when to merge back to `main` (the branch is 2 commits behind origin/main at plan-start — may need `git pull --rebase` or let the user handle via PR).
- The spec's "Future considerations" section lists known deferrals (desktop app `/api/events` proxy, billing portal, stronger fraud protection, token metering) — none block v1.

