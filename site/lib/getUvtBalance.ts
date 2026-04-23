// Server-side UVT balance helper — the PolicyGate route cannot trust a
// client-supplied uvtBalance (C2 in tests/security/redteam_policygate_report.md).
//
// Shape: returns the user's REMAINING UVT for the current period.
//   remaining = max(0, plan.uvt_monthly - uvt_balances.total_uvt_latest)
//
// Source of truth parity:
//   - lib/token_accountant.py writes usage_events + uvt_balances via
//     rpc_record_usage (see aethercloud/supabase/migrations/20260421_uvt_accounting.sql:154+).
//     total_uvt on the most-recent uvt_balances row is what the Python
//     PricingGuard reads too (_fetch_monthly_uvt in lib/pricing_guard.py).
//   - plans.uvt_monthly is the authoritative quota per tier
//     (aethercloud/supabase/migrations/20260421_uvt_accounting.sql:13+).
//
// On any error: throw. The route has no outer catch around this resolver,
// so a DB failure surfaces as a 500 to the caller — explicitly NOT a
// fail-open (which would mean "unlimited balance during DB outage").

// PromiseLike — the real @supabase/supabase-js query builder is thenable
// but NOT a strict Promise<T> (lacks .catch / .finally / Symbol.toStringTag).
// Using Promise<T> here caused TS2589 "Type instantiation is excessively
// deep" when SupabaseClient was passed as the arg; PromiseLike is the
// documented escape hatch.
export interface GetUvtBalanceDeps {
  supabase: {
    from: (table: string) => {
      select: (cols: string) => {
        eq: (col: string, val: string) => {
          order?: (col: string, opts: { ascending: boolean }) => {
            limit: (n: number) => {
              maybeSingle?: () => PromiseLike<{ data: unknown; error: unknown }>;
            };
          };
          single?: () => PromiseLike<{ data: unknown; error: unknown }>;
          maybeSingle?: () => PromiseLike<{ data: unknown; error: unknown }>;
        };
      };
    };
  };
}

interface UserRow {
  tier: string;
}
interface PlanRow {
  uvt_monthly: number | string;
}
interface BalanceRow {
  total_uvt: number | string;
}

function asNumber(value: unknown, label: string): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const n = Number(value);
    if (Number.isFinite(n)) return n;
  }
  throw new Error(`getUvtBalance: non-numeric ${label}: ${String(value)}`);
}

export async function getUvtBalance(
  userId: string,
  deps: GetUvtBalanceDeps,
): Promise<number> {
  // 1. User → tier
  const userQuery = deps.supabase.from("users").select("tier").eq("id", userId);
  const { data: userData, error: userErr } = await (userQuery.single
    ? userQuery.single()
    : userQuery.maybeSingle!());
  if (userErr) {
    throw userErr instanceof Error ? userErr : new Error(String(userErr));
  }
  const userRow = userData as UserRow | null;
  if (!userRow) {
    throw new Error(`getUvtBalance: user ${userId} not found`);
  }

  // 2. Plan → uvt_monthly
  const planQuery = deps.supabase.from("plans").select("uvt_monthly").eq("tier", userRow.tier);
  const { data: planData, error: planErr } = await (planQuery.single
    ? planQuery.single()
    : planQuery.maybeSingle!());
  if (planErr) {
    throw planErr instanceof Error ? planErr : new Error(String(planErr));
  }
  const planRow = planData as PlanRow | null;
  if (!planRow) {
    throw new Error(`getUvtBalance: plan for tier ${userRow.tier} not found`);
  }
  const cap = asNumber(planRow.uvt_monthly, "plans.uvt_monthly");

  // 3. uvt_balances → most-recent period's total_uvt (0 if no row yet)
  const balQuery = deps.supabase
    .from("uvt_balances")
    .select("total_uvt")
    .eq("user_id", userId);
  const ordered = balQuery.order
    ? balQuery.order("period_started_at", { ascending: false })
    : null;
  let consumed = 0;
  if (ordered) {
    const limited = ordered.limit(1);
    const { data: balData, error: balErr } = await (limited.maybeSingle
      ? limited.maybeSingle()
      : Promise.resolve({ data: null, error: null }));
    if (balErr) {
      throw balErr instanceof Error ? balErr : new Error(String(balErr));
    }
    if (balData) {
      consumed = asNumber((balData as BalanceRow).total_uvt, "uvt_balances.total_uvt");
    }
  }

  return Math.max(0, Math.floor(cap - consumed));
}
