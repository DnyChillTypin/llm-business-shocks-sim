"""Unit tests for Report 2 production planning, baselines, authorization, and recovery."""
import copy
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.research.report2 import ROOT, PROTOCOL, MANIFEST, canonical_hash, read_json
from src.research.report2_production import (
    TASK, MODEL, SCALE,
    production_plan, baseline_plan, episode_identity,
    authorization_template, validate_authorization,
    build_production_proposal, verify_production_proposal, activate_production,
    prepare_production_recovery, activate_production_recovery,
    audit_production, current_allowance, read_ledger, fingerprint
)
from src.experiments.report2_production import (
    get_evaluation_block, prepare_production_case, get_or_create_prefix,
    run_baseline_branch, run_all_baselines, check_prior_claim
)


class TestProductionPlanning(unittest.TestCase):
    def test_cohort_counts(self):
        main = production_plan("main")
        self.assertEqual(len(main["episodes"]), 432)
        self.assertEqual(main["decisions"], 6048)
        self.assertEqual(main["max_attempts"], 12096)

        history = production_plan("history")
        self.assertEqual(len(history["episodes"]), 432)
        self.assertEqual(history["decisions"], 6048)

        elasticity = production_plan("elasticity")
        self.assertEqual(len(elasticity["episodes"]), 432)
        self.assertEqual(elasticity["decisions"], 6048)

        all_cohorts = production_plan("all")
        self.assertEqual(len(all_cohorts["episodes"]), 1296)
        self.assertEqual(all_cohorts["decisions"], 18144)

    def test_baseline_counts(self):
        b_main = baseline_plan("main")
        self.assertEqual(len(b_main["episodes"]), 288)

        b_elasticity = baseline_plan("elasticity")
        self.assertEqual(len(b_elasticity["episodes"]), 288)

        b_all = baseline_plan("all")
        self.assertEqual(len(b_all["episodes"]), 576)

    def test_episode_identities_unique(self):
        main = production_plan("main")
        ids = [episode_identity(main, ep) for ep in main["episodes"]]
        self.assertEqual(len(ids), 432)
        self.assertEqual(len(set(ids)), 432)

    def test_get_evaluation_block(self):
        block = get_evaluation_block("S001_P0003_eval_1")
        self.assertEqual(block["store_id"], "S001")
        self.assertEqual(block["product_id"], "P0003")
        self.assertEqual(block["window_id"], "eval_1")
        with self.assertRaises(ValueError):
            get_evaluation_block("non_existent_block")


