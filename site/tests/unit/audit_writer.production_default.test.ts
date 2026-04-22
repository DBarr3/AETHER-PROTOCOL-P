import { describe, it, expect, beforeEach, afterAll, vi } from "vitest";

// C4 regression guard: importing the route in a process that has the
// Supabase env vars must install a non-noop audit writer. And the
// startup assertion must FAIL in production mode when those env vars
// are missing, so the noop default cannot silently ship.

describe("audit_writer.production_default — Supabase writer wiring at boot", () => {
  beforeEach(() => {
    vi.resetModules();
    delete process.env.SUPABASE_URL;
    delete process.env.SUPABASE_SERVICE_ROLE_KEY;
  });

  afterAll(() => {
    delete process.env.SUPABASE_URL;
    delete process.env.SUPABASE_SERVICE_ROLE_KEY;
  });

  it("wires a non-noop writer when SUPABASE_URL + SERVICE_ROLE_KEY are set", async () => {
    process.env.SUPABASE_URL = "https://fake.supabase.co";
    // 40 alphanum chars — createClient validates loosely so this doesn't throw
    process.env.SUPABASE_SERVICE_ROLE_KEY = "fakeSvcRoleKeyForTestingOnlyABCDEFGHIJKL";

    await import("@/lib/router/boot");
    const audit = await import("@/lib/router/auditLog");

    expect(audit.isAuditWriterDefault()).toBe(false);
  });

  it("assertRouterWired() throws RouterBootFailedError in production when env vars missing", async () => {
    // Ensure env vars are absent.
    delete process.env.SUPABASE_URL;
    delete process.env.SUPABASE_SERVICE_ROLE_KEY;
    const originalNodeEnv = process.env.NODE_ENV;
    // vitest defaults NODE_ENV='test'; flip to 'production' via direct
    // assignment (Object.defineProperty is rejected by the process.env
    // proxy — "only accepts a configurable, writable, and enumerable
    // data descriptor").
    process.env.NODE_ENV = "production";

    try {
      const { assertRouterWired, RouterBootFailedError } = await import(
        "@/lib/router/startupAssertions"
      );
      expect(() => assertRouterWired()).toThrow(RouterBootFailedError);
    } finally {
      process.env.NODE_ENV = originalNodeEnv;
    }
  });

  it("assertRouterWired() does NOT throw in test mode with env vars missing", async () => {
    // NODE_ENV stays 'test' (vitest default). assertRouterWired must be a
    // no-op so dev + CI suites keep working with the noop writer.
    delete process.env.SUPABASE_URL;
    delete process.env.SUPABASE_SERVICE_ROLE_KEY;
    const { assertRouterWired } = await import("@/lib/router/startupAssertions");
    expect(() => assertRouterWired()).not.toThrow();
  });
});
