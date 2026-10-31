"""Continuation keeps prior evidence and schedules each unfinished branch at most once."""
import copy
import json
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from budget_fixture import manifest as mock_allowance
from src.benchmarks.budget import BudgetLedger
from src.experiments.kaggle_protocol import write
from src.research.report2 import ROOT, PROTOCOL, canonical_hash, read_json
from src.research.report2_pilot import current_allowance, fingerprint
from src.research.report2_development import (SOURCES, prepare, verify, activate, active_state,
                                            identity, run_pending, validate_update, audit)


class DevelopmentContinuationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in SOURCES:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        protocol = read_json(ROOT / PROTOCOL)
        self.plan = {"task_id": "report2:development", "implementation_sha256": "mock_only", "episodes": [
            {"case_id": case["id"], "scenario": scenario, "history": history, "realization": 0}
            for case in protocol["sampling"]["development_cases"]
            for scenario in protocol["branching"]["conditions"] for history in protocol["policies"]["history_variants"]]}
        self.envelope = mock_allowance(cap=20, attempts=3000)
        self.envelope.update(scope_caps_usd={"native": 4.2, "kaggle": 11.8},
                             allowed_tasks=["legacy:task", "report2:development"],
                             allowed_purposes=["pilot", "evaluation"],
                             bounded_unknown_failure_categories=["missing_usage"])
        self.old = copy.deepcopy(self.envelope)
        self.old["scope_caps_usd"]["kaggle"] = .8
        self.old["max_attempts"] = 100
        self.path = self.root / "results/budgets/mock_only.sqlite"
        self.ledger = BudgetLedger(self.old, self.path, run_id="historic", scope="kaggle")
        self.ledger.reserve("held_old", "test", 100, 10)
        self.ledger.settle("held_old", uncertain_reason="missing_usage")
        self.ledger.retain_bounded_failed_charge("held_old", "offline fixture retained hold")
        first_ledger = BudgetLedger(self.old, self.path, run_id=identity(self.plan, 0), scope="kaggle")
        for index in range(19):
            first_ledger.reserve(f"first_{index}", "gpt-4.1-mini-2025-04-14", 10, 2)
            first_ledger.settle(f"first_{index}", input_tokens=10, output_tokens=2)
        db = sqlite3.connect(self.path)
        db.execute("CREATE TABLE allowance_amendments (at TEXT, previous_manifest TEXT, new_manifest TEXT)")
        db.execute("INSERT INTO allowance_amendments VALUES (?,?,?)", ("fixture", json.dumps(self.envelope), json.dumps(self.old)))
        db.commit()
        db.close()
        self.first = self.root / "results/report2/first"
        for name, value in (("proposal.json", {"old_allowance": self.envelope}),
                            ("approved_budget.json", self.old), ("approved_authorization.json", {"fixture": True}),
                            ("pilot_audit.json", {"fixture": True}), ("gateway_snapshot.json", {"fixture": True})):
            write(self.first / name, value)
        self.batch = self.root / "results/report2/manual_development"
        write(self.batch / "claims" / f"{identity(self.plan, 0)}.json", {"status": "validated_complete",
              "episode": self.plan["episodes"][0],
              "budget_sha256": fingerprint(self.old), "authorization_sha256": canonical_hash({"fixture": True})})
        self.folder = self.root / "results/report2/continuation"
        self.folder.mkdir(parents=True)
        self.snapshot = {"provider": "ShopAIKey", "base_url": "https://api.shopaikey.com/v1", "rates_verified": True,
                         "paid_api_calls": 0, "missing_models": [], "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                         "pricing_version": "fixture", "rates": copy.deepcopy(self.old["rates"]), "balance": {"remaining": 10}}
        self.addCleanup(patch.stopall)
        patch("src.research.report2_development.verify_implementation", return_value={}).start()
        patch("src.experiments.report2.development_plan", return_value=self.plan).start()
        patch("src.research.report2_development.audit_first_branch", return_value={"pilot_measured": True,
              "completed_development_branches": 1, "user_model_attempts": 19, "input_tokens": 190,
              "output_tokens": 38, "serial_api_seconds": 45}).start()
        # The real single-branch evidence checker is covered in the runner tests.
        # Here we isolate continuation scheduling and actual SQLite allowance transitions.
        self.claim_checker = patch("scripts.run_report2_pilot.check_prior_claim", side_effect=self.check_claim).start()

    def check_claim(self, batch, path):
        if read_json(path).get("status") != "validated_complete":
            raise ValueError("Incomplete claim needs review")

    def proposal(self):
        return prepare(self.snapshot, self.path, self.first, self.root)

    def activated(self):
        proposal = self.proposal()
        activate(proposal, self.snapshot, self.folder, approve_credit_limit=1, root=self.root)
        return proposal

    def save_completed(self, index):
        budget = read_json(self.folder / "approved_budget.json")
        auth = read_json(self.folder / "approved_authorization.json")
        write(self.batch / "claims" / f"{identity(self.plan, index)}.json",
              {"status": "validated_complete", "episode": self.plan["episodes"][index], "budget_sha256": fingerprint(budget),
               "authorization_sha256": canonical_hash(auth)})

    def test_preparation_is_readonly_and_targets_only_the_remaining_branches(self):
        before = current_allowance(self.path)
        proposal = self.proposal()
        verify(proposal, self.snapshot, self.root)
        self.assertEqual(current_allowance(self.path), before)
        self.assertEqual(proposal["pending_branch_indices"], list(range(1, 24)))
        self.assertEqual(proposal["forecast"]["remaining_decisions"], 322)
        self.assertEqual(proposal["forecast"]["maximum_additional_attempts"], 644)

    def test_activation_preserves_every_attempt_and_hold_and_overall_cap(self):
        proposal = self.activated()
        active, state = current_allowance(self.path)
        self.assertEqual(state, proposal["before"])
        self.assertEqual(active["cap_usd"], 20)
        self.assertEqual(active["rates"], self.old["rates"])
        self.assertEqual(active["max_attempts"], state["attempts"] + 644)
        self.assertTrue((self.folder / "ledger_before_activation.sqlite").exists())
        auth = read_json(self.folder / "approved_authorization.json")
        self.assertEqual(auth["allowed_branch_indices"], list(range(24)))
        self.assertEqual((auth["max_decisions"], auth["max_attempts"]), (336, 672))
        self.assertLessEqual(19 + 23 * 28, auth["max_attempts"])

    def test_wrong_manual_limit_cannot_activate(self):
        proposal = self.proposal()
        with self.assertRaisesRegex(ValueError, "match"):
            activate(proposal, self.snapshot, self.folder, approve_credit_limit=.5, root=self.root)
        self.assertEqual(current_allowance(self.path)[1], proposal["before"])

    def test_global_cap_tariff_or_broader_attempt_overrun_is_rejected(self):
        proposal = self.proposal()
        new = copy.deepcopy(proposal["prospective_allowance"])
        new["cap_usd"] = 21
        with self.assertRaisesRegex(ValueError, "global credit cap"):
            validate_update(self.old, new, proposal["before"], self.envelope, 1)
        new = copy.deepcopy(proposal["prospective_allowance"])
        new["max_attempts"] += 1
        with self.assertRaisesRegex(ValueError, "644"):
            validate_update(self.old, new, proposal["before"], self.envelope, 1)

    def test_first_evidence_change_blocks_continuation(self):
        proposal = self.proposal()
        write(self.first / "pilot_audit.json", {"changed": True})
        with self.assertRaisesRegex(ValueError, "first audited branch"):
            verify(proposal, self.snapshot, self.root)

    def test_earlier_ledger_charge_change_is_rejected_after_activation(self):
        proposal = self.activated()
        db = sqlite3.connect(self.path)
        db.execute("UPDATE attempts SET actual_nanos=actual_nanos+1 WHERE id='first_0'")
        db.commit()
        db.close()
        with self.assertRaisesRegex(ValueError, "Earlier attempts"):
            active_state(proposal, self.snapshot, self.folder, self.root)

    def test_model_driver_requires_explicit_manual_execution(self):
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "explicit user"):
            run_pending({}, {}, self.folder, runner, self.root)
        runner.assert_not_called()

    def test_paid_evidence_without_a_claim_cannot_be_reissued(self):
        proposal = self.activated()
        budget = read_json(self.folder / "approved_budget.json")
        ledger = BudgetLedger(budget, self.path, run_id=identity(self.plan, 1), scope="kaggle")
        ledger.reserve("missing_claim", "gpt-4.1-mini-2025-04-14", 10, 2)
        ledger.settle("missing_claim", input_tokens=10, output_tokens=2)
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "without a verified completed claim"):
            run_pending(proposal, self.snapshot, self.folder, runner, self.root, manual=True)
        runner.assert_not_called()

    def test_driver_skips_completed_and_successful_repeat_launches_no_models(self):
        proposal = self.activated()
        self.save_completed(1)
        calls = []

        def run(index, auth, budget):
            calls.append(index)
            self.save_completed(index)
            return 0

        result, code = run_pending(proposal, self.snapshot, self.folder, run, self.root, manual=True)
        self.assertEqual(code, 0)
        self.assertEqual(calls, list(range(2, 24)))
        self.assertEqual(result["completed_branches"], 24)
        runner = Mock()
        repeated, code = run_pending(proposal, self.snapshot, self.folder, runner, self.root, manual=True)
        self.assertEqual((code, repeated["new_branches_launched"]), (0, 0))
        runner.assert_not_called()

    def test_failed_branch_stops_and_incomplete_claim_is_never_reissued(self):
        proposal = self.activated()

        def fail(index, auth, budget):
            write(self.batch / "claims" / f"{identity(self.plan, index)}.json", {"status": "claimed_before_client_creation"})
            return 1

        result, code = run_pending(proposal, self.snapshot, self.folder, fail, self.root, manual=True)
        self.assertEqual((code, result["failed_branch_index"]), (1, 1))
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            run_pending(proposal, self.snapshot, self.folder, runner, self.root, manual=True)
        runner.assert_not_called()

    def test_audit_before_activation_reports_pending_instead_of_fake_results(self):
        result = audit(self.proposal(), self.snapshot, self.folder, self.root)
        self.assertEqual(result["status"], "awaiting_user_manual_continuation")
        self.assertEqual(result["audit_model_calls_made"], 0)

    def mock_cohort(self, completed=24):
        proposal = self.activated()
        budget = read_json(self.folder / "approved_budget.json")
        for index in range(completed):
            key = identity(self.plan, index)
            ledger = BudgetLedger(budget, self.path, run_id=key, scope="kaggle")
            if index:
                for number in range(14):
                    attempt = f"branch_{index}_{number}"
                    ledger.reserve(attempt, "gpt-4.1-mini-2025-04-14", 10, 2)
                    ledger.settle(attempt, input_tokens=10, output_tokens=2)
                self.save_completed(index)
            db = sqlite3.connect(self.path)
            entries = db.execute("SELECT id,actual_nanos FROM attempts WHERE run_id=?", (key,)).fetchall()
            db.close()
            events = []
            for attempt, charge in entries:
                events.extend([{"event": "started", "attempt_id": attempt},
                               {"event": "finished", "attempt_id": attempt, "status": "completed",
                                "requested_model": "gpt-4.1-mini-2025-04-14", "cost_usd": charge / 1e9,
                                "usage": {"prompt_tokens": 10, "completion_tokens": 2}, "latency_seconds": .1}])
            path = self.batch / "requests" / key / "api_attempts.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
            write(self.batch / "branches" / key / "summary.json", {"completed_decisions": 14,
                  "first_pass_valid": 9 if index == 0 else 14, "repair_attempts": 5 if index == 0 else 0,
                  "successful_repairs": 5 if index == 0 else 0, "fallback_days": 0,
                  "model_calls_made": len(entries), "post_split_contribution": 1, "fill_rate": 1})
            write(self.batch / "branches" / key / "run_manifest.json", {**self.plan["episodes"][index], "policy": "llm_with_fallback"})
            write(self.batch / "cases" / self.plan["episodes"][index]["case_id"] / "warmup/prefix.json", {"offline_fixture": True})
        # Single-branch physical replay is independently tested elsewhere; isolate
        # the full-cohort identity, completeness and financial join here.
        patch("src.experiments.report2.validate_branch").start()
        return proposal

    def test_complete_mock_cohort_is_audited_without_launching_models(self):
        proposal = self.mock_cohort()
        result = audit(proposal, self.snapshot, self.folder, self.root)
        self.assertEqual(result["status"], "development_pilot_audited_stage3_complete")
        self.assertEqual(result["totals"]["decisions"], 336)
        self.assertEqual(result["totals"]["model_attempts"], 19 + 23 * 14)
        self.assertFalse(result["production_evaluation_started"])
        self.assertEqual(result["audit_model_calls_made"], 0)

    def test_partial_mock_cohort_cannot_be_reported_as_stage3_complete(self):
        proposal = self.mock_cohort(completed=3)
        result = audit(proposal, self.snapshot, self.folder, self.root)
        self.assertEqual(result["status"], "partial_development_pilot_audited")
        self.assertEqual(result["completed_branches"], 3)

    def test_duplicate_finished_event_cannot_bypass_the_cohort_ledger_join(self):
        proposal = self.mock_cohort(completed=2)
        path = self.batch / "requests" / identity(self.plan, 1) / "api_attempts.jsonl"
        events = [json.loads(s) for s in path.read_text().splitlines()]
        events[-1]["attempt_id"] = events[1]["attempt_id"]
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        with self.assertRaisesRegex(ValueError, "attempt identities"):
            audit(proposal, self.snapshot, self.folder, self.root)

    def test_branch_labels_cannot_be_swapped_between_frozen_plan_entries(self):
        proposal = self.mock_cohort(completed=2)
        path = self.batch / "branches" / identity(self.plan, 1) / "run_manifest.json"
        value = read_json(path)
        value["history"] = "none"
        write(path, value)
        with self.assertRaisesRegex(ValueError, "scenario/history identity"):
            audit(proposal, self.snapshot, self.folder, self.root)


if __name__ == "__main__":
    unittest.main()
