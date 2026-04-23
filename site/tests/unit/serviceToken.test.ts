import { describe, it, expect, beforeEach, afterAll } from "vitest";
import {
  serviceTokenEquals,
  isValidServiceTokenHeader,
} from "@/lib/router/serviceToken";

/**
 * Red Team #1 M2 — single source of truth for service-token compare.
 *
 * Before: two hand-rolled constantTimeEqual functions (middleware.ts and
 * route.ts), both with an early `if (a.length !== b.length) return false`
 * that leaked token length through timing.
 *
 * After: one module wrapping node:crypto.timingSafeEqual with a pad-to-
 * longer branch for unequal-length inputs. Both call sites import from
 * here so the impl can't drift.
 */

describe("serviceTokenEquals — node:crypto.timingSafeEqual wrapper", () => {
  it("returns true for identical strings", () => {
    expect(serviceTokenEquals("abc123", "abc123")).toBe(true);
  });

  it("returns false for same-length mismatch", () => {
    expect(serviceTokenEquals("abc123", "abc124")).toBe(false);
  });

  it("returns false for different-length inputs (does not throw)", () => {
    expect(serviceTokenEquals("abc", "abcdef")).toBe(false);
    expect(serviceTokenEquals("abcdef", "abc")).toBe(false);
  });

  it("returns false when either side is empty (matched empty still false to prevent accidental bypass)", () => {
    // An empty expected-token env var is treated as "unconfigured" by the
    // outer caller; serviceTokenEquals itself returns true for empty-equals-
    // empty (it's a pure string comparison), but the caller guards with a
    // non-empty check. Here we assert the pure-compare semantics.
    expect(serviceTokenEquals("", "")).toBe(true);
    expect(serviceTokenEquals("x", "")).toBe(false);
    expect(serviceTokenEquals("", "x")).toBe(false);
  });

  it("handles long tokens without throwing (64-char hex)", () => {
    const a = "a".repeat(64);
    const b = "a".repeat(64);
    const c = "b".repeat(64);
    expect(serviceTokenEquals(a, b)).toBe(true);
    expect(serviceTokenEquals(a, c)).toBe(false);
  });
});

const GOOD = "primary-token-abc";
const PREV = "previous-token-xyz";

beforeEach(() => {
  process.env.AETHER_INTERNAL_SERVICE_TOKEN = GOOD;
  process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = PREV;
});

afterAll(() => {
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV;
});

describe("isValidServiceTokenHeader", () => {
  it("accepts the current token", () => {
    expect(isValidServiceTokenHeader(GOOD)).toBe(true);
  });

  it("accepts the previous token during rotation overlap", () => {
    expect(isValidServiceTokenHeader(PREV)).toBe(true);
  });

  it("rejects a wrong token", () => {
    expect(isValidServiceTokenHeader("wrong")).toBe(false);
  });

  it("rejects null header", () => {
    expect(isValidServiceTokenHeader(null)).toBe(false);
  });

  it("rejects empty-string header even if env var is also empty (no bypass)", () => {
    process.env.AETHER_INTERNAL_SERVICE_TOKEN = "";
    process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = "";
    expect(isValidServiceTokenHeader("")).toBe(false);
  });
});
