import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { POST } from "@/app/api/internal/router/pick/route";
import { resetAuditWriter } from "@/lib/router/auditLog";
import { resetGateInputsForTests } from "@/lib/router/gateInputs";

/**
 * Red Team #1 H2 — estimatedInputTokens / estimatedOutputTokens upper bound.
 *
 * Before the bigint migration, a 500 M input-token request on Opus
 * overflowed int32 on predicted_uvt_cost during the routing_decisions insert;
 * fireAndForget swallowed the DB error, audit row was lost.
 *
 * Defense in depth (orthogonal to the column-type migration): reject
 * unreasonable request sizes at the Zod layer — no legitimate caller sends
 * more than ~200 k tokens per request (Claude's own context window), so
 * 2 M is a 10x safety ceiling. Anything above is either a bug or an attack.
 */

const GOOD = "test-service-token-xyz";

function req(body: unknown): Request {
  return new Request("http://localhost/api/internal/router/pick", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-aether-internal": GOOD,
    },
    body: JSON.stringify(body),
  });
}

const base = {
  userId: "00000000-0000-0000-0000-000000000001",
  tier: "pro",
  taskKind: "chat",
  estimatedInputTokens: 100,
  estimatedOutputTokens: 100,
  requestId: "r1",
  traceId: "t1",
};

beforeEach(() => {
  process.env.AETHER_INTERNAL_SERVICE_TOKEN = GOOD;
  process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = "";
  resetAuditWriter();
  resetGateInputsForTests();
});

afterAll(() => {
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV;
  resetAuditWriter();
  resetGateInputsForTests();
});

describe("H2 upper-bound on estimated token counts", () => {
  it("accepts estimatedInputTokens at the 2M ceiling", async () => {
    const res = await POST(
      req({ ...base, estimatedInputTokens: 2_000_000, estimatedOutputTokens: 0, uvtBalance: 1_000_000_000 }),
    );
    // Either 200 (if balance/gates pass) or 402/413 on a gate — but MUST NOT
    // be 400 validation_failed.
    expect(res.status).not.toBe(400);
  });

  it("rejects estimatedInputTokens above 2M with 400 validation_failed", async () => {
    const res = await POST(req({ ...base, estimatedInputTokens: 2_000_001 }));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("validation_failed");
  });

  it("rejects estimatedInputTokens = 500M (Red Team H2 overflow input) with 400", async () => {
    const res = await POST(req({ ...base, estimatedInputTokens: 500_000_000 }));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("validation_failed");
  });

  it("rejects estimatedOutputTokens above 2M (overflow defense in depth) with 400", async () => {
    const res = await POST(req({ ...base, estimatedOutputTokens: 2_000_001 }));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("validation_failed");
  });

  it("accepts typical Team-tier request (200k input, 64k output)", async () => {
    const res = await POST(
      req({ ...base, tier: "team", estimatedInputTokens: 200_000, estimatedOutputTokens: 64_000 }),
    );
    // Not a 400 — business-logic gates may still trip, but schema is happy.
    expect(res.status).not.toBe(400);
  });
});
