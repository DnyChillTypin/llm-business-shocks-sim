"""Costing is read-only; manual activation preserves old charges and cannot expand caps."""
import copy
import importlib.util
import json
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from budget_fixture import manifest as mock_allowance
from src.benchmarks.budget import BudgetLedger
from src.benchmarks.errors import BudgetStop
from src.research.report2 import ROOT, PROTOCOL, canonical_hash, read_json
from src.experiments.kaggle_protocol import write
from src.research.report2_pilot import (SOURCE_FILES, MODEL, activate_proposal, audit_first_branch,
    build_proposal, current_allowance, fingerprint, token_cost, validate_snapshot,
    validate_transition, verify_proposal)


class Report2PilotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in [PROTOCOL, *SOURCE_FILES]:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        self.directory = self.root / "results/report2/milestone3/first_branch"
        self.directory.mkdir(parents=True)
        self.path = self.root / "results/budgets/mock_only.sqlite"
        self.allowance = mock_allowance(cap=2, attempts=3000)
        self.allowance.update(scope_caps_usd={"native": 1, "kaggle": 1},
                              allowed_tasks=["legacy:task"], bounded_unknown_failure_categories=["missing_usage"])
        self.ledger = BudgetLedger(self.allowance, self.path, run_id="old", scope="kaggle")
        self.ledger.reserve("known", MODEL, 100, 10)
        self.ledger.settle("known", input_tokens=50, output_tokens=2)
        self.ledger.reserve("unknown", MODEL, 100, 10)
        self.ledger.settle("unknown", uncertain_reason="missing_usage")
        self.ledger.retain_bounded_failed_charge("unknown", "offline fixture retained reserve")
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE allowance_amendments (at TEXT, previous_manifest TEXT, new_manifest TEXT)")
            db.execute("INSERT INTO allowance_amendments VALUES (?,?,?)", ("fixture", "{}", json.dumps(self.allowance)))
        db.close()
        self.snapshot = {"provider": "ShopAIKey", "base_url": "https://api.shopaikey.com/v1",
                         "rates_verified": True, "missing_models": [], "paid_api_calls": 0,
                         "checked_at_utc": datetime.now(timezone.utc).isoformat(), "pricing_version": "fixture",
                         "rates": copy.deepcopy(self.allowance["rates"]), "balance": {"remaining": 10}}
        self.historical = {"decisions": 252, "attempts": 396, "input_tokens": 359739,
                           "output_tokens": 8428, "serial_api_seconds": 700.69, "cohort": "offline fixture"}
        self.observations = [{"observation": {"date": "2023-05-08", "funds": 100, "products": {}}} for _ in range(14)]
        self.plan = {"implementation_sha256": "mock_only", "episodes": list(range(24)), "task_id": "report2:development"}
        self.addCleanup(patch.stopall)
        patch("src.research.report2_pilot.verify_implementation", return_value={}).start()
        patch("src.experiments.report2.development_plan", return_value=self.plan).start()

    def proposal(self):
        return build_proposal(self.snapshot, self.path, self.historical, self.observations, root=self.root)

    def test_preparation_and_check_preserve_ledger_and_create_no_model_result(self):
        old, before = current_allowance(self.path)
        proposal = self.proposal()
        verify_proposal(proposal, self.snapshot, self.root)
        after, state = current_allowance(self.path)
        self.assertEqual(old, after)
        self.assertEqual(before, state)
        self.assertEqual(proposal["status"], "prepared_awaiting_manual_activation_and_model_run")
        self.assertFalse((self.root / "results/report2/manual_development").exists())

    def test_manual_activation_backs_up_and_preserves_every_charge_and_hold(self):
        proposal = self.proposal()
        receipt = activate_proposal(proposal, self.snapshot, self.directory, approve_credit_limit=.5, root=self.root)
        active, state = current_allowance(self.path)
        self.assertEqual(state, proposal["before"])
        self.assertEqual(active["cap_usd"], self.allowance["cap_usd"])
        self.assertEqual(active["rates"], self.allowance["rates"])
        self.assertEqual(active["max_attempts"], state["attempts"] + 28)
        self.assertLess(active["scope_caps_usd"]["kaggle"], self.allowance["scope_caps_usd"]["kaggle"])
        self.assertTrue((self.directory / "ledger_before_activation.sqlite").is_file())
        self.assertEqual(receipt["model_calls_made"], 0)
        auth = read_json(self.directory / "approved_authorization.json")
        self.assertEqual(auth["allowed_branch_indices"], [0])
        self.assertEqual(auth["budget_sha256"], fingerprint(active))

    def test_credit_and_aggregate_attempt_limits_are_enforced_by_the_existing_ledger(self):
        proposal = self.proposal()
        activate_proposal(proposal, self.snapshot, self.directory, approve_credit_limit=.5, root=self.root)
        active = read_json(self.directory / "approved_budget.json")
        ledger = BudgetLedger(active, self.path, run_id="mock_branch", scope="kaggle")
        for i in range(5):
            ledger.reserve(f"credit_{i}", MODEL, 100000, 0)
        with self.assertRaisesRegex(BudgetStop, "remaining allowance"):
            ledger.reserve("over_credit", MODEL, 1, 0)
        for i in range(23):
            ledger.reserve(f"zero_{i}", MODEL, 0, 0)
        with self.assertRaisesRegex(BudgetStop, "attempt ceiling"):
            ledger.reserve("over_attempts", MODEL, 0, 0)

    def test_wrong_manual_limit_does_not_modify_the_ledger(self):
        proposal = self.proposal()
        with self.assertRaisesRegex(ValueError, "differs"):
            activate_proposal(proposal, self.snapshot, self.directory, approve_credit_limit=.1, root=self.root)
        self.assertEqual(current_allowance(self.path)[1], proposal["before"])
        self.assertFalse((self.directory / "approved_budget.json").exists())

    def test_rate_change_or_stale_snapshot_is_rejected(self):
        changed = copy.deepcopy(self.snapshot)
        changed["rates"][MODEL]["input_per_million"] *= 2
        with self.assertRaisesRegex(ValueError, "Tariffs changed"):
            validate_snapshot(changed, self.allowance)
        old = copy.deepcopy(self.snapshot)
        old["checked_at_utc"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with self.assertRaisesRegex(ValueError, "24 hours"):
            validate_snapshot(old, self.allowance)

    def test_global_cap_increase_or_repriced_history_is_rejected(self):
        proposal = self.proposal()
        changed = copy.deepcopy(proposal["prospective_allowance"])
        changed["cap_usd"] += 1
        with self.assertRaisesRegex(ValueError, "global cap"):
            validate_transition(self.allowance, changed, proposal["before"], .5)
        changed = copy.deepcopy(proposal["prospective_allowance"])
        changed["rates"][MODEL]["input_per_million"] *= 2
        with self.assertRaisesRegex(ValueError, "tariff values"):
            validate_transition(self.allowance, changed, proposal["before"], .5)

    def test_changed_ledger_or_preparation_code_blocks_activation(self):
        proposal = self.proposal()
        self.ledger.reserve("another", MODEL, 10, 1)
        self.ledger.settle("another", input_tokens=10, output_tokens=1)
        with self.assertRaisesRegex(ValueError, "ledger changed"):
            verify_proposal(proposal, self.snapshot, self.root)
        script = self.root / SOURCE_FILES[1]
        script.write_text(script.read_text() + "\n# changed fixture\n")
        with self.assertRaisesRegex(ValueError, "code, plan"):
            verify_proposal(proposal, self.snapshot, self.root)

    def test_rehashed_original_allowance_cannot_expand_a_bound_approval(self):
        proposal = self.proposal()
        proposal["old_allowance"]["cap_usd"] += 10
        proposal["prospective_allowance"]["cap_usd"] += 10
        proposal["proposal_sha256"] = canonical_hash({k: v for k, v in proposal.items() if k != "proposal_sha256"})
        with self.assertRaisesRegex(ValueError, "original allowance"):
            verify_proposal(proposal, self.snapshot, self.root)

    def test_explicit_manual_launcher_is_the_only_mode_that_launches_the_runner(self):
        spec = importlib.util.spec_from_file_location("stage3_manual_cli", ROOT / "scripts/prepare_report2_pilot.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        write(self.directory / "proposal.json", self.proposal())
        write(self.directory / "gateway_snapshot.json", self.snapshot)
        argv = ["prepare_report2_pilot.py", "--activate-and-run", "--directory", str(self.directory), "--approve-credit-limit", "0.50"]
        with patch.object(cli, "ROOT", self.root), patch("sys.argv", argv), \
             patch("src.research.report2_pilot.activate_proposal", return_value={"offline_mock": True}) as activate, \
             patch.object(cli.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(cli.main(), 0)
            activate.assert_called_once()
            args = run.call_args.args[0]
            self.assertIn("--execute-model", args)
            self.assertEqual(args[args.index("--branch-index") + 1], "0")

    def test_no_model_result_is_reported_as_pending(self):
        report = audit_first_branch(self.proposal(), self.snapshot, self.directory, self.root)
        self.assertFalse(report["pilot_measured"])
        self.assertEqual(report["status"], "awaiting_user_manual_model_run")
        self.assertEqual(report["audit_model_calls_made"], 0)

    def test_current_tariff_cost_is_in_credits_and_not_cash_conversion(self):
        rate = {"input_per_million": .6408, "output_per_million": 2.5632, "per_request": 0}
        self.assertAlmostEqual(token_cost(rate, 359739, 8428), .2521234008)

    def mock_result(self):
        self.plan["episodes"] = [{"case_id": "dev_1", "scenario": "control", "history": "full"} for _ in range(24)]
        proposal = self.proposal()
        activate_proposal(proposal, self.snapshot, self.directory, approve_credit_limit=.5, root=self.root)
        active = read_json(self.directory / "approved_budget.json")
        auth = read_json(self.directory / "approved_authorization.json")
        identity = canonical_hash({"plan": canonical_hash(self.plan), "episode": self.plan["episodes"][0]})
        ledger = BudgetLedger(active, self.path, run_id=identity, scope="kaggle")
        events = []
        for i in range(14):
            attempt = f"mock_{i}"
            ledger.reserve(attempt, MODEL, 10, 2)
            cost = ledger.settle(attempt, input_tokens=10, output_tokens=2)
            events += [{"event": "started", "attempt_id": attempt},
                       {"event": "finished", "attempt_id": attempt, "requested_model": MODEL,
                        "status": "completed", "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                        "cost_usd": cost, "latency_seconds": .1}]
        batch = self.root / "results/report2/manual_development"
        write(batch / "claims" / f"{identity}.json", {"status": "validated_complete", "budget_sha256": fingerprint(active),
              "authorization_sha256": canonical_hash(auth)})
        write(batch / "cases/dev_1/warmup/prefix.json", {})
        write(batch / "branches" / identity / "summary.json", {"model_calls_made": 14, "completed_decisions": 14,
              "first_pass_valid": 14, "repair_attempts": 0, "successful_repairs": 0,
              "fallback_days": 0, "post_split_contribution": 1.0})
        path = batch / "requests" / identity / "api_attempts.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        # State replay is covered by runner tests. These tests isolate the
        # additional identity/token/charge reconciliation against a real mock DB.
        patch("scripts.run_report2_pilot.check_prior_claim").start()
        patch("src.experiments.report2.validate_branch").start()
        return proposal, events, path

    def test_completed_mock_pilot_joins_charges_without_marking_the_full_stage_done(self):
        proposal, _, _ = self.mock_result()
        result = audit_first_branch(proposal, self.snapshot, self.directory, self.root)
        self.assertTrue(result["pilot_measured"])
        self.assertEqual(result["user_model_attempts"], 14)
        self.assertEqual(result["input_tokens"], 140)
        self.assertEqual(result["completed_development_branches"], 1)
        self.assertEqual(result["status"], "first_branch_audited_remaining_development_pilot_pending")

    def test_duplicate_finished_event_is_rejected_even_with_matching_counts(self):
        proposal, events, path = self.mock_result()
        events[-1]["attempt_id"] = events[1]["attempt_id"]
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        with self.assertRaisesRegex(ValueError, "Unique attempt IDs"):
            audit_first_branch(proposal, self.snapshot, self.directory, self.root)


if __name__ == "__main__":
    unittest.main()
