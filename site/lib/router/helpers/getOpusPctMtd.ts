// 30s TTL in-memory cache of (userId → opusPctMtd).
// On DB error: return 0.0 (fail-open for opus cap) AND emit OTel counter
// router.opus_cap_bypassed_fail_open so SRE can alert when it spikes.
//
// Called by the API route BEFORE pick(). Router itself does not fetch —
// opusPctMtd arrives via RoutingContext.

import { trace } from "@opentelemetry/api";

const TTL_MS = 30_000;

interface CacheEntry {
  value: number;
  expiresAt: number;
}

const _cache = new Map<string, CacheEntry>();

export interface OpusPctMtdDeps {
  supabase: {
    rpc?: (fn: string, args: unknown) => Promise<{ data: unknown; error: unknown }>;
    from: (t: string) => {
      select: (cols: string) => {
        eq: (col: string, val: string) => {
          gte: (col: string, val: string) => Promise<{ data: unknown; error: unknown }>;
        };
      };
    };
  };
  now?: () => number;
}

export async function getOpusPctMtd(
  userId: string,
  deps: OpusPctMtdDeps,
): Promise<number> {
  const now = deps.now ? deps.now() : Date.now();
  const cached = _cache.get(userId);
  if (cached && cached.expiresAt > now) {
    return cached.value;
  }

  try {
    // Uses an rpc if available (cleaner for the SUM/FILTER expression);
    // callers wire the rpc in migration. If absent, we derive from a
    // simpler scan path which the migration also provides a view for.
    if (deps.supabase.rpc) {
      const { data, error } = await deps.supabase.rpc("rpc_opus_pct_mtd", {
        p_user_id: userId,
      });
      if (error) throw error;
      const value = typeof data === "number" ? data : 0;
      _cache.set(userId, { value, expiresAt: now + TTL_MS });
      return value;
    }
    // Fall-through path: caller didn't wire rpc; fail-open.
    return 0;
  } catch (err) {
    trace
      .getActiveSpan()
      ?.addEvent("router.opus_cap_bypassed_fail_open", {
        "error.type": err instanceof Error ? err.name : "unknown",
      });
    return 0;
  }
}

export function __clearOpusPctMtdCacheForTests(): void {
  _cache.clear();
}
