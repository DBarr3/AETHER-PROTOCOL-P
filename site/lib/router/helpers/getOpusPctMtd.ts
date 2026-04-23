// 30s TTL in-memory cache of (userId → opusPctMtd) + unbounded last-known-good
// cache keyed by userId for fail-closed recovery.
//
// Red Team #1 H5 fix: DB error no longer returns 0 (which was "fail-open" and
// let a Supabase outage hand out unlimited Opus). New behavior:
//   * rpc success           → cache and return the value
//   * rpc error + LKG cache → return cached value (best effort) + emit
//                              router.opus_pct_mtd_resolver_error
//                              with fallback="last_known_good"
//   * rpc error + no LKG    → return 1.0 (blocks Opus hard) + emit
//                              fallback="fail_closed"
//   * rpc absent entirely   → return 1.0 + emit fallback="fail_closed"
//
// Called by the API route BEFORE pick(). Router itself does not fetch —
// opusPctMtd arrives via RoutingContext.

import { trace } from "@opentelemetry/api";

const TTL_MS = 30_000;

interface CacheEntry {
  value: number;
  expiresAt: number;
}

// Short-TTL cache for hot-path hits
const _cache = new Map<string, CacheEntry>();
// Last-known-good cache: never expires until process restart; populated on
// every successful rpc call. Enables best-effort recovery when rpc fails
// transiently without punishing every user with a 1.0 gate during the outage.
const _lkg = new Map<string, number>();

export interface OpusPctMtdDeps {
  supabase: {
    // PromiseLike — the real @supabase/supabase-js client returns
    // PostgrestFilterBuilder from rpc()/from()..., which is thenable but
    // NOT a strict Promise<T>. `await` resolves both the same way.
    rpc?: (fn: string, args: unknown) => PromiseLike<{ data: unknown; error: unknown }>;
    from: (t: string) => {
      select: (cols: string) => {
        eq: (col: string, val: string) => {
          gte: (col: string, val: string) => PromiseLike<{ data: unknown; error: unknown }>;
        };
      };
    };
  };
  now?: () => number;
}

function emitResolverError(
  err: unknown,
  fallback: "fail_closed" | "last_known_good",
): void {
  trace.getActiveSpan()?.addEvent("router.opus_pct_mtd_resolver_error", {
    "error.type": err instanceof Error ? err.name : "unknown",
    fallback,
  });
}

function failFallback(userId: string, err: unknown): number {
  const lkg = _lkg.get(userId);
  if (lkg !== undefined) {
    emitResolverError(err, "last_known_good");
    return lkg;
  }
  emitResolverError(err, "fail_closed");
  return 1.0;
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

  if (!deps.supabase.rpc) {
    // No resolver wired. This is the "dev/test without rpc seed" path; in
    // production this never fires because boot.ts wires the rpc-capable
    // service-role client. Return 1.0 — do NOT fall back to 0.
    return failFallback(userId, new Error("rpc_not_configured"));
  }

  try {
    const { data, error } = await deps.supabase.rpc("rpc_opus_pct_mtd", {
      p_user_id: userId,
    });
    if (error) throw error;
    const value = typeof data === "number" ? data : 0;
    _cache.set(userId, { value, expiresAt: now + TTL_MS });
    _lkg.set(userId, value);
    return value;
  } catch (err) {
    return failFallback(userId, err);
  }
}

export function __clearOpusPctMtdCacheForTests(): void {
  _cache.clear();
  _lkg.clear();
}
