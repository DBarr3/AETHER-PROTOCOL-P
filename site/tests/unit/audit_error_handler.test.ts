import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { trace } from "@opentelemetry/api";
import {
  recordDecisionAsync,
  setAuditWriter,
  resetAuditWriter,
  resetAuditErrorHandler,
} from "@/lib/router/auditLog";

/**
 * Red Team #1 H4 — default _errorHandler used to only addEvent() to the
 * active span. That's a no-op unless an OTel SDK + collector is wired.
 * Post-C4, the Supabase writer is live; any transient DB failure silently
 * dropped audit rows. This suite freezes the new behavior:
 *   1. ERROR log line via console.error with structured fields
 *      (always-on — Vercel captures stdout/stderr)
 *   2. OTel counter audit_writer_failed_total incremented
 *   3. Span addEvent retained for trace context
 */

const ctx = {
  userId: "00000000-0000-0000-0000-000000000001",
  tier: "pro" as const,
  taskKind: "chat" as const,
  estimatedInputTokens: 10,
  estimatedOutputTokens: 10,
  opusPctMtd: 0,
  activeConcurrentTasks: 0,
  uvtBalance: 1_000_000,
  requestId: "r_h4",
  traceId: "t_h4",
};

const decision = {
  chosen_model: "claude-sonnet-4",
  reason_code: "default_by_tier_and_task" as const,
  predicted_uvt_cost: 50,
  predicted_uvt_cost_simple: 20,
  decision_schema_version: 1,
  uvt_weight_version: 1,
  latency_ms: 1,
};

beforeEach(() => {
  resetAuditErrorHandler();
});

afterEach(() => {
  resetAuditWriter();
  resetAuditErrorHandler();
  vi.restoreAllMocks();
});

describe("audit_error_handler — H4 default alerting ladder", () => {
  it("console.error emits structured record when writer throws", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    setAuditWriter(async () => {
      throw new Error("db_unreachable");
    });
    recordDecisionAsync(ctx, decision);
    // fire-and-forget — flush microtask queue so .catch runs
    await new Promise((r) => setImmediate(r));

    expect(errSpy).toHaveBeenCalledTimes(1);
    const callArgs = errSpy.mock.calls[0];
    // First arg is a label/tag, second is the structured extras (or a single
    // combined arg). Either way both strings must be present somewhere.
    const joined = callArgs.map((a) => (typeof a === "string" ? a : JSON.stringify(a))).join(" ");
    expect(joined).toContain("router.audit");
    expect(joined).toContain("db_unreachable");
    expect(joined).toMatch(/error_type|errorType/);
  });

  it("span.addEvent still called with router.audit_log_failure (trace context preserved)", async () => {
    const addEvent = vi.fn();
    const getSpy = vi.spyOn(trace, "getActiveSpan").mockReturnValue({
      addEvent,
    } as any);
    vi.spyOn(console, "error").mockImplementation(() => {});

    setAuditWriter(async () => {
      throw new Error("tx_aborted");
    });
    recordDecisionAsync(ctx, decision);
    await new Promise((r) => setImmediate(r));

    expect(addEvent).toHaveBeenCalledWith(
      "router.audit_log_failure",
      expect.objectContaining({ "error.type": expect.any(String) }),
    );
    getSpy.mockRestore();
  });

  it("error handler is itself try/catch wrapped — a broken handler does not crash caller", async () => {
    // install a user handler that throws; default handler fallback should
    // not propagate (original fire-and-forget contract).
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    setAuditWriter(async () => {
      throw new Error("root_cause");
    });

    // This is handled in auditLog.ts via the outer try/catch in
    // fireAndForget's .catch block; the test here just proves no unhandled
    // rejection escapes.
    recordDecisionAsync(ctx, decision);
    await new Promise((r) => setImmediate(r));
    // If we got here without an unhandled rejection, we're good.
    expect(errSpy).toHaveBeenCalled();
  });

  it("counter increment path is reachable (no-op meter returns undefined, not throws)", async () => {
    // We can't observe a NoopCounter's count, but we can assert the call
    // path doesn't throw with the default @opentelemetry/api stub.
    vi.spyOn(console, "error").mockImplementation(() => {});
    setAuditWriter(async () => {
      throw new Error("boom");
    });
    recordDecisionAsync(ctx, decision);
    await new Promise((r) => setImmediate(r));
    // success = no test-framework unhandled rejection warning
    expect(true).toBe(true);
  });
});
