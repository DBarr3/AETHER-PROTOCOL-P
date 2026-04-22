"""PoC 2.7 — DLQ (dead-letter queue) has no replay mechanism.

lib/token_accountant.py writes a JSONL line to
$AETHER_USAGE_DLQ (default /var/lib/aethercloud/usage_dlq.jsonl) whenever
`rpc_record_usage` fails. The billing ledger is recoverable only if a
replay job re-executes each line.

But no replay job exists. Evidence:
1. deploy/commit-uvt-stack.sh:254 — "DLQ replay cron (currently manual)"
2. RELEASE_NOTES.md:61 — "No DLQ replay. If rpc_record_usage ever fails,
   events land in /var/lib/aethercloud/usage_dlq.jsonl on VPS2; manual
   replay until Stage K cron lands."
3. deploy/vps2-runbook.md:399 describes the replay job as future work.
4. grep 'replay' lib/  → no matches (no replay function in the module).

So: any `rpc_record_usage` failure produces un-metered inference
permanently. The Anthropic call already completed and returned output to
the user; their UVT balance never decremented; no usage_events row exists
to aggregate into the next month's opus_pct_mtd.

Attack scenarios:

A. Natural: Supabase transient 5xx or connection-pool-exhausted — common
   enough during deploys. Attackers who notice a burst of 5xx in supabase
   status page can time their heaviest requests during those windows.

B. Induced: attacker who can stress the RPC (via other auth'd endpoints
   that hit the same Supabase pool) causes timeout → `rpc_record_usage`
   fails inside TokenAccountant's try/except → DLQ-only. Free inference
   for the duration of the stress.

C. DLQ growth + no alert: vps2-runbook.md:277 says "DLQ file size: ...
   should stay at 0 bytes" but no alert is wired. An operator who
   forgets to check sees the DLQ grow unbounded. Disk-full kills the
   server eventually (availability, not confidentiality).

Severity: HIGH
    - Integrity: every DLQ line is inference the user consumed but
      didn't pay for. Money-adjacent.
    - Detectability: low (no alert, only a runbook mention).
    - Attacker capability: induced variant requires some control over
      Supabase load. Natural variant just requires patience.

Fix (Stage K per release notes — SHOULD land before PR 1 cutover):
    - Write a replay job (systemd timer or Supabase pg_cron) that reads
      DLQ lines, re-fires rpc_record_usage with identical args, and only
      deletes a line on success.
    - Idempotency: add request_id column to rpc_record_usage / add
      unique index on (user_id, task_id, created_at) in usage_events so
      replays can't double-bill.
    - Prometheus alert: DLQ file size > 0 bytes sustained > 5 min.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_no_replay_function_in_lib() -> None:
    """Grep lib/ for any function or module that could replay the DLQ."""
    hits: list[tuple[Path, int, str]] = []
    pat = re.compile(r"\b(replay|reprocess)_(dlq|usage|events?)\b", re.IGNORECASE)
    for path in (REPO / "lib").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in pat.finditer(text):
            line_no = text[: m.start()].count("\n") + 1
            hits.append((path, line_no, m.group(0)))
    assert not hits, (
        "Unexpected: replay hooks found in lib/. If Stage K landed, great — "
        f"update this PoC. Hits: {hits}"
    )


def test_release_notes_confirm_no_replay() -> None:
    rn = (REPO / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    assert "No DLQ replay" in rn, (
        "RELEASE_NOTES.md no longer carries the 'No DLQ replay' caveat. "
        "If replay landed, remove this PoC."
    )


def test_deploy_script_documents_manual_replay_gap() -> None:
    script = (REPO / "deploy" / "commit-uvt-stack.sh").read_text(encoding="utf-8")
    assert "DLQ replay cron (currently manual" in script, (
        "deploy/commit-uvt-stack.sh no longer documents the manual-replay "
        "gap. Assert the replay job now exists and update this PoC."
    )


if __name__ == "__main__":
    test_no_replay_function_in_lib()
    test_release_notes_confirm_no_replay()
    test_deploy_script_documents_manual_replay_gap()
    print("Confirmed: DLQ replay is manual-only. Un-metered inference on "
          "any rpc_record_usage failure persists indefinitely.")
