export const config = { matcher: ["/api/internal/:path*"] };

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export function middleware(req: Request): Response | undefined {
  const header = req.headers.get("x-aether-internal") ?? "";
  const current = process.env.AETHER_INTERNAL_SERVICE_TOKEN ?? "";
  const prev = process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV ?? "";

  const ok =
    (current !== "" && constantTimeEqual(header, current)) ||
    (prev !== "" && constantTimeEqual(header, prev));

  if (!ok) {
    return new Response(JSON.stringify({ error: "unauthorized" }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }
  return undefined;
}