class TestProductionPreparationAndBaselines(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_prepare_case_and_prefix(self):
        block = get_evaluation_block("S001_P0003_eval_1")
        prepared = prepare_production_case(block, elasticity=1.5, batch_dir=self.temp_dir)
        self.assertTrue(prepared.exists())
        self.assertTrue((prepared / "artifact_checksums.json").exists())

        # Verify settings file in case directory has elasticity 1.5
        case_dir = self.temp_dir / "cases" / block["block_id"] / "elasticity_1.5"
        settings = read_json(case_dir / "settings.json")
        self.assertEqual(settings["elasticity"], 1.5)

        # Shared config must remain unmodified
        shared = read_json(ROOT / "configs/kaggle_retailbench.json")
        self.assertEqual(shared["elasticity"], 1.5)

        # Create immutable prefix
        prefix = get_or_create_prefix(block, elasticity=1.5, batch_dir=self.temp_dir)
        self.assertEqual(prefix["schema_version"], 1)
        self.assertEqual(len(prefix["decisions"]), 7)

        # Calling again should load cached prefix
        prefix2 = get_or_create_prefix(block, elasticity=1.5, batch_dir=self.temp_dir)
        self.assertEqual(prefix["prefix_sha256"], prefix2["prefix_sha256"])

    def test_run_single_baseline_branch(self):
        block = get_evaluation_block("S001_P0003_eval_1")
        episode = {
            "cohort": "baseline_main",
            "block_id": block["block_id"],
            "store_id": block["store_id"],
            "product_id": block["product_id"],
            "window_id": block["window_id"],
            "scenario": "control",
            "history": "full",
            "elasticity": 1.5,
            "realization": 0,
            "policy": "adaptive",
        }
        res = run_baseline_branch(episode, batch_dir=self.temp_dir)
        self.assertEqual(res["status"], "validated_complete")
        self.assertFalse(res["skipped_existing"])

        # Second run should skip
        res2 = run_baseline_branch(episode, batch_dir=self.temp_dir)
        self.assertTrue(res2["skipped_existing"])


def make_fixture_manifest():
    return {
        "budget_id": "stage2_pilot_v1",
        "approved": True,
        "approval_reference": "Fixture initial allowance",
        "approved_at_utc": "2026-10-31T05:58:31.134514+00:00",
        "provider": "ShopAIKey",
        "base_url": "https://api.shopaikey.com/v1",
        "currency": "USD_gateway_credit",
        "cap_usd": 20.0,
        "scope_caps_usd": {"native": 4.2, "kaggle": 0.565312222},
        "max_attempts": 2497,
        "allowed_purposes": ["pilot", "evaluation"],
        "allowed_tasks": ["report2:development"],
        "max_input_tokens_bound": 262144,
        "max_output_tokens": 4096,
        "protocol_token_allowance": 4096,
        "rates_verified": True,
        "rates_source": "https://api.shopaikey.com/pricing",
        "rates_verified_at_utc": "2026-10-31T05:33:32.821739+00:00",
        "pricing_version": "a42d372ccf0b5dd13ecf71203521f9d2",
        "rates": {
            "gpt-4.1-mini-2025-04-14": {"input_per_million": 0.6408, "output_per_million": 2.5632, "per_request": 0},
            "gpt-4o-mini-2024-07-18": {"input_per_million": 0.18, "output_per_million": 0.72, "per_request": 0},
            "deepseek-v3.2": {"input_per_million": 2.4, "output_per_million": 3.6, "per_request": 0}
        },
        "qualification": "Fixture allowance",
        "initial_sequence": "Fixture sequence",
        "bounded_unknown_failure_categories": ["api_InternalServerError_http_503"]
    }


def make_fixture_ledger(path: Path) -> dict:
    manifest = make_fixture_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("CREATE TABLE config (fingerprint TEXT)")
        conn.execute("INSERT INTO config VALUES (?)", (fingerprint(manifest),))
        conn.execute("CREATE TABLE allowance_amendments (at TEXT, previous_manifest TEXT, new_manifest TEXT)")
        conn.execute("INSERT INTO allowance_amendments VALUES (?,?,?)", ("2026-10-31T05:58:31.134514+00:00", json.dumps(manifest), json.dumps(manifest)))
        conn.execute("CREATE TABLE attempts (id TEXT, run_id TEXT, scope TEXT, model TEXT, reserved_nanos INTEGER, actual_nanos INTEGER, status TEXT, input_bound INTEGER, output_bound INTEGER, started_at TEXT, finished_at TEXT, uncertainty_reason TEXT)")
        conn.execute("CREATE TABLE bounded_holds (attempt_id TEXT, approval_reference TEXT, at TEXT, explanation TEXT)")
    conn.close()
    return manifest


def make_fixture_snapshot(manifest: dict) -> dict:
    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": manifest["provider"],
        "base_url": manifest["base_url"],
        "rates_verified": True,
        "pricing_version": manifest["pricing_version"],
        "paid_api_calls": 0,
        "missing_models": [],
        "rates": copy.deepcopy(manifest["rates"]),
    }


