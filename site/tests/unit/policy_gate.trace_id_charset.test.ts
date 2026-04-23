import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { POST } from "@/app/api/internal/router/pick/route";
import { resetAuditWriter } from "@/lib/router/auditLog";
import { resetGateInputsForTests } from "@/lib/router/gateInputs";
import { __resetRateLimitForTests } from "@/lib/router/rateLimit";

/**
 * Red Team #1 M4 — traceId / requestId charset + length restriction.
 *
 * Pre-fix: z.string().min(1).max(256) — newlines, ANSI escapes, control
 * chars all allowed. Low-impact in the HTTP envelope; higher concern is
 * the audit row: traceId lands in routing_decisions.trace_id text
 * unescaped, corrupting any log dashboard that splits on \n or renders
 * ANSI.
 *
 * Post-fix: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/). Charset covers
 * UUIDs, span IDs, Vercel trace formats, and all existing callers.
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
  tier: "pro" as const,
  taskKind: "chat" as const,
  estimatedInputTokens: 10,
  estimatedOutputTokens: 10,
  requestId: "req_valid",
  traceId: "trace_valid",
};

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

describe("M4 — traceId / requestId charset enforcement", () => {
  it("accepts UUID-shaped traceId + requestId", async () => {
    const res = await POST(
      req({
        ...base,
        requestId: "550e8400-e29b-41d4-a716-446655440000",
        traceId: "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
      }),
    );
    expect(res.status).not.toBe(400);
  });

  it("accepts alphanumeric+underscore+colon (Vercel span-id style)", async () => {
    const res = await POST(
      req({ ...base, traceId: "vercel:span_abc123", requestId: "req.id_42" }),
    );
    expect(res.status).not.toBe(400);
  });

  it("rejects traceId with embedded newline (log injection)", async () => {
    const res = await POST(req({ ...base, traceId: "ok\nmalicious-line" }));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("validation_failed");
  });

  it("rejects traceId with ANSI escape", async () => {
    const res = await POST(req({ ...base, traceId: "\u001b[31mred\u001b[0m" }));
    expect(res.status).toBe(400);
  });

  it("rejects traceId with space (charset violation)", async () => {
    const res = await POST(req({ ...base, traceId: "has space" }));
    expect(res.status).toBe(400);
  });

  it("rejects traceId with emoji / non-ASCII", async () => {
    const res = await POST(req({ ...base, traceId: "\u{1F525}fire" }));
    expect(res.status).toBe(400);
  });

  it("rejects traceId above 128 char limit", async () => {
    const res = await POST(req({ ...base, traceId: "a".repeat(129) }));
    expect(res.status).toBe(400);
  });

  it("accepts traceId at exact 128 char limit", async () => {
    const res = await POST(req({ ...base, traceId: "a".repeat(128) }));
    expect(res.status).not.toBe(400);
  });

  it("rejects empty requestId", async () => {
    const res = await POST(req({ ...base, requestId: "" }));
    expect(res.status).toBe(400);
  });

  it("rejects traceId with slash / equals (not in allowlist)", async () => {
    const res = await POST(req({ ...base, traceId: "x/y=z" }));
    expect(res.status).toBe(400);
  });
});
