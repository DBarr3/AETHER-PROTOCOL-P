import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import {
  computeUvtWeighted,
  computeUvtSimple,
  type UvtUsage,
} from "@/lib/uvt/compute";

interface Fixture {
  input: UvtUsage;
  expected_simple: number;
  expected_weighted: number;
}

const FIXTURES_PATH = path.resolve(
  __dirname,
  "../../../tests/parity/fixtures.json",
);

const fixtures: Fixture[] = JSON.parse(
  fs.readFileSync(FIXTURES_PATH, "utf-8"),
);

describe("UVT parity — TS impl vs fixture expected values (100 fixtures)", () => {
  it("fixtures file has exactly 100 entries", () => {
    expect(fixtures.length).toBe(100);
  });

  it("computeUvtSimple matches expected_simple for every fixture", () => {
    const mismatches: { idx: number; got: number; want: number; input: UvtUsage }[] = [];
    fixtures.forEach((f, idx) => {
      const got = computeUvtSimple(f.input);
      if (got !== f.expected_simple) {
        mismatches.push({ idx, got, want: f.expected_simple, input: f.input });
      }
    });
    expect(mismatches).toEqual([]);
  });

  it("computeUvtWeighted matches expected_weighted for every fixture", () => {
    const mismatches: { idx: number; got: number; want: number; input: UvtUsage }[] = [];
    fixtures.forEach((f, idx) => {
      const got = computeUvtWeighted(f.input).uvt_cost;
      if (got !== f.expected_weighted) {
        mismatches.push({ idx, got, want: f.expected_weighted, input: f.input });
      }
    });
    expect(mismatches).toEqual([]);
  });
});
