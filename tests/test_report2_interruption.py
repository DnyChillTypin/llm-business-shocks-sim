"""Incident review retains unknown charges and verifies partial saved trajectories."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.experiments.kaggle_protocol import write
from src.experiments.report2 import create_prefix, run_branch
from src.experiments.report2_fixtures import prepare_case, scripted_policy
from src.research.report2 import PROTOCOL, ROOT, canonical_hash, read_json
from src.research.report2_interruption import file_hashes, reconcile_requests, replay_partial
from src.research.report2_pilot import MODEL


class RequestReconciliationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.rows = [{"id": "ok", "run_id": "branch", "scope": "kaggle", "model": MODEL,
                      "reserved_nanos": 8000000, "actual_nanos": 600000, "status": "settled"},
                     {"id": "timeout", "run_id": "branch", "scope": "kaggle", "model": MODEL,
                      "reserved_nanos": 8000000, "actual_nanos": None, "status": "uncertain",
                      "uncertainty_reason": "api_APITimeoutError_http_unknown"}]
        self.events = []
        for row in self.rows:
            base = {"attempt_id": row["id"], "run_id": "branch", "requested_model": MODEL,
                    "purpose": "pilot", "request_sha256": row["id"],
                    "logical_request_id": "day:2023-05-19:repair:1", "reserved_cost_usd": .008}
            self.events.extend([{**base, "event": "started"},
                                {**base, "event": "finished", "latency_seconds": 90,
                                 "status": "completed" if row["id"] == "ok" else "failed",
                                 "cost_usd": .0006 if row["id"] == "ok" else None,
                                 "usage": {"prompt_tokens": 10} if row["id"] == "ok" else None,
                                 "failure_category": row.get("uncertainty_reason")}])

    def reconcile(self, complete=False):
        (self.folder / "api_attempts.jsonl").write_text("\n".join(json.dumps(e) for e in self.events) + "\n")
        return reconcile_requests(self.folder, self.rows, "branch", complete=complete)

    def test_unknown_charge_remains_a_full_reservation(self):
        result = self.reconcile()
        self.assertEqual(result["model_attempts"], 2)
        self.assertEqual(result["known_credits"], .0006)
        self.assertEqual(result["unknown_charge_reserved_credits"], .008)
        self.assertEqual(result["failed_requests"][0]["attempt_id"], "timeout")
        self.assertIsNone(self.rows[1]["actual_nanos"])

    def test_missing_or_duplicate_finished_attempt_cannot_hide_a_charge(self):
        self.events[-1] = copy.deepcopy(self.events[1])
        with self.assertRaisesRegex(ValueError, "unique cumulative ledger"):
            self.reconcile()

    def test_unknown_charge_cannot_be_counted_as_complete(self):
        with self.assertRaisesRegex(ValueError, "uncertainty"):
            self.reconcile(complete=True)

    def test_fabricated_zero_charge_is_rejected(self):
        self.events[-1]["cost_usd"] = 0
        with self.assertRaisesRegex(ValueError, "uncertainty"):
            self.reconcile()

    def test_altered_reservation_and_other_branch_identity_are_rejected(self):
        for field, value in (("reserved_cost_usd", 0), ("run_id", "another-branch")):
            original = self.events[0][field]
            self.events[0][field] = value
            with self.assertRaisesRegex(ValueError, "identity or conservative reservation"):
                self.reconcile()
            self.events[0][field] = original

    def test_changed_settled_cost_is_rejected(self):
        self.rows[0]["actual_nanos"] += 1
        with self.assertRaisesRegex(ValueError, "charge differs"):
            self.reconcile()


class PartialReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temporary.name)
        cls.protocol = read_json(ROOT / PROTOCOL)
        cls.prepared = prepare_case(cls.protocol["sampling"]["development_cases"][0], cls.folder / "prepared")
        cls.prefix = create_prefix(cls.prepared, cls.folder / "prefix")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def interrupted(self, completed=3):
        run = self.folder / (self._testMethodName + "_branch")
        scripted, _ = scripted_policy(self.protocol["model"])
        calls = 0

        def decide(observation):
            nonlocal calls
            calls += 1
            if calls > completed:
                raise RuntimeError("offline simulated transport interruption")
            return scripted(observation)

        with self.assertRaisesRegex(RuntimeError, "offline simulated"):
            run_branch(self.prepared, self.prefix, run, scenario="delivery_disruption", history="frozen",
                       policy="llm_with_fallback", decide=decide, manual_model_execution=True)
        return run

    def test_partial_replay_keeps_evidence_and_incomplete_status_unchanged(self):
        run = self.interrupted()
        before = file_hashes(run)
        result = replay_partial(self.prepared, self.prefix, run, self.folder / (self._testMethodName + "_replay"))
        self.assertEqual(result["saved_decisions_verified"], 3)
        self.assertFalse(result["included_in_completed_outcomes"])
        self.assertEqual(file_hashes(run), before)
        self.assertEqual(read_json(run / "run_manifest.json")["status"], "incomplete")

    def test_rehashed_partial_observation_edit_fails_independent_replay(self):
        run = self.interrupted()
        path = run / "observations.jsonl"
        records = [json.loads(s) for s in path.read_text().splitlines()]
        records[-1]["observation"]["funds"] += 1
        records[-1]["sha256"] = canonical_hash(records[-1]["observation"])
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        with self.assertRaisesRegex(ValueError, "independent reconstruction"):
            replay_partial(self.prepared, self.prefix, run, self.folder / (self._testMethodName + "_replay"))

    def test_missing_partial_action_cannot_be_silently_ignored(self):
        run = self.interrupted()
        path = run / "actions.jsonl"
        path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
        with self.assertRaisesRegex(ValueError, "interrupted observation"):
            replay_partial(self.prepared, self.prefix, run, self.folder / (self._testMethodName + "_replay"))

    def test_failed_first_decision_has_no_completed_outcome(self):
        run = self.interrupted(completed=0)
        result = replay_partial(self.prepared, self.prefix, run, self.folder / (self._testMethodName + "_replay"))
        self.assertEqual(result["saved_decisions_verified"], 0)
        self.assertIsNone(result["last_saved_decision_date"])

    def test_falsely_completed_partial_manifest_is_rejected(self):
        run = self.interrupted()
        manifest = read_json(run / "run_manifest.json")
        manifest["status"] = "validated_complete"
        write(run / "run_manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "incomplete status"):
            replay_partial(self.prepared, self.prefix, run, self.folder / (self._testMethodName + "_replay"))


if __name__ == "__main__":
    unittest.main()
