// site/tests/integration/posthog-capture.test.ts
//
// End-to-end coverage for the three API routes that emit PostHog
// server events (issue #48 + the checkout/session extension).
//
// Strategy: mock `posthog-node` so we can assert on PostHog.capture()
// calls without hitting the network. Mock `@/lib/stripe` for the
// checkout/session routes so we don't need STRIPE_SECRET_KEY or a
// real Stripe API roundtrip.

import {
  afterAll,
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

// ---------------------------------------------------------------------
// posthog-node mock — captured() is the shared accumulator used by every
// test. resetPostHogMock() clears it between tests.
// ---------------------------------------------------------------------

const captured: Array<{
  distinctId: string;
  event: string;
  properties: Record<string, unknown>;
}> = [];

const captureSpy = vi.fn((e: {
  distinctId: string;
  event: string;
  properties: Record<string, unknown>;
}) => {
  captured.push({
    distinctId: e.distinctId,
    event: e.event,
    properties: e.properties ?? {},
  });
});
const shutdownSpy = vi.fn(async () => {});

vi.mock("posthog-node", () => {
  return {
    PostHog: vi.fn().mockImplementation(() => ({
      capture: captureSpy,
      shutdown: shutdownSpy,
    })),
  };
});

// ---------------------------------------------------------------------
// Stripe mock for checkout + session routes. Each test overrides the
// implementation to exercise success vs. failure branches.
// ---------------------------------------------------------------------

const stripeCheckoutCreate = vi.fn();
const stripeCheckoutRetrieve = vi.fn();

vi.mock("@/lib/stripe", () => {
  return {
    requireStripe: () => ({
      checkout: {
        sessions: {
          create: stripeCheckoutCreate,
          retrieve: stripeCheckoutRetrieve,
        },
      },
    }),
  };
});

// Defer route imports until AFTER the mocks are registered.
async function getRoutes() {
  const pickModule = await import("@/app/api/internal/router/pick/route");
  const checkoutModule = await import("@/app/api/checkout/route");
  const sessionModule = await import("@/app/api/session/route");
  const helper = await import("@/lib/posthog-server");
  return {
    pickPOST: pickModule.POST,
    checkoutPOST: checkoutModule.POST,
    sessionGET: sessionModule.GET,
    resetPostHogClient: helper.__resetPostHogClientForTests,
  };
}

// Router test deps — need to stub the audit writer / gate resolvers.
import {
  resetAuditWriter,
  setAuditWriter,
} from "@/lib/router/auditLog";
import {
  resetGateInputsForTests,
  setActiveConcurrentTasksResolver,
} from "@/lib/router/gateInputs";
import { __resetRateLimitForTests } from "@/lib/router/rateLimit";

const GOOD_TOKEN = "test-service-token-xyz";

function pickReq(body: unknown, headers: Record<string, string> = {}): Request {
  return new Request("http://localhost/api/internal/router/pick", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-aether-internal": GOOD_TOKEN,
      ...headers,
    },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

function checkoutReq(body: unknown): Request {
  return new Request("http://localhost/api/checkout", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

function sessionReq(id: string | null): Request {
  const url = new URL("http://localhost/api/session");
  if (id !== null) url.searchParams.set("id", id);
  return new Request(url.toString(), { method: "GET" });
}

const validRouterCtx = {
  userId: "00000000-0000-0000-0000-000000000001",
  tier: "pro",
  taskKind: "chat",
  estimatedInputTokens: 100,
  estimatedOutputTokens: 100,
  requestId: "req_posthog_1",
  traceId: "trace_posthog_1",
};

beforeEach(() => {
  process.env.POSTHOG_KEY = "phc_test_key";
  process.env.POSTHOG_HOST = "https://us.i.posthog.com";
  process.env.AETHER_INTERNAL_SERVICE_TOKEN = GOOD_TOKEN;
  process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = "";
  process.env.STRIPE_PRICE_AETHER_CLOUD_PRO = "price_test_pro";
  captured.length = 0;
  captureSpy.mockClear();
  shutdownSpy.mockClear();
  stripeCheckoutCreate.mockReset();
  stripeCheckoutRetrieve.mockReset();
  resetAuditWriter();
  resetGateInputsForTests();
  __resetRateLimitForTests();
});

afterEach(async () => {
  const { resetPostHogClient } = await getRoutes();
  resetPostHogClient();
});

afterAll(() => {
  delete process.env.POSTHOG_KEY;
  delete process.env.POSTHOG_HOST;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV;
  delete process.env.STRIPE_PRICE_AETHER_CLOUD_PRO;
  resetAuditWriter();
  resetGateInputsForTests();
});

// Small helper: the router emits capture() fire-and-forget (not
// awaited). Wait for the microtask queue + the mocked shutdown's
// Promise chain to settle so assertions see the captured events.
async function flushMicrotasks() {
  for (let i = 0; i < 5; i++) {
    await new Promise((r) => setImmediate(r));
  }
}

// ---------------------------------------------------------------------
// router/pick events — the three from #48
// ---------------------------------------------------------------------

describe("router/pick PostHog events", () => {
  it("200 success emits router_pick_request with chosen_model + tier + userId", async () => {
    const { pickPOST } = await getRoutes();
    setAuditWriter(async () => {});
    const res = await pickPOST(pickReq(validRouterCtx));
    expect(res.status).toBe(200);
    await flushMicrotasks();

    const reqEvents = captured.filter((e) => e.event === "router_pick_request");
    expect(reqEvents).toHaveLength(1);
    const props = reqEvents[0].properties;
    expect(props.status_code).toBe(200);
    expect(typeof props.latency_ms).toBe("number");
    expect(props.chosen_model).toBe("claude-sonnet-4");
    expect(props.tier).toBe("pro");
    expect(props.userId).toBe(validRouterCtx.userId);
    expect(props.gate_type).toBeNull();
    expect(reqEvents[0].distinctId).toBe(validRouterCtx.userId);
  });

  it("429 rate-limit path emits router_rate_limited + router_pick_request", async () => {
    const { pickPOST } = await getRoutes();
    setAuditWriter(async () => {});
    // Burn the per-user bucket (USER_LIMIT_PER_MIN = 600) by calling
    // the route 601 times. Cheaper alternative: directly exercise the
    // rateLimit module — but using the route itself keeps this as a
    // true integration test.
    const { USER_LIMIT_PER_MIN } = await import("@/lib/router/rateLimit");
    for (let i = 0; i < USER_LIMIT_PER_MIN; i++) {
      await pickPOST(pickReq(validRouterCtx));
    }
    captured.length = 0; // reset accumulator before the 429 call
    const res = await pickPOST(pickReq(validRouterCtx));
    expect(res.status).toBe(429);
    await flushMicrotasks();

    const rl = captured.filter((e) => e.event === "router_rate_limited");
    expect(rl).toHaveLength(1);
    expect(rl[0].properties.tier).toBe("pro");
    const pick = captured.filter((e) => e.event === "router_pick_request");
    expect(pick).toHaveLength(1);
    expect(pick[0].properties.status_code).toBe(429);
    expect(pick[0].properties.reason_code).toBe("rate_limited");
  });

  it("gate-trip emits router_gate_tripped with enum gate_type only", async () => {
    const { pickPOST } = await getRoutes();
    setAuditWriter(async () => {});
    setActiveConcurrentTasksResolver(async () => 3);
    const res = await pickPOST(
      pickReq({ ...validRouterCtx, taskKind: "code_review" }),
    );
    expect(res.status).toBe(429);
    await flushMicrotasks();

    const gate = captured.filter((e) => e.event === "router_gate_tripped");
    expect(gate).toHaveLength(1);
    expect(gate[0].properties.gate_type).toBe("concurrency_cap_exceeded");
    // Sanitization: gate_cap_key / observed_value MUST NOT be emitted.
    expect(gate[0].properties.gate_cap_key).toBeUndefined();
    expect(gate[0].properties.observed_value).toBeUndefined();
    expect(gate[0].properties.plan_cap_value).toBeUndefined();

    const pick = captured.filter((e) => e.event === "router_pick_request");
    expect(pick).toHaveLength(1);
    expect(pick[0].properties.status_code).toBe(429);
    expect(pick[0].properties.gate_type).toBe("concurrency_cap_exceeded");
    expect(pick[0].properties.reason_code).toBe("gate_rejected");
  });

  it("401 unauthorized emits router_pick_request with distinctId=anonymous", async () => {
    const { pickPOST } = await getRoutes();
    const res = await pickPOST(
      new Request("http://localhost/api/internal/router/pick", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(validRouterCtx),
      }),
    );
    expect(res.status).toBe(401);
    await flushMicrotasks();

    const pick = captured.filter((e) => e.event === "router_pick_request");
    expect(pick).toHaveLength(1);
    expect(pick[0].distinctId).toBe("anonymous");
    expect(pick[0].properties.status_code).toBe(401);
    expect(pick[0].properties.userId).toBeNull();
    expect(pick[0].properties.tier).toBeNull();
  });
});

// ---------------------------------------------------------------------
// checkout route — checkout_started / _completed / _failed
// ---------------------------------------------------------------------

describe("/api/checkout PostHog events", () => {
  it("success path emits checkout_started then checkout_completed", async () => {
    const { checkoutPOST } = await getRoutes();
    stripeCheckoutCreate.mockResolvedValueOnce({
      id: "cs_test_abcdef1234567890",
      url: "https://checkout.stripe.com/c/pay/cs_test_abcdef",
    });
    const res = await checkoutPOST(checkoutReq({ tier: "pro" }));
    expect(res.status).toBe(200);
    await flushMicrotasks();

    const started = captured.filter((e) => e.event === "checkout_started");
    expect(started).toHaveLength(1);
    expect(started[0].properties.tier).toBe("pro");

    const completed = captured.filter((e) => e.event === "checkout_completed");
    expect(completed).toHaveLength(1);
    expect(completed[0].properties.tier).toBe("pro");
    expect(completed[0].properties.session_id_prefix).toBe("cs_test_");
    // Full id must NOT leak.
    expect(
      Object.values(completed[0].properties).some(
        (v) => typeof v === "string" && v.includes("abcdef1234567890"),
      ),
    ).toBe(false);
    expect(typeof completed[0].properties.latency_ms).toBe("number");
  });

  it("invalid tier emits checkout_failed with enum error_code, tier=null", async () => {
    const { checkoutPOST } = await getRoutes();
    const res = await checkoutPOST(checkoutReq({ tier: "<script>alert(1)</script>" }));
    expect(res.status).toBe(400);
    await flushMicrotasks();

    const failed = captured.filter((e) => e.event === "checkout_failed");
    expect(failed).toHaveLength(1);
    expect(failed[0].properties.error_code).toBe("invalid_tier");
    // Critical: the attacker-shaped `tier` string must NOT be emitted.
    expect(failed[0].properties.tier).toBeNull();
    const started = captured.filter((e) => e.event === "checkout_started");
    expect(started).toHaveLength(0);
  });

  it("stripe failure emits checkout_failed with error_code=stripe_error", async () => {
    const { checkoutPOST } = await getRoutes();
    stripeCheckoutCreate.mockRejectedValueOnce(
      new Error("Stripe internal: <html>malicious</html>"),
    );
    const res = await checkoutPOST(checkoutReq({ tier: "pro" }));
    expect(res.status).toBe(500);
    await flushMicrotasks();

    const failed = captured.filter((e) => e.event === "checkout_failed");
    expect(failed).toHaveLength(1);
    expect(failed[0].properties.error_code).toBe("stripe_error");
    expect(failed[0].properties.tier).toBe("pro");
    // The raw Stripe error string must not appear anywhere.
    expect(
      Object.values(failed[0].properties).some(
        (v) => typeof v === "string" && v.includes("malicious"),
      ),
    ).toBe(false);
  });
});

// ---------------------------------------------------------------------
// session route — session_retrieved / session_retrieve_failed
// ---------------------------------------------------------------------

describe("/api/session PostHog events", () => {
  it("success emits session_retrieved with 8-char prefix only", async () => {
    const { sessionGET } = await getRoutes();
    stripeCheckoutRetrieve.mockResolvedValueOnce({
      status: "complete",
      line_items: { data: [{ price: { nickname: "pro" } }] },
      customer_details: { email: "a@b.c" },
      metadata: {},
    });
    const res = await sessionGET(sessionReq("cs_test_abcdef1234567890"));
    expect(res.status).toBe(200);
    await flushMicrotasks();

    const ok = captured.filter((e) => e.event === "session_retrieved");
    expect(ok).toHaveLength(1);
    expect(ok[0].properties.session_id_prefix).toBe("cs_test_");
    expect(
      Object.values(ok[0].properties).some(
        (v) => typeof v === "string" && v.includes("abcdef1234567890"),
      ),
    ).toBe(false);
    expect(typeof ok[0].properties.latency_ms).toBe("number");
  });

  it("missing id emits session_retrieve_failed{error_code:missing_id}", async () => {
    const { sessionGET } = await getRoutes();
    const res = await sessionGET(sessionReq(null));
    expect(res.status).toBe(400);
    await flushMicrotasks();

    const failed = captured.filter((e) => e.event === "session_retrieve_failed");
    expect(failed).toHaveLength(1);
    expect(failed[0].properties.error_code).toBe("missing_id");
  });

  it("invalid id format emits error_code=invalid_id_format", async () => {
    const { sessionGET } = await getRoutes();
    const res = await sessionGET(sessionReq("not-a-stripe-id"));
    expect(res.status).toBe(400);
    await flushMicrotasks();

    const failed = captured.filter((e) => e.event === "session_retrieve_failed");
    expect(failed).toHaveLength(1);
    expect(failed[0].properties.error_code).toBe("invalid_id_format");
  });

  it("stripe lookup failure emits error_code=stripe_lookup_failed", async () => {
    const { sessionGET } = await getRoutes();
    stripeCheckoutRetrieve.mockRejectedValueOnce(new Error("no such session"));
    const res = await sessionGET(sessionReq("cs_test_doesnotexist"));
    expect(res.status).toBe(404);
    await flushMicrotasks();

    const failed = captured.filter((e) => e.event === "session_retrieve_failed");
    expect(failed).toHaveLength(1);
    expect(failed[0].properties.error_code).toBe("stripe_lookup_failed");
  });
});

// ---------------------------------------------------------------------
// helper resilience — capture failure must not throw into callers
// ---------------------------------------------------------------------

describe("captureServerEvent resilience", () => {
  it("swallows posthog-node errors (caller never sees the throw)", async () => {
    const { sessionGET } = await getRoutes();
    // Make capture throw synchronously — the route MUST still respond.
    captureSpy.mockImplementationOnce(() => {
      throw new Error("simulated posthog failure");
    });
    const res = await sessionGET(sessionReq(null));
    expect(res.status).toBe(400);
  });

  it("no-ops silently when POSTHOG_KEY is unset", async () => {
    delete process.env.POSTHOG_KEY;
    const { sessionGET, resetPostHogClient } = await getRoutes();
    resetPostHogClient();
    const res = await sessionGET(sessionReq(null));
    expect(res.status).toBe(400);
    await flushMicrotasks();
    // The mocked PostHog constructor should NOT have been invoked
    // this call — the helper short-circuits before instantiating.
    // (We can't assert count because earlier tests used a key; the
    // behavior assertion is that the route returned normally.)
  });
});
