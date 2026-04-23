import { trace, metrics } from "@opentelemetry/api";
import type { RoutingContext, RoutingDecision } from "./types";
import type { RouterGateError } from "./errors";

// Red Team #1 H4 — counter collected by any OTel metrics SDK wired at
// startup. NoopMeter (when no SDK is installed) returns a NoopCounter whose
// .add() is a silent no-op, so this is safe to invoke unconditionally.
// SRE alert (when collected): rate(audit_writer_failed_total[5m])
//   > 0.01 * rate(router_pick_total[5m]) → page.
const _auditMeter = metrics.getMeter("aether.router.audit");
const _auditFailedCounter = _auditMeter.createCounter("audit_writer_failed_total", {
  description:
    "Count of PolicyGate audit-log write failures (routing_decisions INSERT errors, network partitions, RLS mis-config, partition-rollover misses).",
});

export interface RoutingDecisionRow {
  user_id: string;
  request_id: string;
  trace_id: string;
  task_kind: string;
  tier: string;
  chosen_model: string | null;
  reason_code: string;
  gate_error_type: string | null;
  gate_cap_key: string | null;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
  predicted_uvt_cost: number | null;
  predicted_uvt_cost_simple: number | null;
  opus_pct_mtd_snapshot: number;
  active_concurrent_tasks: number;
  uvt_balance_snapshot: number;
  decision_schema_version: number;
  uvt_weight_version: number;
  latency_ms: number;
}

export type AuditWriter = (row: RoutingDecisionRow) => Promise<void>;

const noopWriter: AuditWriter = async () => {};

let _writer: AuditWriter = noopWriter;

// Red Team #1 H4 — the pre-fix default only did span.addEvent(), which is a
// no-op without an OTel SDK wired. Post-C4 the Supabase writer is live and
// any transient failure silently dropped audit rows. New default emits on
// three channels so at least one always surfaces:
//   1. console.error — always-on, stdout/stderr captured by Vercel/journald
//   2. OTel counter   — collected when metrics SDK is wired (Prometheus etc.)
//   3. Span addEvent  — preserves distributed-trace context for the request
// User callers can still override via setAuditErrorHandler() for a Sentry
// hook or similar. The outer try/catch in fireAndForget still guards
// against a user-handler throwing.
const defaultErrorHandler: (err: unknown) => void = (err) => {
  const name = err instanceof Error ? err.name : "unknown";
  const message = err instanceof Error ? err.message : String(err);

  // 1. Always-on log at ERROR level. Intentionally omits row body — that may
  //    contain sensitive context (user_id, trace_id, etc.); only the error
  //    class + message leak, which is fine because both come from the DB
  //    driver, not user input.
  // eslint-disable-next-line no-console
  console.error("[router.audit] writer failed", {
    error_type: name,
    error_message: message,
  });

  // 2. OTel counter (no-op if no SDK wired)
  try {
    _auditFailedCounter.add(1, { "error.type": name });
  } catch {
    // defensive — a counter add should never throw, but if a future meter
    // provider is buggy we don't want to cascade
  }

  // 3. Span context for distributed traces
  trace.getActiveSpan()?.addEvent("router.audit_log_failure", { "error.type": name });
};

let _errorHandler: (err: unknown) => void = defaultErrorHandler;

export function setAuditWriter(writer: AuditWriter): void {
  _writer = writer;
}

export function resetAuditWriter(): void {
  _writer = noopWriter;
}

// Exposes whether the active writer is still the default (noop) writer.
// Used by startupAssertions.assertRouterWired() to fail-closed in
// production when boot.ts could not install the Supabase-backed writer.
export function isAuditWriterDefault(): boolean {
  return _writer === noopWriter;
}

export function setAuditErrorHandler(h: (err: unknown) => void): void {
  _errorHandler = h;
}

export function resetAuditErrorHandler(): void {
  _errorHandler = defaultErrorHandler;
}

function fireAndForget(row: RoutingDecisionRow): void {
  Promise.resolve()
    .then(() => _writer(row))
    .catch((err) => {
      try {
        _errorHandler(err);
      } catch {
        // handler errors are intentionally swallowed — audit must never crash caller
      }
    });
}

export function recordDecisionAsync(
  ctx: RoutingContext,
  d: RoutingDecision,
): void {
  fireAndForget({
    user_id: ctx.userId,
    request_id: ctx.requestId,
    trace_id: ctx.traceId,
    task_kind: ctx.taskKind,
    tier: ctx.tier,
    chosen_model: d.chosen_model,
    reason_code: d.reason_code,
    gate_error_type: null,
    gate_cap_key: null,
    estimated_input_tokens: ctx.estimatedInputTokens,
    estimated_output_tokens: ctx.estimatedOutputTokens,
    predicted_uvt_cost: d.predicted_uvt_cost,
    predicted_uvt_cost_simple: d.predicted_uvt_cost_simple,
    opus_pct_mtd_snapshot: ctx.opusPctMtd,
    active_concurrent_tasks: ctx.activeConcurrentTasks,
    uvt_balance_snapshot: ctx.uvtBalance,
    decision_schema_version: d.decision_schema_version,
    uvt_weight_version: d.uvt_weight_version,
    latency_ms: d.latency_ms,
  });
}

export function recordGateAsync(
  ctx: RoutingContext,
  err: RouterGateError,
  latencyMs: number,
): void {
  fireAndForget({
    user_id: ctx.userId,
    request_id: ctx.requestId,
    trace_id: ctx.traceId,
    task_kind: ctx.taskKind,
    tier: ctx.tier,
    chosen_model: null,
    reason_code: "gate_rejected",
    gate_error_type: err.gateType,
    gate_cap_key: err.gateCapKey,
    estimated_input_tokens: ctx.estimatedInputTokens,
    estimated_output_tokens: ctx.estimatedOutputTokens,
    predicted_uvt_cost: null,
    predicted_uvt_cost_simple: null,
    opus_pct_mtd_snapshot: ctx.opusPctMtd,
    active_concurrent_tasks: ctx.activeConcurrentTasks,
    uvt_balance_snapshot: ctx.uvtBalance,
    decision_schema_version: 1,
    uvt_weight_version: 1,
    latency_ms: latencyMs,
  });
}

// Production wiring — called once at app boot from the API route.
// Kept as a factory so tests don't accidentally hit Supabase.
export function makeSupabaseAuditWriter(
  supabase: { from: (t: string) => { insert: (row: unknown) => Promise<{ error: unknown }> } },
): AuditWriter {
  return async (row: RoutingDecisionRow) => {
    const { error } = await supabase.from("routing_decisions").insert(row);
    if (error) {
      throw error instanceof Error ? error : new Error(String(error));
    }
  };
}
