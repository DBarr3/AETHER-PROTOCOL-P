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


def test_manual_replay_script_exists() -> None:
    """Red Team #2 H3 post-fix: a manual replay path exists at
    deploy/replay_dlq.py. A scheduled cron is still Stage K."""
    script = REPO / "deploy" / "replay_dlq.py"
    assert script.exists(), (
        "deploy/replay_dlq.py is missing. The Red Team #2 H3 fix shipped "
        "a manual replay entry point here — if you've relocated it, update "
        "this assertion."
    )
    text = script.read_text(encoding="utf-8")
    # Core interface: dry-run flag + service-role env + rpc_record_usage call.
    assert "--dry-run" in text
    assert "rpc_record_usage" in text


def test_dlq_threshold_alert_wired_in_token_accountant() -> None:
    """Red Team #2 H3 post-fix: the DLQ writer emits a CRITICAL tag
    `DLQ_OVER_THRESHOLD` once the queue crosses
    AETHER_DLQ_ALERT_THRESHOLD. This is the loud-alarm half of the
    'durable billing' fix until Stage K automates replay."""
    text = (REPO / "lib" / "token_accountant.py").read_text(encoding="utf-8")
    assert "DLQ_OVER_THRESHOLD" in text, (
        "Threshold alert tag has been removed from token_accountant. "
        "The H3 fix requires a grep-friendly tag so ops can alert."
    )
    assert "AETHER_DLQ_ALERT_THRESHOLD" in text, (
        "Threshold env var is no longer referenced."
    )
    assert "dlq.size_gauge" in text, (
        "DLQ size-gauge log record is no longer emitted on every enqueue."
    )


def test_release_notes_document_the_fix() -> None:
    """Post-fix RELEASE_NOTES reflects manual replay + threshold alert."""
    rn = (REPO / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    assert "DLQ replay is manual" in rn or "manual replay" in rn.lower()
    assert "replay_dlq.py" in rn
    assert "DLQ_OVER_THRESHOLD" in rn


def test_deploy_script_documents_manual_replay_gap() -> None:
    """deploy/commit-uvt-stack.sh still references the manual-replay state.
    When Stage K's cron lands, that reference will be updated and this
    test may need refreshing."""
    script = (REPO / "deploy" / "commit-uvt-stack.sh").read_text(encoding="utf-8")
    assert "DLQ replay cron (currently manual" in script, (
        "deploy/commit-uvt-stack.sh no longer documents the manual-replay "
        "gap. Assert the replay cron now exists and update this PoC."
    )


if __name__ == "__main__":
    test_manual_replay_script_exists()
    test_dlq_threshold_alert_wired_in_token_accountant()
    test_release_notes_document_the_fix()
    test_deploy_script_documents_manual_replay_gap()
    print("Confirmed: H3 fix in place — manual replay script + threshold "
          "alert + gauge. Stage K cron still pending.")
