import { z } from "zod";
import { pick } from "@/lib/router/deterministic";
import { RouterGateError } from "@/lib/router/errors";
import "@/lib/router/boot";
import { assertRouterWired } from "@/lib/router/startupAssertions";
import {
  resolveActiveConcurrentTasks,
  resolveOpusPctMtd,
  resolveUvtBalance,
} from "@/lib/router/gateInputs";
import {
  rateCheck,
  RATE_WINDOW_MS,
  USER_LIMIT_PER_MIN,
} from "@/lib/router/rateLimit";
import { isValidServiceTokenHeader } from "@/lib/router/serviceToken";
import { captureServerEvent } from "@/lib/posthog-server";

// Pre-token-validation distinctId for the two early-exit events
// (unauthorized / oversize / invalid_json / validation_failed) — we
// don't have a validated userId yet and must NOT pass raw strings
// into PostHog. "anonymous" keeps those events groupable for the
// router-health dashboard without leaking attacker input.
const ANON_DISTINCT = "anonymous";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Keys the route USED to read from the body but that are now server-
// resolved (C1/C2/C3 in tests/security/redteam_policygate_report.md).
// In-flight callers may still send them; the route strips them before
// Zod validation so `.strict()` does not reject. The values are then
// ignored — resolvers are the only source of truth.
const LEGACY_STRIPPED_BODY_KEYS: readonly string[] = [
  "opusPctMtd",
  "uvtBalance",
  "activeConcurrentTasks",
];

function stripLegacyKeys(obj: unknown): unknown {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return obj;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
    if (!LEGACY_STRIPPED_BODY_KEYS.includes(k)) out[k] = v;
  }
  return out;
}

const RoutingContextSchema = z
  .object({
    userId: z.string().uuid(),
    tier: z.enum(["free", "solo", "pro", "team"]),
    taskKind: z.enum([
      "chat",
      "code_gen",
      "code_review",
      "research",
      "summarize",
      "classify",
      "agent_plan",
      "agent_execute",
    ]),
    // Red Team #1 H2 — defense-in-depth ceiling against integer-overflow audit
    // evasion + general DoS prevention. Claude's context window is 200 k; no
    // legitimate caller needs more than 2 M input tokens. Column-type migration
    // to bigint (20260423_routing_decisions_bigint.sql) is the primary fix;
    // this upper bound rejects over-large requests at the edge before any
    // DB insert happens.
    estimatedInputTokens: z.number().int().nonnegative().max(2_000_000).finite(),
    estimatedOutputTokens: z.number().int().nonnegative().max(2_000_000).finite(),
    // Red Team #1 M4 — restrict to [A-Za-z0-9._:-], 1..128 chars. Covers
    // UUIDs, span IDs, Vercel trace formats; rejects newline/ANSI/control
    // chars that would corrupt routing_decisions audit rows or log
    // dashboards that split on \n. Length ceiling dropped from 256 to 128
    // — no known caller sends longer IDs.
    requestId: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/, {
      message: "requestId must be 1..128 chars of [A-Za-z0-9._:-]",
    }),
    traceId: z.string().regex(/^[A-Za-z0-9._:-]{1,128}$/, {
      message: "traceId must be 1..128 chars of [A-Za-z0-9._:-]",
    }),
  })
  .strict();

// Red Team #1 M2 — constantTimeEqual + isValidServiceToken previously lived
// here AND in middleware.ts. Both have been consolidated into
// @/lib/router/serviceToken (node:crypto.timingSafeEqual under the hood,
// with pad-to-longer on unequal-length inputs so the length branch can't
// be observed via timing).

// Red Team #1 L3 — HTTP body size ceiling. Vercel's default bodyParser
// (App Router) is 4.5 MB; the RoutingContext shape is a few hundred bytes.
// 16 KB gives ample headroom for future fields without inviting any
// realistic large-body DoS.
const BODY_MAX_BYTES = 16_384;

