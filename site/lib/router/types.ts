export type Tier = "free" | "solo" | "pro" | "team";

export type TaskKind =
  | "chat"
  | "code_gen"
  | "code_review"
  | "research"
  | "summarize"
  | "classify"
  | "agent_plan"
  | "agent_execute";

export interface RoutingContext {
  userId: string;
  tier: Tier;
  taskKind: TaskKind;
  estimatedInputTokens: number;
  estimatedOutputTokens: number;
  opusPctMtd: number;
  activeConcurrentTasks: number;
  uvtBalance: number;
  requestId: string;
  traceId: string;
}

export interface RoutingDecision {
  chosen_model: string;
  reason_code: "default_by_tier_and_task";
  predicted_uvt_cost: number;
  predicted_uvt_cost_simple: number;
  decision_schema_version: number;
  uvt_weight_version: number;
  latency_ms: number;
}
