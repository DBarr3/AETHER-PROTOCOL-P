// Single source of truth for service-token constant-time comparison.
//
// Red Team #1 M2 consolidation. The pre-fix state had a hand-rolled
// XOR-reduce `constantTimeEqual` duplicated in site/middleware.ts and
// site/app/api/internal/router/pick/route.ts, both with an early-return
// on length mismatch that leaked the expected-token length through
// timing. This module wraps node:crypto.timingSafeEqual (constant-time
// at the libcrypto level) and pads unequal-length inputs so the length
// branch also takes the full compare's worth of time.

import { metrics } from "@opentelemetry/api";

// Why not node:crypto.timingSafeEqual:
//   site/middleware.ts consumes this module from the Vercel edge runtime,
//   which does not expose node:-prefixed built-ins. `import "node:crypto"`
//   was causing webpack UnhandledSchemeError at build time. The XOR-reduce
//   below is runtime-agnostic (works on edge + nodejs) and gives the same
//   constant-time property as timingSafeEqual provided we don't early-exit
//   on length mismatch — which is exactly the M2 fix over the pre-M2 hand-
//   rolled version.

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
 * Constant-time string compare. No early return on length mismatch —
 * always walks max(len_a, len_b) codepoints. Folds the length difference
 * into the XOR accumulator so a length-oracle attacker cannot distinguish
 * "wrong length" from "wrong content" via timing.
 *
 * Edge-runtime safe (works without node:crypto). Equivalent timing
 * property to node:crypto.timingSafeEqual as long as the loop is not
 * short-circuited by a hostile JIT — the accumulator write on every
 * iteration keeps the loop alive for the optimizer.
 *
 * Returns true only when both strings have the same length AND
 * byte-identical UTF-16 codepoint sequences. (All callers use this on
 * opaque service-token strings; no Unicode normalization edge cases
 * apply because the comparison is codepoint-exact.)
 */
export function serviceTokenEquals(provided: string, expected: string): boolean {
  const la = provided.length;
  const lb = expected.length;
  const n = la > lb ? la : lb || 1;
  let diff = la ^ lb;
  for (let i = 0; i < n; i++) {
    const ca = i < la ? provided.charCodeAt(i) : 0;
    const cb = i < lb ? expected.charCodeAt(i) : 0;
    diff |= ca ^ cb;
  }
  return diff === 0;
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