class TestProductionBudgetAndAuthorization(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.ledger_path = self.temp_dir / "stage2_pilot_v1.sqlite"
        self.budget = make_fixture_ledger(self.ledger_path)
        self.snapshot = make_fixture_snapshot(self.budget)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_authorization_validation(self):
        plan = production_plan("main")
        auth = authorization_template(plan)
        budget = copy.deepcopy(self.budget)

        # Unapproved auth should fail
        with self.assertRaises(ValueError):
            validate_authorization(auth, budget, plan, 0)

        # Approved auth matching budget
        budget["allowed_tasks"].append(TASK)
        budget["allowed_purposes"].append("evaluation")
        auth["approved"] = True
        auth["approval_reference"] = "Test approval reference"
        auth["budget_sha256"] = fingerprint(budget)
        validate_authorization(auth, budget, plan, 0)

    def test_build_and_activate_proposal(self):
        with patch("src.research.report2_production.validate_snapshot", return_value={"input_per_million": 0.6408, "output_per_million": 2.5632, "per_request": 0}):
            proposal = build_production_proposal(
                self.snapshot,
                self.ledger_path,
                cohort="main",
                incremental_credit_limit=6.0,
                root=ROOT,
            )
            self.assertEqual(proposal["status"], "prepared_awaiting_manual_activation_and_model_run")
            self.assertEqual(proposal["incremental_credit_limit"], 6.0)
            self.assertEqual(proposal["planned_branches"], 432)

            handoff_dir = self.temp_dir / "production_handoff"
            handoff_dir.mkdir()
            receipt = activate_production(proposal, self.snapshot, handoff_dir, approve_credit_limit=6.0, root=ROOT)
            self.assertEqual(receipt["status"], "production_activated_awaiting_manual_models")
            self.assertTrue((handoff_dir / "approved_budget.json").exists())
            self.assertTrue((handoff_dir / "approved_authorization.json").exists())
            self.assertTrue((handoff_dir / "ledger_before_activation.sqlite").exists())

            # Verify ledger amendment was committed
            _, state = current_allowance(self.ledger_path)
            self.assertEqual(state["retained_holds"], 0)


class TestProductionRecovery(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.batch_dir = self.temp_dir / "batch"
        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.temp_dir / "stage2_pilot_v1.sqlite"
        self.budget = make_fixture_ledger(self.ledger_path)
        self.snapshot = make_fixture_snapshot(self.budget)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_prepare_and_activate_recovery(self):
        plan = production_plan("main")
        ep0 = plan["episodes"][0]
        key0 = episode_identity(plan, ep0)

        # Simulate an interrupted claim
        claims_dir = self.batch_dir / "claims"
        claims_dir.mkdir(parents=True, exist_ok=True)
        (claims_dir / f"{key0}.json").write_text(json.dumps({
            "status": "claimed_before_client_creation",
            "branch_index": 0,
            "episode": ep0,
        }), encoding="utf-8")

        handoff_dir = self.temp_dir / "recovery_handoff"
        proposal = prepare_production_recovery(
            self.batch_dir,
            handoff_dir,
            self.snapshot,
            cohort="main",
            ledger_path=self.ledger_path,
            root=ROOT,
        )
        self.assertEqual(proposal["status"], "ready_for_user_manual_recovery")
        self.assertEqual(proposal["interrupted_index"], 0)
        self.assertEqual(proposal["interrupted_identity"], key0)

        # Test activation of recovery
        temp_ledger = self.temp_dir / "test_ledger.sqlite"
        shutil.copy(self.ledger_path, temp_ledger)
        proposal["ledger_relative_path"] = str(temp_ledger.resolve())

        with patch("src.research.report2_production.connect_readonly", side_effect=sqlite3.connect):
            receipt = activate_production_recovery(proposal, handoff_dir, self.batch_dir, approve_held_credits=0.0, root=ROOT)
            self.assertEqual(receipt["status"], "production_recovery_activated")
            self.assertTrue((handoff_dir / "archive" / f"claims/{key0}.json").exists())
            self.assertFalse((self.batch_dir / f"claims/{key0}.json").exists())

    def test_rejection_of_incomplete_claim(self):
        claims_dir = self.batch_dir / "claims"
        claims_dir.mkdir(parents=True, exist_ok=True)
        claim_path = claims_dir / "bad_claim.json"
        claim_path.write_text(json.dumps({"status": "claimed_before_client_creation"}), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            check_prior_claim(self.batch_dir, claim_path)
        self.assertIn("incomplete or interrupted", str(ctx.exception))

    def test_stale_proposal_detection(self):
        plan = production_plan("main")
        fake_snap = copy.deepcopy(self.snapshot)
        fake_snap["checked_at_utc"] = "2020-01-01T00:00:00+00:00"
        with self.assertRaises(ValueError):
            with patch("src.research.report2_production.validate_snapshot", side_effect=ValueError("Gateway snapshot must be timezone-aware, recent within 24 hours")):
                verify_production_proposal({"proposal_sha256": "bad", "cohort": "main", "plan_sha256": "bad", "gateway_snapshot_sha256": "bad", "old_allowance": {}}, fake_snap, root=ROOT)


class TestProductionCLI(unittest.TestCase):
    def test_cli_plan(self):
        import subprocess, sys
        cmd = [sys.executable, str(ROOT / "scripts/run_report2_production.py"), "--plan", "--cohort", "main"]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data["cohort"], "main")
        self.assertEqual(data["total_branches"], 432)
        self.assertEqual(data["total_decisions"], 6048)

    def test_cli_baseline_plan(self):
        import subprocess, sys
        cmd = [sys.executable, str(ROOT / "scripts/run_report2_production.py"), "--baseline-plan", "--cohort", "all"]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data["total_baseline_branches"], 576)


if __name__ == "__main__":
    unittest.main()
