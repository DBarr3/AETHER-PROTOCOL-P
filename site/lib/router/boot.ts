// Side-effect module: installs the production Supabase audit writer.
// Imported for its side effect from site/app/api/internal/router/pick/route.ts.
//
// Behaviour:
//   1. First call to ensureRouterBooted() reads SUPABASE_URL +
//      SUPABASE_SERVICE_ROLE_KEY, constructs a service-role Supabase
//      client, and installs makeSupabaseAuditWriter(client) as the
//      active audit writer.
//   2. Subsequent calls are no-ops (idempotent).
//   3. If either env var is missing or createClient throws, the default
//      noopWriter stays in place and a warning is logged. Production
//      startup-assertion (startupAssertions.ts) will escalate the
//      missing-writer to a hard error on first request.

import { createClient } from "@supabase/supabase-js";
import {
  isAuditWriterDefault,
  makeSupabaseAuditWriter,
  setAuditWriter,
} from "./auditLog";
import {
  setActiveConcurrentTasksResolver,
  setOpusPctMtdResolver,
  setUvtBalanceResolver,
} from "./gateInputs";
import { getOpusPctMtd } from "./helpers/getOpusPctMtd";
import { getUvtBalance } from "@/lib/getUvtBalance";
import { getActiveConcurrentTasks } from "@/lib/getActiveConcurrentTasks";
import {
  assertPlanParity,
  recordPlanParityResult,
} from "./startupAssertions";

let _attempted = false;
let _succeeded = false;

export function ensureRouterBooted(): void {
  if (_attempted) return;
  _attempted = true;

  const url = process.env.SUPABASE_URL?.trim();
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();

  if (!url || !key) {
    console.warn(
      "[router boot] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set — audit writer stays noop",
    );
    return;
  }

  try {
    const supabase = createClient(url, key, {
      auth: { persistSession: false, autoRefreshToken: false },
    });

    // SupabaseClient's generic type depth causes TS2589 ("Type
    // instantiation is excessively deep and possibly infinite") when
    // unifying against the deeply-nested query-builder interfaces we
    // use in the resolver deps (order?().limit().maybeSingle?() chain
    // in GetUvtBalanceDeps, etc.). The runtime object supports every
    // method we call; the cast here narrows to the structural shape
    // each resolver expects without asking TS to do the heavy generic
    // match. Each resolver's own interface still enforces its method
    // contract at the call site inside the fn, which is what matters
    // for test stubs and future refactors.
    //
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const sb = supabase as any;

    setAuditWriter(makeSupabaseAuditWriter(sb));
    setOpusPctMtdResolver((userId) => getOpusPctMtd(userId, { supabase: sb }));
    setUvtBalanceResolver((userId) => getUvtBalance(userId, { supabase: sb }));
    setActiveConcurrentTasksResolver((userId) =>
      getActiveConcurrentTasks(userId, { supabase: sb }),
    );

    // Red Team #1 M5 — fire-and-forget plan-parity check. Records the
    // outcome on the startupAssertions module; assertRouterWired()
    // escalates to 500 in production if the cached result is an error.
    // Intentionally NOT awaited here — boot.ts runs during module import
    // which cannot be async. The first few requests may land before the
    // check completes and will pass through; once the check settles,
    // subsequent requests see the cached result.
    void assertPlanParity(sb as Parameters<typeof assertPlanParity>[0])
      .then(() => recordPlanParityResult(null))
      .catch((err: unknown) => {
        recordPlanParityResult(
          err instanceof Error ? err : new Error(String(err)),
        );
        console.warn(
          `[router boot] plan parity check failed: ${err instanceof Error ? err.message : String(err)}`,
        );
      });

    _succeeded = true;
  } catch (err) {
    const name = err instanceof Error ? err.name : "unknown";
    console.warn(
      `[router boot] Supabase client construction failed (${name}); audit writer stays noop`,
    );
  }
}

// Test-only — lets the audit_writer.production_default test re-run boot
// from a clean slate without spawning a new vitest worker.
export function __resetRouterBootForTests(): void {
  _attempted = false;
  _succeeded = false;
}

export function isRouterBootAttempted(): boolean {
  return _attempted;
}

export function isRouterBootSucceeded(): boolean {
  return _succeeded && !isAuditWriterDefault();
}

// Side-effect wire-up on import. In Next.js serverless the module graph
// is re-evaluated per cold start, so this runs once per lambda instance.
ensureRouterBooted();