export async function POST(req: Request): Promise<Response> {
  assertRouterWired();

  const startMs = Date.now();

  // Per-request telemetry state filled in as we validate the request.
  // `tier` + `userId` stay null until Zod parses the body; emitting those
  // pre-validation would risk putting attacker-shaped strings into
  // PostHog properties (see sanitization note in PR #35 audit).
  let tier: string | null = null;
  let userId: string | null = null;
  let chosenModel: string | null = null;
  let gateType: string | null = null;
  let reasonCode: string | null = null;

  // Capture the terminal `router_pick_request` event with everything
  // we know at the time the response is built. Follow-on events
  // (`router_gate_tripped`, `router_rate_limited`) are emitted inline
  // where they apply. Telemetry failures are swallowed inside
  // captureServerEvent — they NEVER throw back into the request path.
  const emitRequestEvent = (statusCode: number): Promise<void> => {
    return captureServerEvent(userId ?? ANON_DISTINCT, "router_pick_request", {
      status_code: statusCode,
      latency_ms: Date.now() - startMs,
      // All three of these are either trusted enum/table values or
      // null — never raw user input.
      gate_type: gateType,
      reason_code: reasonCode,
      chosen_model: chosenModel,
      tier,
      // userId is either a Zod-validated UUID or null — safe.
      userId,
    });
  };

  if (!isValidServiceTokenHeader(req.headers.get("x-aether-internal"))) {
    void emitRequestEvent(401);
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  // Red Team #1 L3 — reject oversize bodies BEFORE req.json() materializes
  // them. Trusts the Content-Length header (chunked/missing → fall through
  // to the JSON parser which has its own protections). Legit callers send
  // tiny RoutingContexts; anything over 16 KB is a bug or an attack.
  const cl = req.headers.get("content-length");
  if (cl !== null) {
    const clNum = Number(cl);
    if (Number.isFinite(clNum) && clNum > BODY_MAX_BYTES) {
      void emitRequestEvent(413);
      return Response.json(
        { error: "payload_too_large", limit_bytes: BODY_MAX_BYTES },
        { status: 413 },
      );
    }
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    void emitRequestEvent(400);
    return Response.json({ error: "invalid_json" }, { status: 400 });
  }

  const parse = RoutingContextSchema.safeParse(stripLegacyKeys(body));
  if (!parse.success) {
    void emitRequestEvent(400);
    return Response.json(
      { error: "validation_failed", details: parse.error.issues },
      { status: 400 },
    );
  }

  // Safe to surface now — both are enum/UUID-validated.
  tier = parse.data.tier;
  userId = parse.data.userId;

  // Red Team #1 H3 — per-user rate limit, 600 req/user/min. Runs AFTER Zod
  // so we have a validated userId to key on; the IP bucket (in middleware)
  // already rejected the caller if they tried to flood before validation.
  const userRate = rateCheck(
    `user:${parse.data.userId}`,
    Date.now(),
    RATE_WINDOW_MS,
    USER_LIMIT_PER_MIN,
  );
  if (!userRate.allowed) {
    reasonCode = "rate_limited";
    // Dashboard 1: 429-specific counter.
    void captureServerEvent(userId, "router_rate_limited", {
      tier,
      userId,
    });
    void emitRequestEvent(429);
    return Response.json(
      { error: "rate_limited", retry_after_seconds: userRate.retry_after_seconds },
      {
        status: 429,
        headers: { "retry-after": String(userRate.retry_after_seconds ?? 60) },
      },
    );
  }

  const [opusPctMtd, uvtBalance, activeConcurrentTasks] = await Promise.all([
    resolveOpusPctMtd(parse.data.userId),
    resolveUvtBalance(parse.data.userId),
    resolveActiveConcurrentTasks(parse.data.userId),
  ]);

  try {
    const decision = pick({
      ...parse.data,
      opusPctMtd,
      uvtBalance,
      activeConcurrentTasks,
    });
    // `chosen_model` comes from deterministic.ts's trusted model table
    // lookup and `reason_code` is an internal enum — safe to emit.
    chosenModel = decision.chosen_model ?? null;
    reasonCode = decision.reason_code ?? null;
    void emitRequestEvent(200);
    return Response.json(decision, { status: 200 });
  } catch (e) {
    if (e instanceof RouterGateError) {
      // gateType is a class-level readonly string on each RouterGateError
      // subclass — never derived from user input. See errors.ts.
      gateType = e.gateType;
      reasonCode = "gate_rejected";
      // Dashboard 1: gate-rejection counter. NOTE we deliberately do
      // NOT include gate_cap_key / observed_value / plan_cap_value
      // here — those can contain attacker-shaped strings per the
      // PR #35 sanitization audit. gate_type (enum) is sufficient
      // for the dashboard's rejection-reason breakdown.
      void captureServerEvent(userId, "router_gate_tripped", {
        gate_type: gateType,
        tier,
        userId,
      });
      void emitRequestEvent(e.httpStatus);
      return Response.json(
        {
          error: "router_gate",
          gate_type: e.gateType,
          user_message_code: e.userMessageCode,
          gate_cap_key: e.gateCapKey,
          plan_cap_value: e.planCapValue,
          observed_value: e.observedValue,
          trace_id: parse.data.traceId,
        },
        { status: e.httpStatus },
      );
    }
    reasonCode = "internal_error";
    void emitRequestEvent(500);
    return Response.json(
      { error: "internal", trace_id: parse.data.traceId },
      { status: 500 },
    );
  }
}
