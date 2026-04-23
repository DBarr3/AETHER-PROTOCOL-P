// In-process sliding-window rate limiter (Red Team #1 H3).
//
// Per-instance defense-in-depth: Vercel serverless has per-region instance
// fan-out, so the effective cluster limit is instance_count × per_instance.
// That's fine for PR 1 — the red-team's concern is "nothing exists today,"
// not "existing limit is too loose." Upgrade path: swap the Map for Upstash
// Redis + replace rateCheck() body with an atomic INCR + TTL script.
//
// Usage:
//   const r = rateCheck(`ip:${ip}`, Date.now(), 60_000, 60);
//   if (!r.allowed) return 429 with `retry-after: r.retry_after_seconds`
//
// Keys should be prefixed by bucket type ("ip:", "user:", etc.) so a single
// userId accidentally matching an IP can't cross-pollinate the buckets.

export interface RateLimitResult {
  allowed: boolean;
  retry_after_seconds?: number;
}

const _buckets = new Map<string, number[]>();

export function rateCheck(
  key: string,
  nowMs: number,
  windowMs: number,
  limit: number,
): RateLimitResult {
  const cutoff = nowMs - windowMs;
  const prior = _buckets.get(key) ?? [];
  // Drop expired entries eagerly so we don't leak memory on idle keys.
  const fresh: number[] = [];
  for (const t of prior) {
    if (t > cutoff) fresh.push(t);
  }

  if (fresh.length >= limit) {
    const oldest = fresh[0];
    const retry = Math.max(1, Math.ceil((oldest + windowMs - nowMs) / 1000));
    _buckets.set(key, fresh);
    return { allowed: false, retry_after_seconds: retry };
  }

  fresh.push(nowMs);
  _buckets.set(key, fresh);
  return { allowed: true };
}

export function __resetRateLimitForTests(): void {
  _buckets.clear();
}

// Default floors recommended by the red-team remediation report. Exported
// as constants so middleware + route share one source of truth.
export const IP_LIMIT_PER_MIN = 60;
export const USER_LIMIT_PER_MIN = 600;
export const RATE_WINDOW_MS = 60_000;
