// Startup assertions run on the first request served by the PolicyGate
// route. They guard against silent production misconfigurations that
// would otherwise only surface as a missing audit trail or a no-op
// gate weeks later.
//
// Contents:
//   - C4: audit writer must be wired in production
//   - M5: PLAN_CAPS must match public.plans row-by-row
//
// Both are wired from boot.ts. assertRouterWired() (called synchronously
// from route.ts before the token check) escalates either failure to a
// 500 in production; in dev/test the same failures log a warning but
// don't block requests.

import { isAuditWriterDefault } from "./auditLog";
import { ensureRouterBooted } from "./boot";
import { PLAN_CAPS, TIERS } from "./constants";

export class RouterBootFailedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RouterBootFailedError";
  }
}

export class PlanParityError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PlanParityError";
  }
}

// ───────────────────────────────────────────────────────────────
// M5 — plan parity
// ───────────────────────────────────────────────────────────────

// Fields in PLAN_CAPS that must match public.plans row-by-row. Kept
// here rather than derived via Object.keys(PLAN_CAPS) so adding a TS-
// only field to PlanCaps (e.g., a feature flag) doesn't accidentally
// widen the DB check.
const PARITY_FIELDS = [
  "uvt_monthly",
  "opus_pct_cap",
  "concurrency_cap",
  "output_cap",
  "sub_agent_cap",
  "context_budget_tokens",
] as const;

// Minimal interface for the subset of the Supabase client we use here.
// Typed loosely so test stubs don't have to implement the full shape.
export interface PlanParitySupabase {
  from: (t: string) => {
    select: (cols: string) => {
      order: (col: string) => Promise<{
        data: Array<Record<string, unknown>> | null;
        error: { message?: string } | null;
      }>;
    };
  };
}

export async function assertPlanParity(
  supabase: PlanParitySupabase,
): Promise<void> {
  const cols =
    "tier, uvt_monthly, opus_pct_cap, concurrency_cap, output_cap, sub_agent_cap, context_budget_tokens";
  const { data, error } = await supabase
    .from("plans")
    .select(cols)
    .order("tier");

  if (error) {
    throw new PlanParityError(
      `plan parity fetch failed: ${error.message ?? "unknown"}`,
    );
  }
  const rows = data ?? [];

  const byTier = new Map<string, Record<string, unknown>>();
  for (const row of rows) {
    if (typeof row.tier === "string") byTier.set(row.tier, row);
  }

  const issues: string[] = [];
  for (const tier of TIERS) {
    const row = byTier.get(tier);
    if (!row) {
      issues.push(`missing tier in plans: ${tier}`);
      continue;
    }
    const expected = PLAN_CAPS[tier];
    // Cast via unknown — PlanCaps has no index signature, so direct cast to
    // Record<string, number> is a TS2352 error in strict mode. The values
    // ARE all numbers; we assert that here.
    const expectedRec = expected as unknown as Record<string, number>;
    for (const key of PARITY_FIELDS) {
      const ev = Number(expectedRec[key]);
      const dv = Number(row[key]);
      if (!Number.isFinite(ev) || !Number.isFinite(dv) || ev !== dv) {
        issues.push(`${tier}.${key}: db=${row[key]} ts=${expectedRec[key]}`);
      }
    }
  }

  if (issues.length > 0) {
    throw new PlanParityError(
      `PLAN_CAPS ↔ public.plans parity mismatch: ${issues.join("; ")}`,
    );
  }
}

// ───────────────────────────────────────────────────────────────
// Cached parity result (populated by boot.ts fire-and-forget path)
// ───────────────────────────────────────────────────────────────

let _planParityResult: Error | null | "unchecked" = "unchecked";

export function recordPlanParityResult(err: Error | null): void {
  _planParityResult = err;
}

export function __resetPlanParityStateForTests(): void {
  _planParityResult = "unchecked";
}

export function __setPlanParityResultForTests(err: Error | null): void {
  _planParityResult = err;
}

// ───────────────────────────────────────────────────────────────
// Synchronous entry point called from route.ts
// ───────────────────────────────────────────────────────────────

export function assertRouterWired(): void {
  ensureRouterBooted();

  const isProd = process.env.NODE_ENV === "production";

  if (isProd && isAuditWriterDefault()) {
    throw new RouterBootFailedError(
      "PolicyGate boot failed: audit writer is still the noop default in " +
        "production. SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set " +
        "on the Vercel project so site/lib/router/boot.ts can wire the " +
        "Supabase-backed writer. See tests/security/redteam_policygate_report.md#C4.",
    );
  }

  // M5 — escalate a cached plan-parity failure in production. Fire-and-
  // forget at boot time means we may get here before the check completes
  // ("unchecked"); in that case we pass through (belt-and-suspenders is
  // better than a hang). Once the check lands, subsequent calls see the
  // cached Error and throw.
  if (isProd && _planParityResult instanceof Error) {
    throw _planParityResult;
  }
}
