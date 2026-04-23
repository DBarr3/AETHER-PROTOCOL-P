import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { POST } from "@/app/api/internal/router/pick/route";
import { resetAuditWriter } from "@/lib/router/auditLog";
import {
  resetGateInputsForTests,
  setActiveConcurrentTasksResolver,
} from "@/lib/router/gateInputs";

// C3 regression: the client cannot lie about their active concurrent
// task count. The route strips activeConcurrentTasks from the body
// pre-Zod and overrides it with the server-resolved value from
// getActiveConcurrentTasks(userId).

const GOOD = "c3-token";

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
  userId: "00000000-0000-0000-0000-00000000c300",
  tier: "pro",                   // concurrency_cap = 3
  taskKind: "chat",
  estimatedInputTokens: 100,
  estimatedOutputTokens: 100,
  requestId: "req_c3",
  traceId: "trace_c3",
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

describe("policy_gate.concurrency_client_override_ignored — C3 guard", () => {
  it("body activeConcurrentTasks: 0 ignored; resolver returns 3 → ConcurrencyCapExceeded 429", async () => {
    setActiveConcurrentTasksResolver(async () => 3);
    const res = await POST(postReq({ ...base, activeConcurrentTasks: 0 }));
    expect(res.status).toBe(429);
    const body = await res.json();
    expect(body.error).toBe("router_gate");
    expect(body.gate_type).toBe("concurrency_cap_exceeded");
    expect(body.gate_cap_key).toBe("concurrency_cap");
    // observed_value is the RESOLVED count, not the client's 0.
    expect(body.observed_value).toBe(3);
  });

  it("body activeConcurrentTasks: 999 ignored; resolver 0 → gate passes", async () => {
    setActiveConcurrentTasksResolver(async () => 0);
    const res = await POST(postReq({ ...base, activeConcurrentTasks: 999 }));
    expect(res.status).toBe(200);
  });

  it("body omitting activeConcurrentTasks → validates", async () => {
    setActiveConcurrentTasksResolver(async () => 0);
    const res = await POST(postReq(base));
    expect(res.status).toBe(200);
  });
});
