import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { POST } from "@/app/api/internal/router/pick/route";
import { resetAuditWriter } from "@/lib/router/auditLog";
import {
  resetGateInputsForTests,
  setUvtBalanceResolver,
} from "@/lib/router/gateInputs";

// C2 regression: the client cannot lie about their UVT balance. The
// route strips uvtBalance from the body pre-Zod and overrides it with
// the server-resolved value from getUvtBalance(userId).

const GOOD = "c2-token";

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

const base = {
  userId: "00000000-0000-0000-0000-00000000c200",
  tier: "pro",
  taskKind: "chat",
  estimatedInputTokens: 5000,
  estimatedOutputTokens: 5000,
  activeConcurrentTasks: 0,
  requestId: "req_c2",
  traceId: "trace_c2",
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

describe("policy_gate.uvt_client_override_ignored — C2 guard", () => {
  it("body uvtBalance: MAX_SAFE_INTEGER ignored; resolver 10 → InsufficientUvtBalance 402", async () => {
    setUvtBalanceResolver(async () => 10);
    const res = await POST(
      postReq({ ...base, uvtBalance: Number.MAX_SAFE_INTEGER }),
    );
    expect(res.status).toBe(402);
    const body = await res.json();
    expect(body.error).toBe("router_gate");
    expect(body.gate_type).toBe("insufficient_uvt_balance");
    expect(body.gate_cap_key).toBe("uvt_balance");
    // The plan_cap_value column in this gate carries the SERVER-RESOLVED
    // balance, not the attacker-claimed MAX_SAFE_INTEGER.
    expect(body.plan_cap_value).toBe(10);
  });

  it("body uvtBalance: 0 ignored; resolver returns 1_000_000 → gate passes", async () => {
    setUvtBalanceResolver(async () => 1_000_000);
    const res = await POST(postReq({ ...base, uvtBalance: 0 }));
    expect(res.status).toBe(200);
  });

  it("body omitting uvtBalance → validates (Zod no longer requires it)", async () => {
    setUvtBalanceResolver(async () => 1_000_000);
    const res = await POST(postReq(base));
    expect(res.status).toBe(200);
  });
});
