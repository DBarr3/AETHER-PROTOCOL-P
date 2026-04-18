// aethercloud/posthog/lib/posthog.ts
//
// Single source of truth for PostHog on the client. Import `posthog` anywhere
// in your Next.js app after the PostHogProvider has mounted.
//
// Requires env vars:
//   NEXT_PUBLIC_POSTHOG_KEY  = phc_...
//   NEXT_PUBLIC_POSTHOG_HOST = https://us.i.posthog.com   (US cloud)
//
// Drop this into lib/posthog.ts in your Vercel repo.

import posthog from "posthog-js";

let initialized = false;

export function initPostHog() {
  if (initialized || typeof window === "undefined") return;
  const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
  if (!key) {
    console.warn("[posthog] NEXT_PUBLIC_POSTHOG_KEY missing — analytics disabled");
    return;
  }
  posthog.init(key, {
    api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://us.i.posthog.com",
    person_profiles: "identified_only", // don't create person rows for anon visitors
    capture_pageview: false,             // we fire $pageview manually in _app.tsx for precise timing
    capture_pageleave: true,
    autocapture: true,
    session_recording: {
      maskAllInputs: true,               // never record keystrokes into form fields (billing safety)
    },
    loaded: (ph) => {
      if (process.env.NODE_ENV === "development") ph.debug();
    },
  });
  initialized = true;
}

export { posthog };

/**
 * Call once after a user authenticates / subscribes. Links all prior anonymous
 * events to this identity and sets reusable person properties.
 */
export function identify(opts: {
  userId: string;              // stripe customer id or your internal uuid
  email: string;
  tier: "free" | "solo" | "pro" | "team";
  licenseKey?: string;
}) {
  posthog.identify(opts.userId, {
    email: opts.email,
    tier: opts.tier,
    has_license: Boolean(opts.licenseKey),
  });
}

export function resetIdentity() {
  // Call on logout.
  posthog.reset();
}
