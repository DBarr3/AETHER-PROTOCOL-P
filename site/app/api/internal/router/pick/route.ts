import { z } from "zod";
import { pick } from "@/lib/router/deterministic";
import { RouterGateError } from "@/lib/router/errors";
import "@/lib/router/boot";
import { assertRouterWired } from "@/lib/router/startupAssertions";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

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
    estimatedInputTokens: z.number().int().nonnegative().finite(),
    estimatedOutputTokens: z.number().int().nonnegative().finite(),
    opusPctMtd: z.number().min(0).max(1).finite(),
    activeConcurrentTasks: z.number().int().nonnegative().finite(),
    uvtBalance: z.number().int().nonnegative().finite(),
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

  const parse = RoutingContextSchema.safeParse(body);
  if (!parse.success) {
    return Response.json(
      { error: "validation_failed", details: parse.error.issues },
      { status: 400 },
    );
  }

  try {
    const decision = pick(parse.data);
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
