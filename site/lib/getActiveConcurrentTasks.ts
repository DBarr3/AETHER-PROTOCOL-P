// Server-side active-concurrent-tasks helper — the PolicyGate route
// cannot trust a client-supplied activeConcurrentTasks (C3 in
// tests/security/redteam_policygate_report.md).
//
// Shape: count rows in public.tasks where
//   user_id = userId
//   AND status IN ('pending','running')
//   AND created_at ≥ now() - STALE_TASK_WINDOW_MINUTES minutes
// The stale-window floor mirrors lib/pricing_guard.py:_count_active_tasks
// so a crashed worker whose task row never transitioned to 'completed'
// doesn't permanently lock the user out.
//
// TODO(PR 2): the tasks table grows on /agent/run start and transitions
// to a terminal status when the orchestrator finishes or errors. The
// CURRENT wiring (lib/uvt_routes.py + lib/router.py) only writes on
// completion — the "running" window is not always observed. PR 2 must
// ensure public.tasks is INSERTed with status='running' at task start
// and UPDATEd to a terminal state on finish/fail (and expires via the
// stale window on crash). Files that must gain this call site:
//   - lib/uvt_routes.py (start row at /agent/run, update on result)
//   - lib/router.py      (propagate task_id into TokenAccountant.call)
//   - lib/token_accountant.py (writes usage_events with task_id)
// Until PR 2 ships those writes, this helper may under-count (reporting
// 0 when a real task is in-flight); that is safer than over-counting
// because the gate is < cap (strict less-than) — under-count lets a
// legit caller through; over-count would falsely block. C3 is not a
// TOCTOU fix on its own; the architecture doc acknowledges that
// race-proof concurrency is PR 2 scope (Redis semaphore or pg advisory
// lock). What C3 guarantees is that the client cannot lie.

const STALE_TASK_WINDOW_MINUTES = 10;

export interface GetActiveConcurrentTasksDeps {
  supabase: {
    from: (table: string) => {
      select: (cols: string, opts?: { count?: "exact" }) => {
        eq: (col: string, val: string) => {
          in: (col: string, vals: string[]) => {
            gte: (col: string, val: string) => Promise<{
              data: unknown;
              error: unknown;
              count?: number | null;
            }>;
          };
        };
      };
    };
  };
}

function isoMinutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60 * 1000).toISOString();
}

export async function getActiveConcurrentTasks(
  userId: string,
  deps: GetActiveConcurrentTasksDeps,
): Promise<number> {
  const since = isoMinutesAgo(STALE_TASK_WINDOW_MINUTES);
  const { data, error, count } = await deps.supabase
    .from("tasks")
    .select("id", { count: "exact" })
    .eq("user_id", userId)
    .in("status", ["pending", "running"])
    .gte("created_at", since);

  if (error) {
    throw error instanceof Error ? error : new Error(String(error));
  }

  if (typeof count === "number") return count;
  if (Array.isArray(data)) return data.length;
  return 0;
}
