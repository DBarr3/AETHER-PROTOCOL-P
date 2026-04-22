import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { POST } from "@/app/api/internal/router/pick/route";
import { resetAuditWriter } from "@/lib/router/auditLog";

// ─────────────────────────────────────────────────────────────────
// §2.5 Audit-Log PoC — the production audit writer is never wired.
//
// `site/lib/router/auditLog.ts` initializes
//   let _writer: AuditWriter = noopWriter;
// and exports setAuditWriter()/makeSupabaseAuditWriter(). The former
// is called only from tests; the latter is exported but never
// instantiated. Production POSTs therefore flow:
//   pick() → recordDecisionAsync() → fireAndForget() → noopWriter
// → routing_decisions receives ZERO inserts.
//
// Net effect: the billing/regulatory audit table is always empty in
// production. Auditors see no decisions, gate-rejection telemetry,
// or latency data. The verification report §12.4 hid this by
// skipping live DB checks.
//
// Severity: CRITICAL (silent total audit gap).
// Fix: wire makeSupabaseAuditWriter(…) at module/app boot, e.g. in a
// new site/lib/router/boot.ts imported from route.ts.
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

const good = {
  userId: "00000000-0000-0000-0000-0000000000dd",
  tier: "pro",
  taskKind: "chat",
  estimatedInputTokens: 100,
  estimatedOutputTokens: 100,
  opusPctMtd: 0,
  activeConcurrentTasks: 0,
  uvtBalance: 1_000_000,
  requestId: "poc-2-5",
  traceId: "poc-2-5",
};

beforeEach(() => {
  process.env.AETHER_INTERNAL_SERVICE_TOKEN = TOKEN;
  process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = "";
  resetAuditWriter(); // returns to the noop default — i.e. production state
});

afterAll(() => {
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV;
});

describe("PoC 2.5 — default (unwired) audit writer silently drops all writes", () => {
  it("route returns 200 with no audit hook invoked", async () => {
    // Replace the default error handler with a spy — if the writer throws
    // (it won't, because it's a noop), we want to see it.
    const errs: unknown[] = [];
    const mod = await import("@/lib/router/auditLog");
    mod.setAuditErrorHandler((e) => errs.push(e));
    mod.resetAuditWriter();

    const res = await POST(post(good));
    expect(res.status).toBe(200);
    await new Promise((r) => setImmediate(r));
    expect(errs.length).toBe(0);
    // No insert, no error — total invisibility to routing_decisions.
  });

  it("text-level verification: route.ts never imports makeSupabaseAuditWriter", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../../../site/app/api/internal/router/pick/route.ts"),
      "utf8",
    );
    expect(src).not.toMatch(/makeSupabaseAuditWriter|setAuditWriter/);
  });
});
