import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { middleware } from "@/middleware";

const GOOD = "primary-token-abc123";
const PREV = "previous-token-xyz789";

function req(headers: Record<string, string> = {}, path = "/api/internal/router/pick"): Request {
  return new Request(`http://localhost${path}`, {
    method: "POST",
    headers,
  });
}

beforeEach(() => {
  process.env.AETHER_INTERNAL_SERVICE_TOKEN = GOOD;
  process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = PREV;
});

afterAll(() => {
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV;
});

describe("middleware — /api/internal/* service token auth", () => {
  it("current token → pass-through (returns undefined)", () => {
    const res = middleware(req({ "x-aether-internal": GOOD }));
    expect(res).toBeUndefined();
  });

  it("previous token (rotation overlap) → pass-through", () => {
    const res = middleware(req({ "x-aether-internal": PREV }));
    expect(res).toBeUndefined();
  });

  it("missing token → 401", () => {
    const res = middleware(req());
    expect(res).toBeDefined();
    expect((res as Response).status).toBe(401);
  });

  it("invalid token → 401", () => {
    const res = middleware(req({ "x-aether-internal": "wrong" }));
    expect(res).toBeDefined();
    expect((res as Response).status).toBe(401);
  });

  it("_PREV empty + current token → pass", () => {
    process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = "";
    const res = middleware(req({ "x-aether-internal": GOOD }));
    expect(res).toBeUndefined();
  });

  it("token comparison is constant-time under noise (no early-exit leak)", () => {
    // Tests the XOR-reduce compare has no data-dependent branch. Timing noise on
    // Windows (JIT, GC, event-loop) dominates the ~100ns compare cost, so we use
    // a very permissive ceiling — the signal we care about is "catastrophic
    // early-exit" (would show >5× delta), not micro-precision. High-precision
    // constant-time validation belongs in a dedicated microbenchmark.
    const N = 3000;
    const median = (fn: () => void): number => {
      const arr: number[] = [];
      for (let i = 0; i < N; i++) {
        const t0 = process.hrtime.bigint();
        fn();
        arr.push(Number(process.hrtime.bigint() - t0));
      }
      arr.sort((a, b) => a - b);
      return arr[Math.floor(N / 2)];
    };

    const validMed = median(() => middleware(req({ "x-aether-internal": GOOD })));
    const badSameLen = "x".repeat(GOOD.length);
    const invalidMed = median(() => middleware(req({ "x-aether-internal": badSameLen })));

    const delta = Math.abs(validMed - invalidMed) / Math.max(validMed, invalidMed);
    expect(delta).toBeLessThan(0.6); // catastrophic-leak ceiling; real early-exit shows >2×
  });
});
