"""Read-only status of a Report 2 production cohort and the shared ledger (no model calls).

Prints one JSON object with a suggested next action for an operator:
  run_chunk | resolve_killed_branch | recover | audit | done | wait | stop
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.resolve_killed_branch import LEDGER, process_alive  # noqa: E402

PLANNED = 432


def runner_processes() -> list[int]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -match 'run_report2_production' } | "
         "ForEach-Object { $_.ProcessId }"],
        capture_output=True, text=True, check=False)
    return [int(x) for x in out.stdout.split() if x.isdigit()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", type=Path, default=Path("results/report2/history"))
    args = parser.parse_args(argv)
    batch = args.batch_dir if args.batch_dir.is_absolute() else ROOT / args.batch_dir

    complete, incomplete = 0, []
    for p in sorted((batch / "claims").glob("*.json")):
        claim = json.loads(p.read_text(encoding="utf-8"))
        if claim.get("status") == "validated_complete":
            complete += 1
        else:
            incomplete.append({"identity": p.stem, "status": claim.get("status"),
                               "branch_index": claim.get("branch_index")})

    lock = batch / ".kaggle_execution.lock"
    lock_pid = None
    if lock.exists():
        text = lock.read_text(encoding="utf-8").strip()
        lock_pid = int(text) if text.isdigit() else -1

    charged = "CASE WHEN status='settled' THEN actual_nanos ELSE MAX(reserved_nanos,COALESCE(actual_nanos,0)) END"
    with closing(sqlite3.connect(LEDGER.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        attempts, exposure = db.execute(f"SELECT COUNT(*), COALESCE(SUM({charged}),0) FROM attempts").fetchone()
        pending = db.execute("SELECT COUNT(*) FROM attempts WHERE status='pending'").fetchone()[0]
        unheld = db.execute("SELECT COUNT(*) FROM attempts WHERE status='uncertain' "
                            "AND id NOT IN (SELECT attempt_id FROM bounded_holds)").fetchone()[0]

    runners = runner_processes()
    audit = batch / "production_audit.json"
    audit_status = json.loads(audit.read_text(encoding="utf-8")).get("status") if audit.exists() else None
    recoveries = sorted(int(p.name[8:]) for p in batch.glob("recovery*") if p.is_dir() and p.name[8:].isdigit())

    if runners:
        action = "wait"
    elif lock_pid is not None and lock_pid != -1 and process_alive(lock_pid):
        action = "wait"
    elif len(incomplete) > 1 or pending > 1 or unheld > 1 or lock_pid == -1:
        action = "stop"
    elif pending == 1:
        action = "resolve_killed_branch"
    elif incomplete:
        action = "recover"
    elif lock_pid is not None:
        action = "stop"  # stale lock without a pending request is unexpected
    elif complete >= PLANNED:
        action = "done" if audit_status == "production_audited_complete" else "audit"
    else:
        action = "run_chunk"

    print(json.dumps({
        "next_action": action,
        "completed_branches": complete,
        "planned_branches": PLANNED,
        "incomplete_claims": incomplete,
        "lock_pid": lock_pid,
        "runner_processes": runners,
        "ledger_attempts": attempts,
        "ledger_pending": pending,
        "ledger_unheld_uncertain": unheld,
        "project_exposure_credits": round(exposure / 1e9, 9),
        "audit_status": audit_status,
        "next_recovery_folder": f"recovery{(recoveries[-1] if recoveries else 0) + 1}",
        "model_calls_made": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
