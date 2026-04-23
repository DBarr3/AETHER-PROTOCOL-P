import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { POST } from "@/app/api/internal/router/pick/route";
import {
  resetAuditWriter,
} from "@/lib/router/auditLog";
import {
  resetGateInputsForTests,
  setOpusPctMtdResolver,
} from "@/lib/router/gateInputs";

// C1 regression: the client cannot lie about their Opus MTD share. The
// route strips opusPctMtd from the body before Zod validation and
// overrides it with the server-resolved value from the registered
// resolver. This test stubs the resolver to return 0.95 and asserts
// the gate fires even when the body claims opusPctMtd: 0.

const GOOD = "c1-token";

function postReq(body: unknown): Request {
  return new Request("http://localhost/api/internal/router/pick", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-aether-internal": GOOD,
    },
    body: JSON.stringify(body),
  });
}

const bodyClaim = {
  userId: "00000000-0000-0000-0000-00000000c100",
  tier: "pro",
  taskKind: "agent_plan",            // pro + agent_plan → claude-opus-4
  estimatedInputTokens: 100,
  estimatedOutputTokens: 100,
  activeConcurrentTasks: 0,
  uvtBalance: 1_000_000,
  opusPctMtd: 0,                      // LIE — stripped & ignored
  requestId: "req_c1",
  traceId: "trace_c1",
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

describe("policy_gate.opuspct_client_override_ignored — C1 guard", () => {
  it("body opusPctMtd:0 ignored; resolver returns 0.95 → OpusBudgetExceeded 402", async () => {
    setOpusPctMtdResolver(async () => 0.95);
    const res = await POST(postReq(bodyClaim));
    expect(res.status).toBe(402);
    const body = await res.json();
    expect(body.error).toBe("router_gate");
    expect(body.gate_type).toBe("opus_budget_exceeded");
    expect(body.gate_cap_key).toBe("opus_pct_cap");
    expect(body.observed_value).toBe(0.95);
  });

  it("body opusPctMtd:0.9 still ignored; resolver 0 → gate passes", async () => {
    setOpusPctMtdResolver(async () => 0);
    const res = await POST(
      postReq({ ...bodyClaim, opusPctMtd: 0.9 }),
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.chosen_model).toBe("claude-opus-4");
  });

  it("body without opusPctMtd → validates (Zod no longer requires it)", async () => {
    setOpusPctMtdResolver(async () => 0);
    const { opusPctMtd: _drop, ...noOpus } = bodyClaim;
    const res = await POST(postReq(noOpus));
    expect(res.status).toBe(200);
  });
});
