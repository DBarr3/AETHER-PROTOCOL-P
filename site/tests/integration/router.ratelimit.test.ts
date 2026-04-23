import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { middleware } from "@/middleware";
import { POST } from "@/app/api/internal/router/pick/route";
import { resetAuditWriter } from "@/lib/router/auditLog";
import { resetGateInputsForTests } from "@/lib/router/gateInputs";
import { __resetRateLimitForTests } from "@/lib/router/rateLimit";

/**
 * Red Team #1 H3 — middleware IP limit + route-level user limit.
 *
 * The red-team's recommended floor: 60 req/IP/min unauthenticated, 600
 * req/user/min authenticated. Implementation is per-instance; Vercel edge
 * fanout means the effective cluster limit is instance_count × floor,
 * which is acceptable for PR 1 and flagged as "upgrade to Upstash at scale"
 * in the docstring.
 */

const GOOD = "test-service-token-xyz";

function req(ip: string, headers: Record<string, string> = {}): Request {
  return new Request("http://localhost/api/internal/router/pick", {
    method: "POST",
    headers: {
      "x-forwarded-for": ip,
      "content-type": "application/json",
      ...headers,
    },
    body: "{}",
  });
}

beforeEach(() => {
  process.env.AETHER_INTERNAL_SERVICE_TOKEN = GOOD;
  process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = "";
  resetAuditWriter();
  resetGateInputsForTests();
  __resetRateLimitForTests();
});

afterAll(() => {
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV;
  resetAuditWriter();
  resetGateInputsForTests();
  __resetRateLimitForTests();
});

describe("middleware — H3 IP rate limit (60/min unauthenticated)", () => {
  it("allows 60 unauthenticated requests from the same IP", () => {
    for (let i = 0; i < 60; i++) {
      const res = middleware(req("1.2.3.4"));
      // 401 (auth failure) allowed within rate budget
      expect((res as Response).status).toBe(401);
    }
  });

  it("rejects the 61st unauthenticated request from the same IP with 429", async () => {
    for (let i = 0; i < 60; i++) middleware(req("1.2.3.4"));
    const res = middleware(req("1.2.3.4"));
    expect((res as Response).status).toBe(429);
    const body = await (res as Response).json();
    expect(body.error).toBe("rate_limited");
  });

  it("different IPs are bucketed independently", () => {
    for (let i = 0; i < 60; i++) middleware(req("1.2.3.4"));
    // 1.2.3.4 is rate-limited; 5.6.7.8 should still be allowed
    const res = middleware(req("5.6.7.8"));
    expect((res as Response).status).toBe(401); // not 429
  });

  it("authenticated requests count against IP rate budget too (flood protection)", () => {
    // 60 authenticated requests exhaust budget
    for (let i = 0; i < 60; i++) {
      middleware(req("1.2.3.4", { "x-aether-internal": GOOD }));
    }
    const res = middleware(req("1.2.3.4", { "x-aether-internal": GOOD }));
    expect((res as Response).status).toBe(429);
  });
});

describe("route — H3 user rate limit (600/min authenticated)", () => {
  const validCtx = {
    userId: "00000000-0000-0000-0000-000000000001",
    tier: "pro" as const,
    taskKind: "chat" as const,
    estimatedInputTokens: 10,
    estimatedOutputTokens: 10,
    requestId: "r",
    traceId: "t",
  };

  function authReq(body: unknown): Request {
    return new Request("http://localhost/api/internal/router/pick", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-aether-internal": GOOD,
      },
      body: JSON.stringify(body),
    });
  }

  it("allows 600 requests from the same userId", async () => {
    for (let i = 0; i < 600; i++) {
      const res = await POST(authReq(validCtx));
      expect(res.status).not.toBe(429);
    }
  });

  it("rejects the 601st request from the same userId with 429", async () => {
    for (let i = 0; i < 600; i++) await POST(authReq(validCtx));
    const res = await POST(authReq(validCtx));
    expect(res.status).toBe(429);
    const body = await res.json();
    expect(body.error).toBe("rate_limited");
  });

  it("different userIds bucketed independently", async () => {
    for (let i = 0; i < 600; i++) await POST(authReq(validCtx));
    const other = { ...validCtx, userId: "00000000-0000-0000-0000-000000000002" };
    const res = await POST(authReq(other));
    expect(res.status).not.toBe(429);
  });
});
