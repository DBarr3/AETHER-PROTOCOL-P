import { describe, it, expect, beforeEach, afterAll, vi } from "vitest";
import {
  assertPlanParity,
  PlanParityError,
  __resetPlanParityStateForTests,
  __setPlanParityResultForTests,
  assertRouterWired,
  RouterBootFailedError,
} from "@/lib/router/startupAssertions";
import { setAuditWriter, resetAuditWriter } from "@/lib/router/auditLog";

/**
 * Red Team #1 M5 — PLAN_CAPS ↔ public.plans boot-time parity check.
 *
 * Pre-fix: site/lib/router/constants.ts had comments promising "locked
 * against live public.plans … in startupAssertions.ts" but no such
 * function existed. Silent drift: admin raises Pro's opus_pct_cap from
 * 0.10 to 0.15, the TS constants keep enforcing 0.10, users see wrong
 * gate behavior.
 *
 * Post-fix: startupAssertions.assertPlanParity(supabase) reads all rows
 * from public.plans, compares tier-by-tier against PLAN_CAPS, throws
 * PlanParityError on any mismatch. Boot.ts kicks it off; result caches
 * on the startupAssertions module; assertRouterWired throws in
 * production if the cached result is an error.
 */

// Ground-truth values duplicated here from site/lib/router/constants.ts
// so a test-only rewrite of the constants can't silently drift the
// assertion.
const GROUND_TRUTH = {
  free: {
    uvt_monthly: 15000,
    opus_pct_cap: 0.0,
    concurrency_cap: 1,
    output_cap: 8000,
    sub_agent_cap: 5,
    context_budget_tokens: 8000,
  },
  solo: {
    uvt_monthly: 400000,
    opus_pct_cap: 0.0,
    concurrency_cap: 1,
    output_cap: 16000,
    sub_agent_cap: 8,
    context_budget_tokens: 24000,
  },
  pro: {
    uvt_monthly: 1500000,
    opus_pct_cap: 0.1,
    concurrency_cap: 3,
    output_cap: 32000,
    sub_agent_cap: 15,
    context_budget_tokens: 80000,
  },
  team: {
    uvt_monthly: 3000000,
    opus_pct_cap: 0.25,
    concurrency_cap: 10,
    output_cap: 64000,
    sub_agent_cap: 25,
    context_budget_tokens: 160000,
  },
} as const;

function makeSupabase(rows: Record<string, Record<string, number>>) {
  return {
    from: (t: string) => ({
      select: (_cols: string) => ({
        order: (_col: string) => Promise.resolve({
          data: Object.entries(rows).map(([tier, caps]) => ({ tier, ...caps })),
          error: null,
        }),
      }),
    }),
  } as unknown as Parameters<typeof assertPlanParity>[0];
}

beforeEach(() => {
  __resetPlanParityStateForTests();
});

afterAll(() => {
  __resetPlanParityStateForTests();
});

describe("assertPlanParity — M5 boot-time check", () => {
  it("resolves cleanly when all 4 rows match PLAN_CAPS", async () => {
    const sb = makeSupabase(GROUND_TRUTH);
    await expect(assertPlanParity(sb)).resolves.toBeUndefined();
  });

  it("throws PlanParityError when uvt_monthly drifts on pro", async () => {
    const drifted = {
      ...GROUND_TRUTH,
      pro: { ...GROUND_TRUTH.pro, uvt_monthly: 999_999 },
    };
    const sb = makeSupabase(drifted);
    await expect(assertPlanParity(sb)).rejects.toThrow(PlanParityError);
  });

  it("throws when opus_pct_cap drifts on team (incident-response scenario)", async () => {
    const drifted = {
      ...GROUND_TRUTH,
      team: { ...GROUND_TRUTH.team, opus_pct_cap: 0.35 },
    };
    const sb = makeSupabase(drifted);
    await expect(assertPlanParity(sb)).rejects.toThrow(/opus_pct_cap/);
  });

  it("throws when a tier is missing from the DB", async () => {
    const { free: _drop, ...without_free } = GROUND_TRUTH;
    const sb = makeSupabase(without_free);
    await expect(assertPlanParity(sb)).rejects.toThrow(/missing.*free/);
  });

  it("surfaces Supabase-side error with a wrapped PlanParityError", async () => {
    const sb = {
      from: (_t: string) => ({
        select: (_cols: string) => ({
          order: (_col: string) => Promise.resolve({
            data: null,
            error: { message: "network partition" },
          }),
        }),
      }),
    } as unknown as Parameters<typeof assertPlanParity>[0];
    await expect(assertPlanParity(sb)).rejects.toThrow(/network partition/);
  });
});

describe("assertRouterWired — escalates cached plan parity error in production", () => {
  // vi.stubEnv cleanly toggles NODE_ENV without tripping Node's
  // non-configurable-property guard on process.env.NODE_ENV.
  afterAll(() => {
    vi.unstubAllEnvs();
    resetAuditWriter();
  });

  it("throws PlanParityError in production when the cached result is an error", () => {
    vi.stubEnv("NODE_ENV", "production");
    process.env.SUPABASE_URL = "x";
    process.env.SUPABASE_SERVICE_ROLE_KEY = "y";
    // Non-noop writer so the C4 check (isAuditWriterDefault) passes first
    // and assertRouterWired reaches the M5 plan-parity branch.
    setAuditWriter(async () => {});
    __setPlanParityResultForTests(new PlanParityError("stub mismatch"));
    expect(() => assertRouterWired()).toThrow(PlanParityError);
  });

  it("does NOT throw in test mode even with cached plan parity error", () => {
    vi.stubEnv("NODE_ENV", "test");
    __setPlanParityResultForTests(new PlanParityError("stub mismatch"));
    expect(() => assertRouterWired()).not.toThrow();
  });
});
