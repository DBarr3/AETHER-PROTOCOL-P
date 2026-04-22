// Startup assertions run on the first request served by the PolicyGate
// route. They guard against silent production misconfigurations that
// would otherwise only surface as a missing audit trail or a no-op
// gate weeks later.
//
// M5 deliberately named this file; it currently holds only the audit-
// writer assertion (C4). plan-cap parity (M5 full scope) lands later
// as a Medium-severity follow-up.

import { isAuditWriterDefault } from "./auditLog";
import { ensureRouterBooted } from "./boot";

export class RouterBootFailedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RouterBootFailedError";
  }
}

export function assertRouterWired(): void {
  ensureRouterBooted();

  if (process.env.NODE_ENV === "production" && isAuditWriterDefault()) {
    throw new RouterBootFailedError(
      "PolicyGate boot failed: audit writer is still the noop default in " +
        "production. SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set " +
        "on the Vercel project so site/lib/router/boot.ts can wire the " +
        "Supabase-backed writer. See tests/security/redteam_policygate_report.md#C4.",
    );
  }
}
