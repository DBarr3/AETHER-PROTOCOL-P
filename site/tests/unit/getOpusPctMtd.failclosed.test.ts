import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { trace } from "@opentelemetry/api";
import {
  getOpusPctMtd,
  __clearOpusPctMtdCacheForTests,
} from "@/lib/router/helpers/getOpusPctMtd";

/**
 * Red Team #1 H5 — fail-closed on DB error.
 *
 * Before: catch returned 0 → `0 >= plan.opus_pct_cap = 0.1` is false → gate
 *         passes. A Supabase outage meant Opus was free for everyone.
 * After : catch returns 1.0 (always blocks Opus). If a last-known-good value
 *         exists in cache (from a prior successful call), use that instead
 *         — degraded accuracy beats pure fail-closed, but we never leak into
 *         unlimited-Opus territory.
 */

function makeDeps(rpcImpl: () => Promise<{ data: unknown; error: unknown }>) {
  return {
    supabase: {
      rpc: vi.fn(rpcImpl),
      from: vi.fn(),
    },
  } as unknown as Parameters<typeof getOpusPctMtd>[1];
}

const UID = "00000000-0000-0000-0000-000000000001";

beforeEach(() => {
  __clearOpusPctMtdCacheForTests();
});

describe("getOpusPctMtd — H5 fail-closed on DB error", () => {
  it("returns 1.0 when rpc throws and no last-known-good cache exists", async () => {
    const deps = makeDeps(async () => {
      throw new Error("supabase outage");
    });
    const result = await getOpusPctMtd(UID, deps);
    expect(result).toBe(1.0);
  });

  it("returns 1.0 when rpc.error is set and no cache", async () => {
    const deps = makeDeps(async () => ({ data: null, error: { message: "5xx" } }));
    const result = await getOpusPctMtd(UID, deps);
    expect(result).toBe(1.0);
  });

  it("returns 1.0 when deps.supabase.rpc is absent (no resolver wired)", async () => {
    const deps = { supabase: { from: vi.fn() } } as unknown as Parameters<
      typeof getOpusPctMtd
    >[1];
    const result = await getOpusPctMtd(UID, deps);
    expect(result).toBe(1.0);
  });

  it("returns last-known-good cached value when rpc throws but cache has a prior success", async () => {
    // 1st call: rpc succeeds, returns 0.07 → cached
    const rpc = vi
      .fn()
      .mockResolvedValueOnce({ data: 0.07, error: null })
      .mockRejectedValueOnce(new Error("tx aborted"));
    const deps = {
      supabase: { rpc, from: vi.fn() },
    } as unknown as Parameters<typeof getOpusPctMtd>[1];

    const first = await getOpusPctMtd(UID, deps);
    expect(first).toBe(0.07);

    // Advance clock beyond TTL so the second call goes to rpc (which now fails)
    const deps2 = {
      supabase: { rpc, from: vi.fn() },
      now: () => Date.now() + 60_000,
    } as unknown as Parameters<typeof getOpusPctMtd>[1];

    const second = await getOpusPctMtd(UID, deps2);
    // Should be the last-known-good 0.07, NOT 1.0 (cache beats hard fail-close)
    expect(second).toBe(0.07);
  });

  it("does not fall back to 0 under any error condition (pre-H5 regression guard)", async () => {
    const deps = makeDeps(async () => {
      throw new Error("boom");
    });
    const result = await getOpusPctMtd(UID, deps);
    expect(result).not.toBe(0);
  });

  it("emits OTel event router.opus_pct_mtd_resolver_error on rpc failure", async () => {
    const addEvent = vi.fn();
    const getSpy = vi.spyOn(trace, "getActiveSpan").mockReturnValue({
      addEvent,
      // minimal span shim
    } as any);

    const deps = makeDeps(async () => {
      throw new Error("db down");
    });
    await getOpusPctMtd(UID, deps);

    expect(addEvent).toHaveBeenCalledWith(
      "router.opus_pct_mtd_resolver_error",
      expect.objectContaining({ fallback: "fail_closed" }),
    );
    getSpy.mockRestore();
  });

  it("emits fallback=last_known_good when cache rescues us", async () => {
    const rpc = vi
      .fn()
      .mockResolvedValueOnce({ data: 0.04, error: null })
      .mockRejectedValueOnce(new Error("intermittent"));
    const deps1 = {
      supabase: { rpc, from: vi.fn() },
    } as unknown as Parameters<typeof getOpusPctMtd>[1];
    await getOpusPctMtd(UID, deps1);

    const addEvent = vi.fn();
    const getSpy = vi.spyOn(trace, "getActiveSpan").mockReturnValue({
      addEvent,
    } as any);

    const deps2 = {
      supabase: { rpc, from: vi.fn() },
      now: () => Date.now() + 60_000,
    } as unknown as Parameters<typeof getOpusPctMtd>[1];
    const result = await getOpusPctMtd(UID, deps2);
    expect(result).toBe(0.04);
    expect(addEvent).toHaveBeenCalledWith(
      "router.opus_pct_mtd_resolver_error",
      expect.objectContaining({ fallback: "last_known_good" }),
    );
    getSpy.mockRestore();
  });
});

afterEach(() => {
  __clearOpusPctMtdCacheForTests();
});
