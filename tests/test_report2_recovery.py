"""Offline recovery tests use real SQLite transitions and injected model drivers."""
import copy
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from budget_fixture import manifest
from src.benchmarks.budget import BudgetLedger
from src.experiments.kaggle_protocol import execution_lock, write
from src.research.report2 import ROOT, canonical_hash, read_json
from src.research.report2_development import identity
from src.research.report2_interruption import file_hashes
from src.research.report2_pilot import MODEL, fingerprint
from src.research.report2_recovery import (SOURCES, TIMEOUT, activate, active_state, audit, check_before,
                                         prepare, read_ledger, run_pending, validate_budget)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in SOURCES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, path)
        self.plan = {"task_id": "report2:development", "episodes": [
            {"case_id": case, "scenario": scenario, "history": history, "realization": 0}
            for case in ("dev_1", "dev_2") for scenario in ("control", "demand_surge", "demand_decline", "delivery_disruption")
            for history in ("full", "frozen", "none")]}
        self.budget = manifest(cap=20, attempts=1000)
        self.budget.update(scope_caps_usd={"native": 4.2, "kaggle": 1.3},
                           allowed_tasks=["report2:development"], rates_verified_at_utc="2026-10-31T00:00:00+00:00",
                           bounded_unknown_failure_categories=["missing_usage"])
        self.path = self.root / "results/budgets/mock_only.sqlite"
        historic = BudgetLedger(self.budget, self.path, run_id="historic", scope="native")
        historic.reserve("historic_hold", "test", 100, 10)
        historic.settle("historic_hold", uncertain_reason="missing_usage")
        historic.retain_bounded_failed_charge("historic_hold", "synthetic prior hold")
        with closing(sqlite3.connect(self.path)) as db:
            with db:
                db.execute("CREATE TABLE allowance_amendments (at TEXT, previous_manifest TEXT, new_manifest TEXT)")
                db.execute("INSERT INTO allowance_amendments VALUES (?,?,?)", ("fixture", json.dumps(self.budget), json.dumps(self.budget)))
        self.batch = self.root / "results/report2/manual_development"
        self.continuation = self.root / "results/report2/continuation"
        self.folder = self.root / "results/report2/recovery"
        self.folder.mkdir(parents=True)
        self.snapshot = {"provider": "ShopAIKey", "base_url": "https://api.shopaikey.com/v1", "rates_verified": True,
                         "paid_api_calls": 0, "missing_models": [], "checked_at_utc": datetime.now(timezone.utc).isoformat(),
                         "rates": self.budget["rates"]}
        for name, value in (("proposal.json", {"ledger_relative_path": "results/budgets/mock_only.sqlite"}),
                            ("gateway_snapshot.json", self.snapshot), ("approved_budget.json", self.budget)):
            write(self.continuation / name, value)
        for index in range(10):
            self.save_branch(index, self.budget, {"fixture": "historical"})
        key = identity(self.plan, 10)
        ledger = BudgetLedger(self.budget, self.path, run_id=key, scope="kaggle")
        ledger.reserve("partial_ok", MODEL, 100, 10)
        ledger.settle("partial_ok", input_tokens=100, output_tokens=10)
        ledger.reserve("timeout", MODEL, 100, 10)
        ledger.settle("timeout", uncertain_reason=TIMEOUT)
        self.write_requests(key, [r for r in read_ledger(self.path)[2] if r["run_id"] == key])
        write(self.batch / "branches" / key / "run_manifest.json", {"status": "incomplete"})
        write(self.batch / "claims" / f"{key}.json", {"status": "claimed_before_client_creation"})
        _, state, rows, _ = read_ledger(self.path)
        failed = next(r for r in rows if r["id"] == "timeout")
        incident = {"status": "interruption_reviewed_stage3_incomplete", "audit_model_calls_made": 0,
                    "canonical_evidence_unchanged": True, "ledger_unchanged": True, "review_source_sha256": {},
                    "interrupted": {"branch_index": 10, "failed_requests": [{"attempt_id": "timeout", "failure_category": TIMEOUT,
                                      "reserved_cost_usd": failed["reserved_nanos"] / 1e9}]},
                    "completed_branches": 10, "budget_state": state, "canonical_artifact_sha256": file_hashes(self.batch)}
        self.review_path = self.root / "results/report2/review.json"
        write(self.review_path, incident)
        self.addCleanup(patch.stopall)
        patch("src.research.report2_recovery.verify_continuation", return_value={}).start()
        patch("src.experiments.report2.development_plan", return_value=self.plan).start()

        def claim_check(batch, path):
            if read_json(path)["status"] != "validated_complete":
                raise ValueError("Incomplete claim blocks model execution")
        patch("scripts.run_report2_pilot.check_prior_claim", side_effect=claim_check).start()

    def write_requests(self, key, rows):
        events = []
        for row in rows:
            base = {"attempt_id": row["id"], "run_id": key, "requested_model": MODEL, "purpose": "pilot",
                    "request_sha256": row["id"], "logical_request_id": "day:2023-05-19:repair:1",
                    "reserved_cost_usd": row["reserved_nanos"] / 1e9}
            events.extend([{**base, "event": "started"},
                           {**base, "event": "finished", "status": "completed" if row["status"] == "settled" else "failed",
                            "cost_usd": row["actual_nanos"] / 1e9 if row["actual_nanos"] is not None else None,
                            "usage": {"prompt_tokens": 100, "completion_tokens": 10} if row["status"] == "settled" else None,
                            "latency_seconds": .1, "failure_category": row.get("uncertainty_reason")}])
        path = self.batch / "requests" / key / "api_attempts.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

    def save_branch(self, index, budget, auth):
        key = identity(self.plan, index)
        ledger = BudgetLedger(budget, self.path, run_id=key, scope="kaggle")
        for n in range(14):
            attempt = f"branch_{index}_{n}"
            ledger.reserve(attempt, MODEL, 100, 10)
            ledger.settle(attempt, input_tokens=100, output_tokens=10)
        rows = [r for r in read_ledger(self.path)[2] if r["run_id"] == key and r["id"] not in {"timeout", "partial_ok"}]
        self.write_requests(key, rows)
        write(self.batch / "branches" / key / "summary.json", {"completed_decisions": 14, "model_calls_made": 14,
              "first_pass_valid": 14, "repair_attempts": 0, "successful_repairs": 0, "fallback_days": 0,
              "post_split_contribution": 1, "fill_rate": 1})
        write(self.batch / "claims" / f"{key}.json", {"status": "validated_complete", "episode": self.plan["episodes"][index],
              "budget_sha256": fingerprint(budget), "authorization_sha256": canonical_hash(auth)})

    def proposal(self):
        return prepare(self.continuation, self.review_path, self.snapshot, self.root)

    def activated(self):
        proposal = self.proposal()
        with execution_lock(self.batch):
            activate(proposal, self.folder, approve_held_credits=proposal["held_credits"], root=self.root)
        return proposal

    def driver(self, index, auth, budget):
        self.save_branch(index, read_json(budget), read_json(auth))
        return 0

    def test_preparation_is_readonly_and_requests_no_new_credit(self):
        before = read_ledger(self.path)
        proposal = self.proposal()
        check_before(proposal, self.root, fresh=True)
        self.assertEqual(read_ledger(self.path), before)
        self.assertEqual(proposal["recovery_branch_indices"], list(range(10, 24)))
        self.assertEqual(proposal["additional_credit_limit"], 0)

    def test_activation_archives_originals_without_changing_attempts_or_limits(self):
        before = read_ledger(self.path)
        original = file_hashes(self.batch)
        proposal = self.activated()
        after = read_ledger(self.path)
        self.assertEqual(before[2], after[2])
        self.assertEqual(after[1]["exposure_nanos"], before[1]["exposure_nanos"])
        self.assertEqual(len(after[3]), len(before[3]) + 1)
        self.assertEqual(after[1]["blocking_uncertain_attempts"], 0)
        self.assertIsNone(next(r for r in after[2] if r["id"] == "timeout")["actual_nanos"])
        self.assertEqual(read_json(self.folder / "approved_budget.json")["scope_caps_usd"], self.budget["scope_caps_usd"])
        self.assertEqual(active_state(proposal, self.folder, self.root)[0], list(range(10)))
        backup = read_ledger(self.folder / "ledger_before_recovery.sqlite")
        self.assertEqual(backup, before)
        key = identity(self.plan, 10)
        self.assertFalse((self.batch / "claims" / f"{key}.json").exists())
        for name, digest in original.items():
            path = self.folder / "archive" / name if key in name else self.batch / name
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_wrong_held_amount_cannot_activate(self):
        proposal = self.proposal()
        before = read_ledger(self.path)
        with self.assertRaisesRegex(ValueError, "entire reviewed"):
            activate(proposal, self.folder, approve_held_credits=0, root=self.root)
        self.assertEqual(read_ledger(self.path), before)

    def test_credit_or_tariff_change_cannot_be_hidden_in_recovery(self):
        proposal = self.activated()
        for name in ("cap_usd", "max_attempts"):
            altered = read_json(self.folder / "approved_budget.json")
            altered[name] += 1
            with self.assertRaisesRegex(ValueError, "cannot change"):
                validate_budget(proposal, altered)

    def test_repeated_activation_is_blocked_without_touching_attempts(self):
        proposal = self.activated()
        before = read_ledger(self.path)
        with self.assertRaisesRegex(ValueError, "Ledger changed"):
            activate(proposal, self.folder, approve_held_credits=proposal["held_credits"], root=self.root)
        self.assertEqual(read_ledger(self.path), before)

    def test_altered_original_completed_evidence_blocks_models(self):
        proposal = self.activated()
        write(self.batch / "claims" / f"{identity(self.plan, 0)}.json", {"changed": True})
        with self.assertRaisesRegex(ValueError, "canonical evidence changed"):
            active_state(proposal, self.folder, self.root)

    def test_altered_archive_blocks_models(self):
        proposal = self.activated()
        path = self.folder / "archive/claims" / f"{identity(self.plan, 10)}.json"
        path.write_text("{}")
        with self.assertRaisesRegex(ValueError, "Archived interruption evidence changed"):
            active_state(proposal, self.folder, self.root)

    def test_historical_charge_edit_is_rejected(self):
        proposal = self.activated()
        with closing(sqlite3.connect(self.path)) as db:
            with db:
                db.execute("UPDATE attempts SET reserved_nanos=reserved_nanos+1 WHERE id='historic_hold'")
        with self.assertRaisesRegex(ValueError, "Historical attempts"):
            active_state(proposal, self.folder, self.root)

    def test_new_unknown_charge_blocks_without_retry(self):
        proposal = self.activated()
        budget = read_json(self.folder / "approved_budget.json")
        ledger = BudgetLedger(budget, self.path, run_id=identity(self.plan, 10), scope="kaggle")
        ledger.reserve("second_failure", MODEL, 100, 10)
        ledger.settle("second_failure", uncertain_reason=TIMEOUT)
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "new interrupted/unknown"):
            run_pending(proposal, self.folder, runner, self.root, manual=True)
        runner.assert_not_called()

    def test_model_driver_requires_manual_execution(self):
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "explicit user manual"):
            run_pending({}, self.folder, runner, self.root)
        runner.assert_not_called()

    def test_successful_driver_skips_old_branches_and_repeats_with_zero_calls(self):
        proposal = self.activated()
        calls = []

        def driver(index, auth, budget):
            calls.append(index)
            return self.driver(index, auth, budget)

        result, code = run_pending(proposal, self.folder, driver, self.root, manual=True)
        self.assertEqual((code, result["completed_branches"]), (0, 24))
        self.assertEqual(calls, list(range(10, 24)))
        runner = Mock()
        result, code = run_pending(proposal, self.folder, runner, self.root, manual=True)
        self.assertEqual((code, result["new_branches_launched"]), (0, 0))
        runner.assert_not_called()
        self.assertEqual(active_state(proposal, self.folder, self.root)[2], 24 * 14 + 2)

    def test_second_interrupted_claim_is_not_reissued(self):
        proposal = self.activated()

        def driver(index, auth, budget):
            write(self.batch / "claims" / f"{identity(self.plan, index)}.json", {"status": "claimed_before_client_creation"})
            return 1

        result, code = run_pending(proposal, self.folder, driver, self.root, manual=True)
        self.assertEqual((code, result["failed_branch_index"]), (1, 10))
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "Incomplete claim"):
            run_pending(proposal, self.folder, runner, self.root, manual=True)
        runner.assert_not_called()

    def test_archived_physical_attempts_count_toward_next_launch_limit(self):
        proposal = self.activated()
        _, state, _ = active_state(proposal, self.folder, self.root)
        runner = Mock()
        with patch("src.research.report2_recovery.active_state", return_value=(list(range(10)), state, 650)):
            with self.assertRaisesRegex(ValueError, "including archived"):
                run_pending(proposal, self.folder, runner, self.root, manual=True)
        runner.assert_not_called()

    def test_paid_attempt_without_completed_claim_cannot_be_reissued(self):
        proposal = self.activated()
        budget = read_json(self.folder / "approved_budget.json")
        ledger = BudgetLedger(budget, self.path, run_id=identity(self.plan, 11), scope="kaggle")
        ledger.reserve("orphan", MODEL, 100, 10)
        ledger.settle("orphan", input_tokens=100, output_tokens=10)
        with self.assertRaisesRegex(ValueError, "lack a completed recovery claim"):
            active_state(proposal, self.folder, self.root)

    def test_final_audit_covers_completed_and_archived_requests_separately(self):
        proposal = self.activated()
        run_pending(proposal, self.folder, self.driver, self.root, manual=True)
        before = read_ledger(self.path)
        with patch("src.experiments.report2.validate_branch"):
            for case in ("dev_1", "dev_2"):
                write(self.batch / "cases" / case / "warmup/prefix.json", {"fixture": True})
            result = audit(proposal, self.folder, self.root)
        self.assertEqual(result["status"], "development_pilot_audited_stage3_complete")
        self.assertEqual(result["totals"]["completed_decisions"], 336)
        self.assertEqual(result["physical_pilot_attempts"], 338)
        self.assertEqual(result["archived_interruption"]["model_attempts"], 2)
        self.assertGreater(result["archived_interruption"]["unknown_charge_reserved_credits"], 0)
        self.assertFalse(result["production_evaluation_started"])
        self.assertEqual(read_ledger(self.path), before)


if __name__ == "__main__":
    unittest.main()
