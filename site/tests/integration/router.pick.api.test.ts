import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { POST } from "@/app/api/internal/router/pick/route";
import {
  setAuditWriter,
  resetAuditWriter,
  type RoutingDecisionRow,
} from "@/lib/router/auditLog";
import {
  resetGateInputsForTests,
  setOpusPctMtdResolver,
} from "@/lib/router/gateInputs";

const GOOD = "test-service-token-xyz";

function req(body: unknown, headers: Record<string, string> = {}): Request {
  return new Request("http://localhost/api/internal/router/pick", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-aether-internal": GOOD,
      ...headers,
    },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

// opusPctMtd is intentionally absent — C1 made it server-resolved. Tests
// that need a non-zero MTD value install a resolver stub via
// setOpusPctMtdResolver(async () => 0.15).
const validCtx = {
  userId: "00000000-0000-0000-0000-000000000001",
  tier: "pro",
  taskKind: "chat",
  estimatedInputTokens: 100,
  estimatedOutputTokens: 100,
  activeConcurrentTasks: 0,
  uvtBalance: 1_000_000,
  requestId: "req_integ_1",
  traceId: "trace_integ_1",
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

describe("POST /api/internal/router/pick", () => {
  it("200 + RoutingDecision on valid context", async () => {
    const res = await POST(req(validCtx));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.chosen_model).toBe("claude-sonnet-4");
    expect(body.reason_code).toBe("default_by_tier_and_task");
    expect(body.decision_schema_version).toBe(1);
    expect(body.uvt_weight_version).toBe(1);
    expect(typeof body.predicted_uvt_cost).toBe("number");
    expect(typeof body.predicted_uvt_cost_simple).toBe("number");
  });

  it("401 when service token missing at route level (defense-in-depth)", async () => {
    const res = await POST(
      new Request("http://localhost/api/internal/router/pick", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(validCtx),
      }),
    );
    expect(res.status).toBe(401);
  });

  it("400 on invalid JSON body", async () => {
    const res = await POST(req("{not json"));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("invalid_json");
  });

  it("400 on zod validation failure (unknown key)", async () => {
    const res = await POST(req({ ...validCtx, extraField: "x" }));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe("validation_failed");
  });

  it("400 on missing required field", async () => {
    const { tier, ...rest } = validCtx;
    const res = await POST(req(rest));
    expect(res.status).toBe(400);
  });

  it("402 with router_gate body shape on OpusBudgetExceeded", async () => {
    // Server-resolved opusPctMtd (C1). Stub the resolver so the gate
    // sees 15% MTD usage; sending opusPctMtd: 0.15 in the body would
    // be ignored (stripped pre-Zod) per the C1 patch.
    setOpusPctMtdResolver(async () => 0.15);
    const res = await POST(req({ ...validCtx, taskKind: "agent_plan" }));
    expect(res.status).toBe(402);
    const body = await res.json();
    expect(body.error).toBe("router_gate");
    expect(body.gate_type).toBe("opus_budget_exceeded");
    expect(body.gate_cap_key).toBe("opus_pct_cap");
    expect(body.user_message_code).toBe("opus_budget_exceeded");
    expect(body.trace_id).toBe("trace_integ_1");
  });

  it("413 on output cap exceeded", async () => {
    const res = await POST(
      req({ ...validCtx, tier: "solo", estimatedOutputTokens: 20000 }),
    );
    expect(res.status).toBe(413);
    const body = await res.json();
    expect(body.gate_type).toBe("output_tokens_exceed_cap");
  });

  it("429 on concurrency cap", async () => {
    const res = await POST(
      req({ ...validCtx, taskKind: "code_review", activeConcurrentTasks: 3 }),
    );
    expect(res.status).toBe(429);
    const body = await res.json();
    expect(body.gate_type).toBe("concurrency_cap_exceeded");
  });

  it("402 on insufficient UVT balance", async () => {
    const res = await POST(
      req({
        ...validCtx,
        estimatedInputTokens: 5000,
        estimatedOutputTokens: 5000,
        uvtBalance: 10,
      }),
    );
    expect(res.status).toBe(402);
    const body = await res.json();
    expect(body.gate_type).toBe("insufficient_uvt_balance");
  });

  it("success path invokes audit writer with chosen_model populated", async () => {
    const captured: RoutingDecisionRow[] = [];
    setAuditWriter(async (row) => {
      captured.push(row);
    });
    const res = await POST(req(validCtx));
    expect(res.status).toBe(200);
    await new Promise((r) => setImmediate(r));
    expect(captured.length).toBe(1);
    expect(captured[0].chosen_model).toBe("claude-sonnet-4");
    expect(captured[0].reason_code).toBe("default_by_tier_and_task");
  });

  it("gate path invokes audit writer with reason_code=gate_rejected", async () => {
    const captured: RoutingDecisionRow[] = [];
    setAuditWriter(async (row) => {
      captured.push(row);
    });
    const res = await POST(
      req({ ...validCtx, tier: "solo", estimatedOutputTokens: 20000 }),
    );
    expect(res.status).toBe(413);
    await new Promise((r) => setImmediate(r));
    expect(captured.length).toBe(1);
    expect(captured[0].reason_code).toBe("gate_rejected");
    expect(captured[0].chosen_model).toBeNull();
    expect(captured[0].gate_cap_key).toBe("output_cap");
    expect(captured[0].latency_ms).toBeGreaterThanOrEqual(0);
  });
});
