import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { POST } from "@/app/api/internal/router/pick/route";
import { setAuditWriter, resetAuditWriter, type RoutingDecisionRow } from "@/lib/router/auditLog";

// ─────────────────────────────────────────────────────────────────
// §2.5 Audit-Log PoC — integer overflow on predicted_uvt_cost
// produces a silent audit gap.
//
// `routing_decisions.predicted_uvt_cost integer` caps at 2^31-1
// (= 2,147,483,647). The weighted formula for Opus with large input
// is `(input * 1 + output * 4 + …) * 5`, and there is NO server-
// side cap on estimatedInputTokens. A Pro/Team user can send a
// request whose weighted cost overflows int32. The audit INSERT
// then fails with "value out of range for type integer" — but the
// writer is fire-and-forget, so the main pick() call still returns
// 200 and the orchestrator still runs the Opus call. Result: an
// un-audited privileged call.
//
// Severity: HIGH (audit evasion). Fix: migrate predicted_uvt_cost /
// predicted_uvt_cost_simple columns to bigint OR enforce an input-
// token cap in the gate.
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

describe("PoC 2.5 — predicted_uvt_cost overflow → dropped audit row", () => {
  it("weighted cost exceeds int32 max when input_tokens is massive + model=opus", async () => {
    const captured: RoutingDecisionRow[] = [];
    setAuditWriter(async (row) => {
      captured.push(row);
      // Emulate Postgres behavior for integer column
      if (row.predicted_uvt_cost !== null && row.predicted_uvt_cost > 2_147_483_647) {
        throw new Error("value out of range for type integer");
      }
    });

    const body = {
      userId: "00000000-0000-0000-0000-0000000000ee",
      tier: "team",
      taskKind: "agent_plan",          // team+agent_plan → claude-opus-4
      estimatedInputTokens: 500_000_000,
      estimatedOutputTokens: 32_000,    // within team output_cap (64000)
      opusPctMtd: 0,                    // below team cap of 0.25
      activeConcurrentTasks: 0,
      uvtBalance: Number.MAX_SAFE_INTEGER, // bypass balance gate (see 2.4)
      requestId: "poc-2-5b",
      traceId: "poc-2-5b",
    };

    const res = await POST(post(body));
    // Gate passes — attacker gets chosen_model back.
    expect(res.status).toBe(200);
    const decision = await res.json();
    expect(decision.chosen_model).toBe("claude-opus-4");
    // Weighted cost vastly exceeds int32 max.
    expect(decision.predicted_uvt_cost).toBeGreaterThan(2_147_483_647);

    // Audit writer captured the row but the simulated INSERT threw.
    await new Promise((r) => setImmediate(r));
    expect(captured.length).toBe(1);
    // In production the fire-and-forget catch swallows the error → no record.
  });
});
