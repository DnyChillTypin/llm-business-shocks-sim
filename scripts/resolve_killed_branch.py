"""Resolve a production branch whose process was killed mid-request (no model calls).

A hard kill (closed terminal, Ctrl+C during a request, reboot) leaves two artifacts the
normal recovery path cannot handle: a ledger attempt stuck in status 'pending' and a
stale '.kaggle_execution.lock'. This tool replaces hand-written SQL for that case.

It marks the single stale pending attempt 'uncertain' with reason
'process_interrupted_gateway_outcome_unknown' (a BOUNDED_FAILURES category), keeping
its full reservation, and removes the stale lock. Afterwards use the normal
--prepare-recovery / --activate-and-resume flow, which places the bounded hold.

Dry run by default. --apply additionally requires --attempt-id matching the detected row.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "results/budgets/stage2_pilot_v1.sqlite"
REASON = "process_interrupted_gateway_outcome_unknown"
# Requests time out after 90 seconds; a pending row this old cannot belong to a live request.
MIN_PENDING_AGE = timedelta(minutes=10)


def process_alive(pid: int) -> bool:
    """Windows-safe liveness check (os.kill(pid, 0) terminates processes on Windows)."""
    if sys.platform != "win32":
        import os
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        # ERROR_INVALID_PARAMETER means no such process; anything else (e.g. access denied) fails safe.
        return ctypes.get_last_error() != 87
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def inspect(batch_dir: Path, ledger: Path, now: datetime) -> dict:
    lock = batch_dir / ".kaggle_execution.lock"
    lock_pid = None
    if lock.exists():
        text = lock.read_text(encoding="utf-8").strip()
        lock_pid = int(text) if text.isdigit() else None
        if lock_pid is None or process_alive(lock_pid):
            raise SystemExit(f"Lock {lock} is held by a live or unknown process ({text!r}); do not touch a running batch.")

    with closing(sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        fields = [r[1] for r in db.execute("PRAGMA table_info(attempts)")]
        pending = [dict(zip(fields, r)) for r in db.execute("SELECT * FROM attempts WHERE status='pending'")]
    if len(pending) != 1:
        raise SystemExit(f"Expected exactly one pending attempt, found {len(pending)}; review manually.")
    row = pending[0]
    if row["actual_nanos"] is not None:
        raise SystemExit("Pending attempt already has an actual charge; review manually.")
    age = now - datetime.fromisoformat(row["started_at"])
    if age < MIN_PENDING_AGE:
        raise SystemExit(f"Pending attempt started {age} ago; it may still be live. Wait and re-check.")

    claim_path = batch_dir / "claims" / f"{row['run_id']}.json"
    if not claim_path.exists():
        raise SystemExit(f"Pending attempt run_id {row['run_id']} has no claim in {batch_dir}; wrong batch?")
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    if claim.get("status") == "validated_complete":
        raise SystemExit("Claim for the pending attempt is validated_complete; review manually.")
    return {"lock": str(lock) if lock.exists() else None, "stale_lock_pid": lock_pid,
            "attempt": row, "claim_status": claim.get("status"),
            "branch_index": claim.get("branch_index"), "pending_age_seconds": round(age.total_seconds())}


def record_interrupted_request_finish(batch_dir: Path, run_id: str, attempt_id: str, finished_at: datetime | str) -> bool:
    req_file = batch_dir / "requests" / run_id / "api_attempts.jsonl"
    if not req_file.exists():
        return False
    lines = [line.strip() for line in req_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    started_event = None
    for line in lines:
        ev = json.loads(line)
        if ev.get("event") == "started" and ev.get("attempt_id") == attempt_id:
            started_event = ev
            break
    if started_event is None:
        return False
    for line in lines:
        ev = json.loads(line)
        if ev.get("event") == "finished" and ev.get("attempt_id") == attempt_id:
            return True
    completed_count = sum(1 for line in lines if json.loads(line).get("event") == "finished" and json.loads(line).get("status") == "completed")
    failed_count = sum(1 for line in lines if json.loads(line).get("event") == "finished" and json.loads(line).get("status") == "failed")
    finished_event = {
        **started_event,
        "event": "finished",
        "finished_at_utc": finished_at.isoformat() if isinstance(finished_at, datetime) else str(finished_at),
        "latency_seconds": 0.0,
        "status": "failed",
        "failure_category": REASON,
        "returned_model": None,
        "response_id": None,
        "usage": None,
        "cost_usd": None,
        "cost_source": "https://api.shopaikey.com/pricing",
        "cost_kind": "observed tokens times applicable uncached gateway rates; upper estimate, not independently verified billing",
        "provider_cost_fields": {},
        "parse_status": "not_checked",
        "finish_reasons": [],
        "attempts": started_event.get("attempt_index", completed_count + failed_count + 1),
        "completed": completed_count,
        "failed": failed_count + 1,
        "input_tokens": 0,
        "output_tokens": 0,
        "missing_usage_responses": 1,
    }
    with req_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(finished_event, ensure_ascii=False) + "\n")
    return True


def apply(batch_dir: Path, ledger: Path, found: dict, now: datetime) -> dict:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    receipts = batch_dir / "interruption_receipts"
    receipts.mkdir(exist_ok=True)
    backup = receipts / f"ledger_before_{found['attempt']['id']}_{stamp}.sqlite"
    with closing(sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True)) as src, \
            closing(sqlite3.connect(backup)) as dst:
        src.backup(dst)
    with closing(sqlite3.connect(ledger, timeout=15)) as db:
        with db:
            db.execute("BEGIN IMMEDIATE")
            cur = db.execute(
                "UPDATE attempts SET status='uncertain', finished_at=?, uncertainty_reason=? "
                "WHERE id=? AND status='pending' AND actual_nanos IS NULL",
                (now.isoformat(), REASON, found["attempt"]["id"]))
            if cur.rowcount != 1:
                raise SystemExit("Ledger changed during resolution; nothing applied.")
    if found["lock"]:
        Path(found["lock"]).unlink()
    record_interrupted_request_finish(batch_dir, found["attempt"]["run_id"], found["attempt"]["id"], now)
    receipt = {"status": "pending_attempt_marked_uncertain", "resolved_at_utc": now.isoformat(),
               "reason": REASON,
               "ledger_backup": (backup.relative_to(ROOT) if backup.is_relative_to(ROOT) else backup).as_posix(),
               "removed_stale_lock_pid": found["stale_lock_pid"], "model_calls_made": 0, **found}
    (receipts / f"{found['attempt']['id']}.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch-dir", type=Path, required=True, help="e.g. results/report2/history")
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--attempt-id", help="Required with --apply; must equal the detected pending attempt")
    parser.add_argument("--sync-attempt-log", help="Sync missing finished event to requests/<run_id>/api_attempts.jsonl for an already uncertain attempt")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    batch_dir = (ROOT / args.batch_dir).resolve() if not args.batch_dir.is_absolute() else args.batch_dir
    if args.sync_attempt_log:
        with closing(sqlite3.connect(args.ledger.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            row = db.execute("SELECT id, run_id, finished_at, status, uncertainty_reason FROM attempts WHERE id=?", (args.sync_attempt_log,)).fetchone()
        if not row:
            raise SystemExit(f"Attempt {args.sync_attempt_log} not found in ledger.")
        if row[3] != "uncertain" or row[4] != REASON:
            raise SystemExit(f"Attempt {args.sync_attempt_log} status is not uncertain/{REASON}: {row[3]}/{row[4]}")
        synced = record_interrupted_request_finish(batch_dir, row[1], row[0], row[2])
        print(json.dumps({"status": "synced" if synced else "not_found", "attempt_id": row[0], "run_id": row[1]}, indent=2))
        return 0

    found = inspect(batch_dir, args.ledger, now)
    if not args.apply:
        print(json.dumps({"status": "dry_run", "model_calls_made": 0, **found}, indent=2))
        print(f"\nTo apply: --apply --attempt-id {found['attempt']['id']}")
        return 0
    if args.attempt_id != found["attempt"]["id"]:
        raise SystemExit("--attempt-id does not match the detected pending attempt.")
    print(json.dumps(apply(batch_dir, args.ledger, found, now), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
