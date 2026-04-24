// site/lib/posthog-server.ts
//
// Server-side PostHog capture wrapper. Used from Next.js API routes
// (App Router, Node runtime) to emit analytics events without ever
// breaking the request path.
//
// Contract
// --------
//   captureServerEvent(distinctId, event, properties): Promise<void>
//
// - Lazy env load: reads POSTHOG_KEY + POSTHOG_HOST the first time
//   captureServerEvent is called, not at module import. This keeps
//   the module testable (vi.mock("posthog-node", ...)) without
//   requiring the env vars to be set at import time.
// - Fire-and-forget: telemetry failures are swallowed with
//   console.warn. This path MUST NOT throw — it sits next to revenue
//   and routing code, and a PostHog outage must not take those down.
// - Warm-start friendly: the PostHog client is a module-level
//   singleton so we re-use the same instance across warm serverless
//   invocations. We still `await posthog.shutdown()` after capture
//   so the event is flushed before the serverless handler returns
//   and the process can be frozen.
//
// Sanitization
// ------------
// This wrapper does NOT sanitize properties — the CALLER is
// responsible for only passing UUIDs, validated enums, static error
// codes, or prefixes (e.g. stripe_session.id.slice(0, 8)). Do NOT
// pass raw user-supplied strings, full Stripe session ids, exception
// messages, or anything else attacker-shaped through this function.
//
// Related: site/lib/posthog.ts (client-side, uses posthog-js).

import { PostHog } from "posthog-node";

type CaptureProps = Record<string, string | number | boolean | null>;

let client: PostHog | null = null;

function getClient(): PostHog | null {
  if (client) return client;

  const key = process.env.POSTHOG_KEY;
  const host = process.env.POSTHOG_HOST ?? "https://us.i.posthog.com";

  if (!key) {
    // Not an error — dev machines and test runs often don't have the
    // server key set. We degrade to a no-op rather than throwing.
    return null;
  }

  client = new PostHog(key, {
    host,
    // flushAt=1 forces each capture() to post immediately. In a
    // serverless function the process may freeze/terminate right
    // after the handler returns, so we cannot rely on the default
    // batch-flush timer firing.
    flushAt: 1,
    // flushInterval=0 disables the background flush timer (which
    // would otherwise keep a Node timer alive and prevent Lambda
    // freeze). The explicit shutdown() in captureServerEvent does
    // the draining.
    flushInterval: 0,
  });
  return client;
}

/**
 * Fire a server-side PostHog event.
 *
 * - Never throws. On any error (env missing, network, serialization)
 *   logs a warning and resolves.
 * - Awaits flush via `.shutdown()` so the event survives serverless
 *   freeze-after-return.
 *
 * @param distinctId  userId (UUID) or a synthetic id — must NOT be a
 *                    raw user-supplied string.
 * @param event       stable event name, e.g. "router_pick_request".
 * @param properties  pre-sanitized map of primitive values.
 */
export async function captureServerEvent(
  distinctId: string,
  event: string,
  properties: CaptureProps,
): Promise<void> {
  try {
    const ph = getClient();
    if (!ph) return;
    ph.capture({
      distinctId,
      event,
      properties,
    });
    // Flush this event before the handler returns. `.shutdown()` on
    // posthog-node v4 waits for pending requests to finish and also
    // clears the singleton's queue; we re-create the client on the
    // next call via getClient() resetting it below.
    await ph.shutdown();
    // After shutdown the client is no longer usable — drop the
    // reference so the next call instantiates a fresh one.
    client = null;
  } catch (err) {
    // Telemetry must never break the request path. Log and move on.
    console.warn("[posthog-server] capture failed", {
      event,
      err: err instanceof Error ? err.message : String(err),
    });
  }
}

/**
 * Test-only helper — forces the next call to re-read env vars. Not
 * exported from the package surface for app code; only vitest uses
 * it.
 */
export function __resetPostHogClientForTests(): void {
  client = null;
}
