// aethercloud/posthog/lib/track.ts
//
// Typed event helpers. Every product-relevant action goes through one of these
// functions — never call posthog.capture() directly from app code. This keeps
// event names and property shapes consistent, which is the only way dashboards
// stay trustworthy over time.

import { posthog } from "./posthog";

type Tier = "free" | "solo" | "pro" | "team";

export const track = {
  pageview(path: string) {
    posthog.capture("$pageview", { $current_url: path });
  },

  signupStarted(source: "pricing_page" | "hero" | "nav" | "other") {
    posthog.capture("signup_started", { source });
  },

  signupCompleted(opts: { method: "email" | "google" | "github" }) {
    posthog.capture("signup_completed", { method: opts.method });
  },

  checkoutStarted(opts: { tier: Tier; price_id: string }) {
    posthog.capture("checkout_started", opts);
  },

  // checkout_completed is fired server-side from the Stripe webhook — don't
  // emit it from the browser. The redirect back to /success may not happen
  // (users close the tab, navigate away) and we must not miss revenue events.

  licenseActivated(opts: { tier: Tier; license_key_last4: string }) {
    // The desktop app calls a /api/events proxy on your Vercel site which
    // forwards this to PostHog. Never send the full license key.
    posthog.capture("license_activated", opts);
  },

  agentActionRun(opts: {
    action_type: string;
    tokens_used: number;
    mcp?: string;           // which MCP was invoked, if any
    duration_ms: number;
    succeeded: boolean;
  }) {
    posthog.capture("agent_action_run", opts);
  },

  voiceMatchUsed(opts: {
    mcp: "gmail" | "other";
    sample_size: number;    // how many sent emails the model learned from
    tone_score: number;     // 0-1 self-reported or auto-rated match quality
  }) {
    posthog.capture("voice_match_used", opts);
  },

  downloadClicked(opts: { os: "macos" | "windows" | "linux" }) {
    posthog.capture("download_clicked", opts);
  },
};
