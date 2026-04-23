import { describe, it, expect, beforeEach } from "vitest";
import { rateCheck, __resetRateLimitForTests } from "@/lib/router/rateLimit";

/**
 * Red Team #1 H3 — in-process sliding-window rate limiter.
 *
 * Per-instance defense-in-depth. Vercel serverless has per-region instance
 * fanout, so the effective cluster limit is (instance_count × per_instance),
 * which is fine for floor-level flood protection. Not a substitute for a
 * real distributed limiter (Upstash, etc.) but the red-team's concern is
 * "nothing exists today" — this exists.
 */

beforeEach(() => {
  __resetRateLimitForTests();
});

describe("rateCheck — sliding-window counter", () => {
  it("allows up to limit requests within the window", () => {
    for (let i = 0; i < 10; i++) {
      const r = rateCheck("k", 1000, 60_000, 10);
      expect(r.allowed).toBe(true);
    }
  });

  it("rejects the (limit+1)th request in the window", () => {
    for (let i = 0; i < 10; i++) rateCheck("k", 1000, 60_000, 10);
    const r = rateCheck("k", 1000, 60_000, 10);
    expect(r.allowed).toBe(false);
    expect(r.retry_after_seconds).toBeGreaterThan(0);
  });

  it("allows again after window slides", () => {
    for (let i = 0; i < 10; i++) rateCheck("k", 1000, 60_000, 10);
    // Now 60.001 s later — all previous entries expired
    const r = rateCheck("k", 61_001, 60_000, 10);
    expect(r.allowed).toBe(true);
  });

  it("keys are isolated — different keys independent", () => {
    for (let i = 0; i < 10; i++) rateCheck("a", 1000, 60_000, 10);
    const r = rateCheck("b", 1000, 60_000, 10);
    expect(r.allowed).toBe(true);
  });

  it("retry_after_seconds is computed from the oldest entry, not now", () => {
    rateCheck("k", 0, 60_000, 2); // oldest at t=0
    rateCheck("k", 10_000, 60_000, 2); // 10s in
    const r = rateCheck("k", 20_000, 60_000, 2); // blocked, oldest expires at 60000
    expect(r.allowed).toBe(false);
    // Oldest expires at 60_000; now is 20_000; wait 40s.
    expect(r.retry_after_seconds).toBe(40);
  });

  it("reset clears all buckets for tests", () => {
    for (let i = 0; i < 10; i++) rateCheck("k", 1000, 60_000, 10);
    __resetRateLimitForTests();
    const r = rateCheck("k", 1000, 60_000, 10);
    expect(r.allowed).toBe(true);
  });
});
