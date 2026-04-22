import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { POST } from "@/app/api/internal/router/pick/route";
import { resetAuditWriter } from "@/lib/router/auditLog";

// ─────────────────────────────────────────────────────────────────
// §2.4 Cap-Evasion PoC — activeConcurrentTasks bypass via client body.
//
// Architecture doc explicitly admits the field is "advisory." The route
// does not re-check concurrency server-side; the value from the POST
// body is the only source consulted. An attacker always passes 0.
//
// TOCTOU extension: even if a future version fetched concurrency
// server-side once at gate time, N simultaneous requests would all
// observe count<cap and all pass — needs a Redis semaphore / pg
// advisory lock. PR 2 scope.
//
// Severity: HIGH. Plan-cap theft + DoS vector. Fix: server-side
// counter with atomic increment.
// ─────────────────────────────────────────────────────────────────

const TOKEN = "poc-token";

function post(body: unknown): Request {
  return new Request("http://localhost/api/internal/router/pick", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-aether-internal": TOKEN,
    },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  process.env.AETHER_INTERNAL_SERVICE_TOKEN = TOKEN;
  process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = "";
  resetAuditWriter();
});

afterAll(() => {
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV;
  resetAuditWriter();
});

describe("PoC 2.4 — client-supplied activeConcurrentTasks bypasses concurrency_cap", () => {
  it("Pro user with 100 real in-flight tasks attests 0 → gate passes", async () => {
    const body = {
      userId: "00000000-0000-0000-0000-0000000000cc",
      tier: "pro",                    // cap=3
      taskKind: "chat",
      estimatedInputTokens: 50,
      estimatedOutputTokens: 50,
      opusPctMtd: 0,
      activeConcurrentTasks: 0,       // LIE — real is 100
      uvtBalance: 1_000_000,
      requestId: "poc-2-4c",
      traceId: "poc-2-4c",
    };
    const res = await POST(post(body));
    expect(res.status).toBe(200);
  });

  it("TOCTOU — 50 parallel requests with activeConcurrentTasks=0 all pass", async () => {
    const mk = (i: number) => ({
      userId: "00000000-0000-0000-0000-0000000000cc",
      tier: "pro" as const,
      taskKind: "chat" as const,
      estimatedInputTokens: 50,
      estimatedOutputTokens: 50,
      opusPctMtd: 0,
      activeConcurrentTasks: 0,
      uvtBalance: 1_000_000,
      requestId: `poc-2-4c-${i}`,
      traceId: `poc-2-4c-${i}`,
    });
    const results = await Promise.all(
      Array.from({ length: 50 }, (_, i) => POST(post(mk(i)))),
    );
    expect(results.every((r) => r.status === 200)).toBe(true);
  });
});
