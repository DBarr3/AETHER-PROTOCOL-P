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
    requestId: z.string().min(1).max(256),
    traceId: z.string().min(1).max(256),
  })
  .strict();

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function isValidServiceToken(header: string | null): boolean {
  if (!header) return false;
  const current = process.env.AETHER_INTERNAL_SERVICE_TOKEN ?? "";
  const prev = process.env.AETHER_INTERNAL_SERVICE_TOKEN_PREV ?? "";
  return (
    (current !== "" && constantTimeEqual(header, current)) ||
    (prev !== "" && constantTimeEqual(header, prev))
  );
}

export async function POST(req: Request): Promise<Response> {
  assertRouterWired();

  if (!isValidServiceToken(req.headers.get("x-aether-internal"))) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "invalid_json" }, { status: 400 });
  }

  const parse = RoutingContextSchema.safeParse(stripLegacyKeys(body));
  if (!parse.success) {
    return Response.json(
      { error: "validation_failed", details: parse.error.issues },
      { status: 400 },
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
    return Response.json(decision, { status: 200 });
  } catch (e) {
    if (e instanceof RouterGateError) {
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
    return Response.json(
      { error: "internal", trace_id: parse.data.traceId },
      { status: 500 },
    );
  }
}
