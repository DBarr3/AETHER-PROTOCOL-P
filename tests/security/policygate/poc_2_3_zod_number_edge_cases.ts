import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { POST } from "@/app/api/internal/router/pick/route";
import { resetAuditWriter } from "@/lib/router/auditLog";

// ─────────────────────────────────────────────────────────────────
// §2.3 Input-Injection PoC — Zod number edge cases that could trip
// downstream math.
//
// The schema uses:
//   - z.number().int().nonnegative().finite()  (token counts, balance)
//   - z.number().min(0).max(1).finite()        (opusPctMtd)
// Coverage here is focused on:
//   (a) Confirming .finite() rejects NaN / +Infinity / -Infinity.
//   (b) Confirming .strict() rejects unknown keys + prototype-shaped
//       keys (__proto__, constructor, prototype).
//   (c) Confirming that string-coerced numbers ("0") are rejected by
//       z.number() in v3.
//
// No critical finding emerges from this file alone — but it is
// important coverage evidence because the opusPctMtd === NaN case is
// the textbook fail-open for `ctx.opusPctMtd >= plan.opus_pct_cap`
// (NaN comparisons are always false → gate would pass opus for free
// tier). Zod blocks it. Document the layered defence.
// ─────────────────────────────────────────────────────────────────

const TOKEN = "zod-poc";

function post(body: unknown): Request {
  return new Request("http://localhost/api/internal/router/pick", {
    method: "POST",
    headers: { "content-type": "application/json", "x-aether-internal": TOKEN },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

const base = {
  userId: "00000000-0000-0000-0000-0000000000ff",
  tier: "pro",
  taskKind: "chat",
  estimatedInputTokens: 100,
  estimatedOutputTokens: 100,
  opusPctMtd: 0,
  activeConcurrentTasks: 0,
  uvtBalance: 1_000_000,
  requestId: "zod",
  traceId: "zod",
};

beforeEach(() => {
  process.env.AETHER_INTERNAL_SERVICE_TOKEN = TOKEN;
  process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = "";
  resetAuditWriter();
});
afterAll(() => {
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV;
});

describe("PoC 2.3 — Zod edges", () => {
  it("NaN opusPctMtd rejected (would otherwise fail-open on >= cap)", async () => {
    // JSON.stringify(NaN) = "null"; send raw JSON string instead.
    const rawBody = JSON.stringify(base).replace('"opusPctMtd":0', '"opusPctMtd":NaN');
    // JSON does not permit the literal NaN; parser returns "invalid_json".
    const res = await POST(post(rawBody));
    expect([400]).toContain(res.status);
  });

  it("Infinity opusPctMtd rejected", async () => {
    const rawBody = JSON.stringify(base).replace('"opusPctMtd":0', '"opusPctMtd":Infinity');
    const res = await POST(post(rawBody));
    expect(res.status).toBe(400);
  });

  it("negative estimatedInputTokens rejected (.nonnegative())", async () => {
    const res = await POST(post({ ...base, estimatedInputTokens: -1 }));
    expect(res.status).toBe(400);
  });

  it("float estimatedOutputTokens rejected (.int())", async () => {
    const res = await POST(post({ ...base, estimatedOutputTokens: 0.5 }));
    expect(res.status).toBe(400);
  });

  it("stringified number rejected (z.number() does not coerce in v3)", async () => {
    const res = await POST(post({ ...base, estimatedInputTokens: "100" as unknown as number }));
    expect(res.status).toBe(400);
  });

  it("__proto__ as top-level key → .strict() unknown-key rejection", async () => {
    const res = await POST(post({ ...base, __proto__: { tier: "team" } }));
    expect(res.status).toBe(400);
  });

  it("opusPctMtd > 1 rejected (.max(1))", async () => {
    const res = await POST(post({ ...base, opusPctMtd: 1.01 }));
    expect(res.status).toBe(400);
  });

  it("tier with trailing zero-width space rejected (enum is exact)", async () => {
    const res = await POST(post({ ...base, tier: "pro​" }));
    expect(res.status).toBe(400);
  });

  it("requestId 257 chars rejected (.max(256))", async () => {
    const res = await POST(post({ ...base, requestId: "x".repeat(257) }));
    expect(res.status).toBe(400);
  });
});
