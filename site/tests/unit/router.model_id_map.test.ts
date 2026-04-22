import { describe, it, expect } from "vitest";
import { LOGICAL_TO_SHORT, toShortKey } from "@/lib/router/model_id_map";

describe("LOGICAL_TO_SHORT — maps spec names to Python short DB enum keys", () => {
  const expected: Record<string, string> = {
    "claude-haiku-4": "haiku",
    "claude-sonnet-4": "sonnet",
    "claude-opus-4": "opus",
    "gpt-5-mini": "gpt5",
    "gpt-5": "gpt5",
    "perplexity-sonar": "gemma",
  };

  for (const [logical, short] of Object.entries(expected)) {
    it(`${logical} → ${short}`, () => {
      expect(LOGICAL_TO_SHORT[logical]).toBe(short);
    });
  }

  it("toShortKey returns short for known logical name", () => {
    expect(toShortKey("claude-opus-4")).toBe("opus");
  });

  it("toShortKey throws on unknown logical name (fail loud, never default silently)", () => {
    expect(() => toShortKey("gpt-100")).toThrow(/Unknown model_id/);
  });

  it("every short key is in the DB enum (haiku|sonnet|opus|gpt5|gemma)", () => {
    const allowed = new Set(["haiku", "sonnet", "opus", "gpt5", "gemma"]);
    for (const short of Object.values(LOGICAL_TO_SHORT)) {
      expect(allowed.has(short)).toBe(true);
    }
  });
});
