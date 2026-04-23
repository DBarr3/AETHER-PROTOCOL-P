import {
  rateCheck,
  IP_LIMIT_PER_MIN,
  RATE_WINDOW_MS,
} from "@/lib/router/rateLimit";
import { isValidServiceTokenHeader } from "@/lib/router/serviceToken";

export const config = { matcher: ["/api/internal/:path*"] };

function getClientIp(req: Request): string {
  // Vercel sets x-forwarded-for; use the first entry (leftmost = original
  // client). Fall back to x-real-ip, then unknown. Unknown requests all
  // share one bucket, which is a tighter limit than per-real-IP.
  const xff = req.headers.get("x-forwarded-for");
  if (xff) return xff.split(",")[0].trim() || "unknown";
  return req.headers.get("x-real-ip") ?? "unknown";
}

export function middleware(req: Request): Response | undefined {
  // Red Team #1 H3 — rate-limit FIRST so even token-brute-forcers can't
  // flood past the limiter. 60 req/IP/min from the RT floor. Counts both
  // auth success and auth failure — this is cost-amplification defense,
  // not auth-bypass defense.
  const ip = getClientIp(req);
  const ipRate = rateCheck(`ip:${ip}`, Date.now(), RATE_WINDOW_MS, IP_LIMIT_PER_MIN);
  if (!ipRate.allowed) {
    return new Response(JSON.stringify({ error: "rate_limited" }), {
      status: 429,
      headers: {
        "content-type": "application/json",
        "retry-after": String(ipRate.retry_after_seconds ?? 60),
      },
    });
  }

  if (!isValidServiceTokenHeader(req.headers.get("x-aether-internal"))) {
    return new Response(JSON.stringify({ error: "unauthorized" }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }
  return undefined;
}
