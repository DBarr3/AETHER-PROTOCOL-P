// Single source of truth for service-token constant-time comparison.
//
// Red Team #1 M2 consolidation. The pre-fix state had a hand-rolled
// XOR-reduce `constantTimeEqual` duplicated in site/middleware.ts and
// site/app/api/internal/router/pick/route.ts, both with an early-return
// on length mismatch that leaked the expected-token length through
// timing. This module wraps node:crypto.timingSafeEqual (constant-time
// at the libcrypto level) and pads unequal-length inputs so the length
// branch also takes the full compare's worth of time.

import { timingSafeEqual } from "node:crypto";
import { metrics } from "@opentelemetry/api";

// Red Team #1 M3 — counter emitted every time the rotation-overlap token
// (_PREV) is the one that matches. SRE alert: any traffic on this counter
// AFTER the rotation window + grace period → page (operator forgot to
// unset _PREV).
const _serviceTokenMeter = metrics.getMeter("aether.router.service_token");
const _prevTokenAcceptedCounter = _serviceTokenMeter.createCounter(
  "router.prev_token_accepted",
  {
    description:
      "Times the AETHER_INTERNAL_SERVICE_TOKEN_PREV rotation-overlap token matched a request. Expected zero outside a rotation window; any traffic after _PREV_EXPIRES_AT passes should also be zero (TTL blocks it).",
  },
);

function isPrevExpired(): boolean {
  const raw = process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT;
  if (!raw) return false; // unset = no deadline, legacy behavior (valid until unset)
  const epoch = Date.parse(raw);
  if (Number.isNaN(epoch)) return true; // unparseable = fail-closed (reject PREV)
  return Date.now() >= epoch;
}

/**
 * Constant-time string compare. Uses node:crypto.timingSafeEqual under
 * the hood; pads unequal-length inputs before comparing so the length
 * check cannot be observed via timing.
 *
 * Returns true only when both strings are the same length AND have
 * byte-identical utf8 representations.
 */
export function serviceTokenEquals(provided: string, expected: string): boolean {
  const ab = Buffer.from(provided, "utf8");
  const bb = Buffer.from(expected, "utf8");

  if (ab.length !== bb.length) {
    // Pad both sides to the longer length. timingSafeEqual still runs a
    // constant-time compare; we intentionally discard the result and
    // return false because the original lengths were unequal. The pad
    // step ensures the "unequal-length" branch and the "equal-length
    // mismatch" branch take approximately the same time.
    const n = Math.max(ab.length, bb.length, 1);
    const pa = Buffer.concat([ab, Buffer.alloc(n - ab.length)], n);
    const pb = Buffer.concat([bb, Buffer.alloc(n - bb.length)], n);
    // Result intentionally consumed by the runtime but not used in the
    // return value — this is the "keep-the-timing-cost" branch.
    timingSafeEqual(pa, pb);
    return false;
  }

  return timingSafeEqual(ab, bb);
}

/**
 * Validate an incoming `x-aether-internal` header against the current
 * and previous (rotation-overlap) tokens from the env. Consolidates the
 * duplicated logic that used to live in middleware.ts + route.ts.
 *
 * Callers: `site/middleware.ts` (edge path), `site/app/api/internal/
 * router/pick/route.ts` (defense-in-depth after the edge check).
 *
 * Empty env values mean "unconfigured" → the corresponding branch is
 * skipped. An entirely unconfigured server returns false for every
 * header (including empty-string), preventing accidental bypass.
 */
export function isValidServiceTokenHeader(header: string | null): boolean {
  if (!header) return false;
  const current = process.env.AETHER_INTERNAL_SERVICE_TOKEN ?? "";
  const prev = process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV ?? "";

  if (current !== "" && serviceTokenEquals(header, current)) return true;

  // PREV path — M3: honor _PREV_EXPIRES_AT TTL + emit OTel counter
  // whenever PREV is the match, so SRE can alert if traffic persists
  // beyond the rotation grace period (or the operator forgot to unset).
  if (prev !== "" && !isPrevExpired() && serviceTokenEquals(header, prev)) {
    try {
      _prevTokenAcceptedCounter.add(1, {});
    } catch {
      // counter add should never throw; defensive
    }
    return true;
  }

  return false;
}
