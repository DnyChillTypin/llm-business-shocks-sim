import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import resolve_killed_branch as tool

SCHEMA = """CREATE TABLE attempts (
    id TEXT PRIMARY KEY, run_id TEXT, scope TEXT, model TEXT,
    reserved_nanos INTEGER, actual_nanos INTEGER, status TEXT,
    input_bound INTEGER, output_bound INTEGER, started_at TEXT,
    finished_at TEXT, uncertainty_reason TEXT)"""


class TestResolveKilledBranch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.batch = base / "history"
        (self.batch / "claims").mkdir(parents=True)
        self.ledger = base / "ledger.sqlite"
        self.now = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute(SCHEMA)
            db.execute("INSERT INTO attempts VALUES ('done','runA','kaggle','m',5,1,'settled',1,1,?,?,NULL)",
                       ((self.now - timedelta(hours=1)).isoformat(), (self.now - timedelta(hours=1)).isoformat()))
            db.execute("INSERT INTO attempts VALUES ('stuck','runB','kaggle','m',7,NULL,'pending',1,1,?,NULL,NULL)",
                       ((self.now - timedelta(minutes=30)).isoformat(),))
        self.claim("runB", "claimed_before_client_creation")

    def tearDown(self):
        self.tmp.cleanup()

    def claim(self, run_id, status):
        (self.batch / "claims" / f"{run_id}.json").write_text(json.dumps({"status": status, "branch_index": 7}))

    def rows(self):
        with closing(sqlite3.connect(self.ledger)) as db:
            return db.execute("SELECT id,status,reserved_nanos,actual_nanos,uncertainty_reason FROM attempts ORDER BY id").fetchall()

    def test_dry_run_detects_without_writing(self):
        before = self.rows()
        found = tool.inspect(self.batch, self.ledger, self.now)
        self.assertEqual(found["attempt"]["id"], "stuck")
        self.assertEqual(found["branch_index"], 7)
        self.assertEqual(self.rows(), before)

    def test_apply_marks_uncertain_keeps_reserve_removes_stale_lock(self):
        lock = self.batch / ".kaggle_execution.lock"
        lock.write_text("424242")
        with patch.object(tool, "process_alive", return_value=False):
            found = tool.inspect(self.batch, self.ledger, self.now)
            receipt = tool.apply(self.batch, self.ledger, found, self.now)
        self.assertIn(("stuck", "uncertain", 7, None, tool.REASON), self.rows())
        self.assertIn(("done", "settled", 5, 1, None), self.rows())
        self.assertFalse(lock.exists())
        self.assertEqual(receipt["model_calls_made"], 0)
        backup = Path(receipt["ledger_backup"])
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(db.execute("SELECT status FROM attempts WHERE id='stuck'").fetchone()[0], "pending")

    def test_refuses_live_lock(self):
        (self.batch / ".kaggle_execution.lock").write_text("424242")
        with patch.object(tool, "process_alive", return_value=True), self.assertRaises(SystemExit):
            tool.inspect(self.batch, self.ledger, self.now)

    def test_refuses_recent_pending(self):
        with self.assertRaises(SystemExit):
            tool.inspect(self.batch, self.ledger, self.now - timedelta(minutes=25))

    def test_refuses_completed_claim_or_missing_claim(self):
        self.claim("runB", "validated_complete")
        with self.assertRaises(SystemExit):
            tool.inspect(self.batch, self.ledger, self.now)
        (self.batch / "claims" / "runB.json").unlink()
        with self.assertRaises(SystemExit):
            tool.inspect(self.batch, self.ledger, self.now)

    def test_refuses_zero_or_multiple_pending(self):
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("INSERT INTO attempts VALUES ('x','runC','kaggle','m',7,NULL,'pending',1,1,?,NULL,NULL)",
                       ((self.now - timedelta(minutes=30)).isoformat(),))
        with self.assertRaises(SystemExit):
            tool.inspect(self.batch, self.ledger, self.now)
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("DELETE FROM attempts WHERE status='pending'")
        with self.assertRaises(SystemExit):
            tool.inspect(self.batch, self.ledger, self.now)

    def test_apply_requires_matching_attempt_id(self):
        with patch.object(tool, "datetime") as dt, self.assertRaises(SystemExit):
            dt.now.return_value = self.now
            dt.fromisoformat = datetime.fromisoformat
            tool.main(["--batch-dir", str(self.batch), "--ledger", str(self.ledger), "--apply", "--attempt-id", "nope"])
        self.assertIn(("stuck", "pending", 7, None, None), self.rows())

    def test_record_interrupted_request_finish(self):
        req_dir = self.batch / "requests" / "runB"
        req_dir.mkdir(parents=True)
        log_file = req_dir / "api_attempts.jsonl"
        log_file.write_text(json.dumps({
            "event": "started", "attempt_id": "stuck", "attempt_index": 1,
            "logical_request_id": "day:1", "run_id": "runB"
        }) + "\n", encoding="utf-8")
        ok = tool.record_interrupted_request_finish(self.batch, "runB", "stuck", self.now)
        self.assertTrue(ok)
        lines = [json.loads(l) for l in log_file.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[1]["event"], "finished")
        self.assertEqual(lines[1]["attempt_id"], "stuck")
        self.assertEqual(lines[1]["status"], "failed")
        self.assertEqual(lines[1]["failure_category"], tool.REASON)


if __name__ == "__main__":
    unittest.main()
