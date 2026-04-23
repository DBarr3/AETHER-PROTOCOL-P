import { describe, it, expect } from "vitest";
import { ROUTER_CONFIG } from "@/lib/router/config";

/**
 * Red Team #1 M6 — guard the shadow-mode safety net with a CI assertion.
 *
 * ROUTER_CONFIG.shadow_mode === true is the whole premise of PR 1. A bad
 * merge or an over-eager ops edit that flips this to false ships PR-2
 * style enforcement without the prerequisites (C1-C4 fixes + canary
 * rollout plan). This test fails loudly if that happens; it's to be
 * flipped to `false` deliberately as part of the PR 2 commit that
 * enables enforcement.
 */

describe("ROUTER_CONFIG.shadow_mode — PR 1 safety net", () => {
  it("is true on this branch (flip intentionally in PR 2, not by accident)", () => {
    expect(ROUTER_CONFIG.shadow_mode).toBe(true);
  });

  it("canary_user_ids is empty (PR 2 adds the first canary)", () => {
    expect(ROUTER_CONFIG.canary_user_ids).toEqual([]);
  });

  it("the config object is frozen (no runtime mutation path)", () => {
    expect(Object.isFrozen(ROUTER_CONFIG)).toBe(true);
  });
});
