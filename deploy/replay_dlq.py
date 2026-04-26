"""Manual DLQ replay — re-fires rpc_record_usage for every event buffered
in $AETHER_USAGE_DLQ (default /var/lib/aethercloud/usage_dlq.jsonl).

Red Team Sweep #2 High finding H3: the DLQ path has been live since
Stage A but no replay job existed. Any rpc_record_usage failure buffered
the event to JSONL forever — un-metered inference with no billing
reconciliation. This script closes the gap as an operator-on-demand
tool until Stage K automates it.

USAGE:
    # Dry run — report what WOULD be replayed without calling Supabase.
    python deploy/replay_dlq.py --dry-run

    # Live replay against the configured service-role client.
    SUPABASE_URL=https://... SUPABASE_SERVICE_ROLE_KEY=... \
        python deploy/replay_dlq.py

    # Replay from an alternate DLQ file (testing / post-incident triage).
    AETHER_USAGE_DLQ=/tmp/incident-dlq.jsonl python deploy/replay_dlq.py

BEHAVIOR:
    - Reads DLQ line-by-line. Each line is a JSON event dict with the
      keys rpc_record_usage expects (user_id, task_id, model,
      input_tokens, output_tokens, cached_input_tokens,
      cost_usd_cents_fractional, qopc_load).
    - For each line: call rpc_record_usage via the service-role client.
        • success → remove that line from the DLQ (rewrite the file
          without it).
        • failure → leave the line; record the error. The line will be
          retried on the next invocation.
    - At the end prints a summary: attempted / succeeded / still-failing.

IDEMPOTENCY GAP (noted in redteam_modelrouter_report.md H3 fix section):
    rpc_record_usage does NOT have a request_id idempotency key today.
    Replaying a line that actually DID succeed on the original call (but
    the HTTP response got lost) would double-bill. This script is
    conservative — it only runs events that the original call recorded
    as failures (they're in the DLQ because rpc_record_usage either
    threw or reported a non-None error). Operators should cross-check
    the daily aggregate against the expected delta before running.
    Stage K is where the idempotency work lands; until then, this
    script is "run carefully, eyes on the output."

DO NOT WIRE THIS INTO CRON UNTIL:
    1. rpc_record_usage gains `p_request_id uuid` with a unique index
       on (user_id, request_id) in usage_events.
    2. The DLQ writer in lib/token_accountant.py:_append_to_dlq also
       writes that request_id so the replay can carry it through.
    3. An integration test covers the "mid-RPC network failure" case
       to prove double-billing is prevented.

Aether Systems LLC — Patent Pending
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


DEFAULT_DLQ_PATH = Path("/var/lib/aethercloud/usage_dlq.jsonl")
SUPPORTED_KEYS = (
    "user_id", "task_id", "model",
    "input_tokens", "output_tokens", "cached_input_tokens",
    "cost_usd_cents_fractional", "qopc_load",
    "reasoning_tokens", "cache_write_tokens",
)

# Keys that must default to 0 when absent from old DLQ event shapes (Phase 0).
_INTEGER_DEFAULTS: dict[str, int] = {
    "reasoning_tokens": 0,
    "cache_write_tokens": 0,
}


def _dlq_path() -> Path:
    return Path(os.environ.get("AETHER_USAGE_DLQ", str(DEFAULT_DLQ_PATH)))


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f if ln.strip()]


def _write_lines(path: Path, lines: list[str]) -> None:
    """Atomic rewrite: write to tempfile + os.replace. Protects against
    crashes mid-write from half-truncating the DLQ file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")
    os.replace(tmp, path)


def _build_service_client():
    """Construct a sync supabase-py client with service_role credentials.
    Raises SystemExit with a clear message if env is incomplete."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print(
            "ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must both be set "
            "for live replay. Use --dry-run to inspect the DLQ without calling "
            "Supabase.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        from supabase import create_client  # type: ignore
    except ImportError as exc:
        print(
            f"ERROR: supabase-py is not importable ({exc}). On VPS2 the Python "
            "orchestrator already has it installed; run this script from the "
            "same virtualenv.",
            file=sys.stderr,
        )
        raise SystemExit(3)
    return create_client(url, key)


def _replay_one(client, event: dict) -> str | None:
    """Fire rpc_record_usage for a single DLQ event.
    Returns None on success; an error string on failure."""
    try:
        params = {
            f"p_{k}": event.get(k, _INTEGER_DEFAULTS.get(k))
            for k in SUPPORTED_KEYS
        }
        resp = client.rpc("rpc_record_usage", params).execute()
        err = getattr(resp, "error", None)
        if err:
            return f"rpc returned error: {err}"
    except Exception as exc:  # noqa: BLE001 — we want to keep going on other rows
        return str(exc)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manual replay of usage_dlq.jsonl — Red Team #2 H3."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse the DLQ and report what would be replayed; do not hit Supabase.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print one line per event (default: summary only).",
    )
    args = parser.parse_args()

    path = _dlq_path()
    lines = _read_lines(path)
    print(f"DLQ: {path}")
    print(f"Queued events: {len(lines)}")

    if not lines:
        print("Nothing to replay.")
        return 0

    if args.dry_run:
        for ln in lines:
            try:
                ev = json.loads(ln)
                uid = ev.get("user_id", "?")
                model = ev.get("model", "?")
                uvt = max(0, int(ev.get("input_tokens", 0)) - int(ev.get("cached_input_tokens", 0))) + int(ev.get("output_tokens", 0))
                print(f"  user={uid[:8] if uid else '?'}… model={model} uvt~{uvt}")
            except Exception as exc:  # noqa: BLE001
                print(f"  <unparseable: {exc}>")
        return 0

    client = _build_service_client()
    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []

    for ln in lines:
        try:
            ev = json.loads(ln)
        except json.JSONDecodeError as exc:
            failed.append((ln, f"unparseable: {exc}"))
            continue
        err = _replay_one(client, ev)
        if err is None:
            succeeded.append(ln)
            if args.verbose:
                print(f"  OK    user={ev.get('user_id', '?')[:8]}… model={ev.get('model')}")
        else:
            failed.append((ln, err))
            if args.verbose:
                print(f"  FAIL  {err}")

    # Rewrite the DLQ with only the failed lines remaining.
    _write_lines(path, [ln for (ln, _) in failed])

    print()
    print(f"Attempted: {len(lines)}")
    print(f"Succeeded: {len(succeeded)}")
    print(f"Still in DLQ: {len(failed)}")
    if failed:
        print()
        print("First 3 failure reasons:")
        for ln, err in failed[:3]:
            print(f"  {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
