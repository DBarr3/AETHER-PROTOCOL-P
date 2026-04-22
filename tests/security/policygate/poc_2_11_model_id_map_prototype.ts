import { describe, it, expect } from "vitest";
import { LOGICAL_TO_SHORT, toShortKey } from "@/lib/router/model_id_map";
import { MODEL_MULTIPLIERS_V1 } from "@/lib/uvt/weights.v1";

// ─────────────────────────────────────────────────────────────────
// §2.11 Model-ID-Map PoC — prototype chain lookups are not .throw()-
// guarded in the hand-rolled lookup; toShortKey() raises correctly,
// but MODEL_MULTIPLIERS_V1[model_id] in compute.ts returns
// Object.prototype.<method> for names like "toString" when model_id
// is attacker-controlled. In PR 1 this is dead code (model always
// comes from DEFAULT_MODEL_BY_TIER_AND_TASK), but the PR 2
// `requestedModel` override would activate it.
//
// Severity: LOW today, HIGH when PR 2 ships. Fix: use
// Object.hasOwn(MAP, key) guard or Map<string, number> instead of
// a plain object.
// ─────────────────────────────────────────────────────────────────

describe("PoC 2.11 — prototype-chain escape in a plain-object lookup", () => {
  it("LOGICAL_TO_SHORT['toString'] returns the Object.prototype.toString function", () => {
    // This is the classical vulnerability: a bare-object lookup is
    // indistinguishable from a prototype-inherited method.
    const value = (LOGICAL_TO_SHORT as Record<string, unknown>)["toString"];
    expect(typeof value).toBe("function");
  });

  it("toShortKey('toString') — currently throws because the guard checks short === undefined", () => {
    // toShortKey guards via `if (short === undefined)`. Object.prototype
    // methods are not undefined, so they bypass the guard. We assert the
    // current broken behaviour to lock the regression in place — fix is
    // to swap the guard for Object.hasOwn.
    // NOTE: because `LOGICAL_TO_SHORT` is typed `Record<string,string>`
    // the TS type-check won't catch this; it's a runtime issue.
    let caught: unknown = null;
    try { toShortKey("toString"); } catch (e) { caught = e; }
    // If this ever starts throwing (fix landed), flip the assertion.
    expect(caught).toBeNull();
  });

  it("MODEL_MULTIPLIERS_V1['toString'] returns a function (would make ceil() NaN)", () => {
    const mult = (MODEL_MULTIPLIERS_V1 as Record<string, unknown>)["toString"];
    expect(typeof mult).toBe("function");
    // In compute.ts: `const mult = MODEL_MULTIPLIERS_V1[id];
    //                 if (mult === undefined) throw;`
    // mult is a function, not undefined → no throw. Then
    // pre_multiplier_subtotal * mult coerces to NaN, which Math.ceil
    // returns as NaN, and the eventual `enforced > ctx.uvtBalance` is
    // false (NaN comparisons are false), so the gate would PASS on
    // zero-cost for any attacker who can influence model_id. Today
    // model_id is always trusted; flag for PR 2 requestedModel.
  });
});
