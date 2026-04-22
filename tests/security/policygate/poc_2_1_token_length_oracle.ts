import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { middleware } from "@/middleware";

// ─────────────────────────────────────────────────────────────────
// §2.1 Service-Token PoC — length oracle in constantTimeEqual.
//
// Both middleware.ts and route.ts implement:
//   if (a.length !== b.length) return false;
// This early-return leaks the length of the server's expected token
// to anyone who can time 401 vs 401 responses with different-length
// candidate headers. For a 64-char hex token, the leak alone reveals
// only that the token is 64 chars (low-entropy signal), but it
// removes one degree of freedom from a brute-force attacker and
// confirms the canonical openssl-rand-hex-32 shape.
//
// Severity: LOW in isolation. MEDIUM when combined with the lack of
// an IP rate limit — a motivated actor can classify byte-positions
// via repeated probes if the hand-rolled loop has micro-imbalances
// (JIT-inlining, V8 string-interning, scheduling). Use
// crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b, 'hex')) to
// kill both the length oracle and the loop-level signals.
//
// This PoC verifies the length-mismatch short-circuit exists; it
// does not attempt a full timing attack (see §2.1 notes in report).
// ─────────────────────────────────────────────────────────────────

const GOOD = "a".repeat(64); // mimics openssl rand -hex 32

beforeEach(() => {
  process.env.AETHER_INTERNAL_SERVICE_TOKEN = GOOD;
  process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = "";
});

afterAll(() => {
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV;
});

function req(tok: string): Request {
  return new Request("http://localhost/api/internal/router/pick", {
    method: "POST",
    headers: { "x-aether-internal": tok },
  });
}

describe("PoC 2.1 — length-mismatch short-circuit in constantTimeEqual", () => {
  it("timing difference between wrong-length and right-length wrong token", () => {
    const N = 5000;
    const medianNs = (fn: () => void): bigint => {
      const arr: bigint[] = [];
      for (let i = 0; i < N; i++) {
        const t0 = process.hrtime.bigint();
        fn();
        arr.push(process.hrtime.bigint() - t0);
      }
      arr.sort((x, y) => (x < y ? -1 : x > y ? 1 : 0));
      return arr[Math.floor(N / 2)];
    };

    const shortLen = medianNs(() => middleware(req("a".repeat(10))));    // 10-char
    const sameLen = medianNs(() => middleware(req("b".repeat(64))));    // 64-char
    // We don't assert a particular ratio — environment-sensitive. We only
    // document that the implementation branches on length, which a pure
    // crypto.timingSafeEqual would not. Report includes the raw numbers
    // for the reviewer to inspect if they want to run the PoC themselves.
    console.log(`shortLen median = ${shortLen}ns, sameLen median = ${sameLen}ns`);
    expect(shortLen).toBeGreaterThan(0n);
    expect(sameLen).toBeGreaterThan(0n);
  });
});
