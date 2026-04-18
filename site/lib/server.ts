// aethercloud/posthog/lib/server.ts
//
// Server-side PostHog client for Next.js API routes and Stripe webhooks.
// Uses posthog-node (batched, flushes on shutdown). Never import this file
// from a client component.
//
// Requires env vars (server-only, NOT the NEXT_PUBLIC_* ones):
//   POSTHOG_KEY  = phc_...
//   POSTHOG_HOST = https://us.i.posthog.com

import { PostHog } from "posthog-node";

let client: PostHog | null = null;

export function posthogServer() {
  if (client) return client;
  const key = process.env.POSTHOG_KEY;
  if (!key) throw new Error("POSTHOG_KEY is not set");
  client = new PostHog(key, {
    host: process.env.POSTHOG_HOST ?? "https://us.i.posthog.com",
    flushAt: 1,          // flush every event immediately — serverless functions die fast
    flushInterval: 0,
  });
  return client;
}

/**
 * Call at the end of a serverless handler so events actually ship before the
 * lambda freezes.
 */
export async function flushPostHog() {
  if (!client) return;
  await client.shutdown();
  client = null;
}
