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
import { setOpusPctMtdResolver } from "./gateInputs";
import { getOpusPctMtd } from "./helpers/getOpusPctMtd";

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
    setAuditWriter(makeSupabaseAuditWriter(supabase));
    setOpusPctMtdResolver((userId) => getOpusPctMtd(userId, { supabase }));
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
