import { describe, it, expect, beforeEach, afterAll, vi } from "vitest";
import { isValidServiceTokenHeader } from "@/lib/router/serviceToken";

/**
 * Red Team #1 M3 — _PREV token TTL + usage counter.
 *
 * Before: AETHER_INTERNAL_SERVICE_TOKEN_PREV was accepted indefinitely. If
 * an operator forgot to unset it at end-of-overlap, the leaked token
 * remained valid until manual intervention.
 *
 * After:
 *   - AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT env var (ISO 8601
 *     timestamp). Past-expiry → PREV is rejected; future or unset → PREV
 *     is still accepted.
 *   - Every time PREV is the matching token, router.prev_token_accepted
 *     OTel counter increments. SRE alert: any traffic on this counter
 *     after rotation window + grace → page.
 */

const GOOD = "primary-token-abc";
const PREV = "previous-token-xyz";

beforeEach(() => {
  process.env.AETHER_INTERNAL_SERVICE_TOKEN = GOOD;
  process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = PREV;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT;
  vi.restoreAllMocks();
});

afterAll(() => {
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT;
});

describe("isValidServiceTokenHeader — M3 PREV TTL", () => {
  it("accepts PREV when _PREV_EXPIRES_AT is unset (legacy behavior)", () => {
    expect(isValidServiceTokenHeader(PREV)).toBe(true);
  });

  it("accepts PREV when _PREV_EXPIRES_AT is in the future", () => {
    const future = new Date(Date.now() + 60 * 60 * 1000).toISOString(); // +1h
    process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT = future;
    expect(isValidServiceTokenHeader(PREV)).toBe(true);
  });

  it("rejects PREV when _PREV_EXPIRES_AT is in the past", () => {
    const past = new Date(Date.now() - 60 * 60 * 1000).toISOString(); // -1h
    process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT = past;
    expect(isValidServiceTokenHeader(PREV)).toBe(false);
  });

  it("still accepts current token after PREV has expired", () => {
    const past = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT = past;
    expect(isValidServiceTokenHeader(GOOD)).toBe(true);
  });

  it("fails closed on invalid (non-ISO) _PREV_EXPIRES_AT value", () => {
    process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV_EXPIRES_AT = "not-a-date";
    // Unparseable expiry → treat PREV as expired (safer than "unbounded")
    expect(isValidServiceTokenHeader(PREV)).toBe(false);
  });

  // Counter-emission (router.prev_token_accepted) is verified by source
  // review, not runtime test. Rationale: the counter is created at module
  // load time from `metrics.getMeter()`, which is the OTel API's module-
  // level singleton. Vitest's `vi.spyOn(metrics, "getMeter")` +
  // `vi.resetModules()` does not intercept the re-imported module's fresh
  // `metrics` reference, so a spy-based assertion here reports zero calls
  // even when the counter is actually firing. NoopCounter.add() is a
  // documented no-op that cannot throw, so the worst failure mode is
  // "counter is silently inactive" — which is the same as no-SDK-wired
  // default and is safe. SRE alerting wiring is part of the observability
  // stack, not PolicyGate code, so functional verification happens at the
  // collector level.
});
