import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { middleware } from "@/middleware";

// ─────────────────────────────────────────────────────────────────
// §2.2 HTTP-Layer PoC — method confusion + matcher behaviour.
//
// Next.js app-router route.ts exports only POST. Middleware runs for
// ALL methods matching /api/internal/:path*. The intent: any method
// without a valid token → 401; any method with a valid token falls
// through to the route which 405s for non-POST.
//
// What we verify here:
//   1. HEAD / OPTIONS / PATCH / DELETE without token → 401 (middleware).
//   2. Matcher is case-sensitive: /api/INTERNAL/router/pick is treated
//      as a DIFFERENT path by Next.js app router, so the file-system
//      route file is NOT reached. Middleware also does not run because
//      matcher strings are case-sensitive. The path 404s. Not a bypass,
//      but a double-negative worth noting: a case-insensitive matcher
//      would be a bypass if any downstream module lowercased paths.
//   3. OPTIONS preflight does NOT skip middleware. There is no OPTIONS
//      allow-list, so CORS preflights from any origin receive 401.
//      This is desirable for an internal endpoint, and documents that
//      there is no accidental CORS allow-origin leak of the token.
// ─────────────────────────────────────────────────────────────────

const GOOD = "method-poc-token";

function req(method: string, headers: Record<string, string> = {}, path = "/api/internal/router/pick"): Request {
  return new Request(`http://localhost${path}`, { method, headers });
}

beforeEach(() => {
  process.env.AETHER_INTERNAL_SERVICE_TOKEN = GOOD;
  process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV = "";
});
afterAll(() => {
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN;
  delete process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV;
});

describe("PoC 2.2 — method confusion + matcher case-sensitivity", () => {
  it.each(["HEAD", "OPTIONS", "PATCH", "DELETE", "PUT", "TRACE"])(
    "no-token %s → 401 via middleware",
    (m) => {
      const r = middleware(req(m));
      expect(r).toBeDefined();
      expect((r as Response).status).toBe(401);
    },
  );

  it("OPTIONS with token → passes middleware (route then 405s)", () => {
    const r = middleware(req("OPTIONS", { "x-aether-internal": GOOD }));
    expect(r).toBeUndefined(); // middleware returns undefined = pass-through
  });

  it("uppercase /api/INTERNAL path → middleware still sees the path as-is", () => {
    // The middleware function has no matcher logic — Next.js decides that.
    // We simply call it with the upper-cased path to confirm it still checks
    // the token. In production Next.js would simply not invoke middleware
    // because the matcher is case-sensitive; the route file also does not
    // exist at the upper-cased path.
    const r = middleware(req("POST", {}, "/api/INTERNAL/router/pick"));
    expect((r as Response).status).toBe(401); // no token still 401s
  });
});
