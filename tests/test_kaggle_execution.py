"""Offline regression checks for duplicate spending and hidden invalid/mismatched evidence."""
import copy
import json
import runpy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from budget_fixture import manifest as budget_fixture
from src.benchmarks.budget import BudgetLedger
from src.benchmarks.common import ROOT
from src.benchmarks.errors import BudgetStop
from src.data.kaggle import prepare_dataset
from src.experiments.kaggle_fixtures import run_validation_fixture
from src.experiments.kaggle_protocol import (PRIMARY_TASK, read, write, primary_matrix, authorization_template,
    require_primary_authorization, require_episode_available, require_fallback_reviews, text_digest,
    failure_evidence_digest, remaining_primary_attempts, execution_lock, save_matrix_registry, require_existing_ledger,
    require_matching_baselines, episode_evidence_digest)
from src.experiments.kaggle_validation import validate_run
from src.research.design import canonical_hash


class ExecutionGatesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".cache")
        self.root = Path(self.temp.name)
        self.matrix = primary_matrix(read(ROOT / "configs/study.json"))

    def tearDown(self):
        self.temp.cleanup()

    def allowance(self):
        return {**budget_fixture(), "scope_caps_usd": {"kaggle": 1}, "allowed_purposes": ["evaluation"],
                "allowed_tasks": [PRIMARY_TASK], "evaluation_tasks": [PRIMARY_TASK]}

    def test_primary_authorization_rejects_unapproved_drift_or_wrong_scope(self):
        template = authorization_template(self.matrix)
        with self.assertRaises(ValueError):
            require_primary_authorization(template, self.allowance(), self.matrix)
        approved = {**template, "approved": True, "budget_id": "mock_only"}
        require_primary_authorization(approved, self.allowance(), self.matrix)
        for field, value in (("max_attempts", 505), ("matrix_sha256", "changed"), ("episode_ids", list(reversed(approved["episode_ids"])))):
            with self.assertRaises(ValueError):
                require_primary_authorization({**approved, field: value}, self.allowance(), self.matrix)
        with self.assertRaises(ValueError):
            require_primary_authorization(approved, {**self.allowance(), "evaluation_tasks": []}, self.matrix)

    def test_cli_rejects_primary_before_credentials_or_primary_data_access(self):
        auth = self.root / "unapproved.json"
        allowance = self.root / "allowance.json"
        write(auth, authorization_template(self.matrix))
        write(allowance, self.allowance())
        argv = ["run_kaggle_experiment.py", "--execute-paid", "--episode-index", "2",
                "--budget", str(allowance), "--execution-manifest", str(auth)]
        with patch("sys.argv", argv), patch("src.benchmarks.common.credentials") as credentials, patch("src.data.kaggle.prepare_dataset") as prepare:
            with self.assertRaises(ValueError):
                runpy.run_path(str(ROOT / "scripts/run_kaggle_experiment.py"), run_name="__main__")
            credentials.assert_not_called()
            prepare.assert_not_called()

    def test_complete_active_and_unreviewed_failed_episodes_cannot_be_reissued(self):
        folder = self.root / "prior"
        for status in ("validated_complete", "running", "execution_finished_requires_artifact_review", "incomplete"):
            write(folder / "run_manifest.json", {"episode_id": "logical", "status": status})
            with self.assertRaises(ValueError):
                require_episode_available(self.root, "logical")
            if status != "incomplete":
                with self.assertRaises(ValueError):
                    require_episode_available(self.root, "logical", retry_failed=True)
        write(folder / "actions.jsonl", {"partial": True})
        write(folder / "failure_review.json", {"status": "reviewed", "decision": "restart_complete_episode",
            "run_manifest_sha256": text_digest(folder / "run_manifest.json"), "evidence_sha256": failure_evidence_digest(folder)})
        self.assertEqual(require_episode_available(self.root, "logical", retry_failed=True), ["prior"])
        (folder / "actions.jsonl").write_text('changed after review\n')
        with self.assertRaises(ValueError):
            require_episode_available(self.root, "logical", retry_failed=True)

    def test_fallback_review_is_bound_to_actual_action_file(self):
        folder = self.root / "fallback"
        write(folder / "run_manifest.json", {"fallback_review_required": True})
        (folder / "actions.jsonl").write_text('{}\n')
        with self.assertRaises(ValueError):
            require_fallback_reviews(self.root)
        write(folder / "quality_review.json", {"status": "reviewed", "decision": "retain_frozen_operational_policy", "actions_sha256": text_digest(folder / "actions.jsonl")})
        require_fallback_reviews(self.root)
        (folder / "actions.jsonl").write_text('{}\n{}\n')
        with self.assertRaises(ValueError):
            require_fallback_reviews(self.root)

    def test_primary_attempt_ceiling_counts_incomplete_and_replacement_cohorts(self):
        identity = self.matrix["episodes"][2]["episode_id"]
        for name, count in (("interrupted", 300), ("replacement", 203)):
            folder = self.root / name
            write(folder / "run_manifest.json", {"episode_id": identity, "status": "incomplete"})
            (folder / "api_attempts.jsonl").write_text('\n'.join(json.dumps({"event": "started"}) for _ in range(count)) + '\n')
        self.assertEqual(remaining_primary_attempts(self.root, self.matrix), 1)
        with (self.root / "replacement/api_attempts.jsonl").open("a") as stream:
            stream.write('{"event":"started"}\n')
        self.assertEqual(remaining_primary_attempts(self.root, self.matrix), 0)

    def test_unreviewed_interruption_blocks_other_primary_paid_episodes_too(self):
        folder = self.root / "interrupted_primary"
        write(folder / "run_manifest.json", {"purpose": "evaluation", "policy": "llm_with_fallback", "status": "incomplete"})
        with self.assertRaises(ValueError):
            require_fallback_reviews(self.root)
        write(folder / "failure_review.json", {"status": "reviewed", "decision": "retain_incomplete_episode", "evidence_sha256": failure_evidence_digest(folder)})
        require_fallback_reviews(self.root)
        (folder / "api_attempts.jsonl").write_text('{"event":"started"}\n')
        with self.assertRaises(ValueError):
            require_fallback_reviews(self.root)

    def test_primary_llm_cannot_run_without_matching_validated_baselines(self):
        with self.assertRaises(ValueError):
            require_matching_baselines(self.root, self.matrix["episodes"][2])

    def test_exclusive_lock_and_immutable_matrix_registry(self):
        with execution_lock(self.root):
            with self.assertRaises(ValueError):
                with execution_lock(self.root):
                    self.fail("Concurrent episode acquired the same lock")
        self.assertFalse((self.root / ".kaggle_execution.lock").exists())
        path = save_matrix_registry(self.root, self.matrix)
        wrong = read(path)
        wrong["plan"]["horizon"] = 1
        write(path, wrong)
        with self.assertRaises(ValueError):
            save_matrix_registry(self.root, self.matrix)

    def test_primary_cannot_create_empty_ledger_or_reset_previous_exposure(self):
        allowance = {**budget_fixture(cap=.00005), "scope_caps_usd": {"kaggle": .00005}}
        with self.assertRaises(ValueError):
            require_existing_ledger(allowance, self.root)
        path = self.root / "mock_only.sqlite"
        first = BudgetLedger(allowance, path, run_id="earlier", scope="kaggle")
        with self.assertRaises(ValueError):
            require_existing_ledger(allowance, self.root)
        first.reserve("prior", "test", 10, 10)
        first.settle("prior", input_tokens=10, output_tokens=10)
        require_existing_ledger(allowance, self.root)
        second = BudgetLedger(allowance, path, run_id="later", scope="kaggle")
        self.assertEqual(second.summary()["attempts"], 1)
        self.assertEqual(second.summary()["exposure_usd"], first.summary()["exposure_usd"])
        with self.assertRaises(BudgetStop):
            second.reserve("new", "test", 10, 10)

    def test_explicit_primary_task_extension_preserves_existing_spending_and_holds(self):
        old = {**self.allowance(), "allowed_purposes": ["pilot", "evaluation"],
            "allowed_tasks": ["kaggle:validation_pilot"], "evaluation_tasks": ["kaggle:validation_pilot"]}
        path = self.root / "existing.sqlite"
        first = BudgetLedger(old, path, run_id="earlier", scope="kaggle")
        first.reserve("known", "test", 10, 10)
        first.settle("known", input_tokens=5, output_tokens=5)
        first.reserve("held", "test", 10, 10)
        first.settle("held", uncertain_reason="mock_only_unknown")
        before = first.summary()
        new = {**old, "approval_reference": "explicit mock-only primary task authorization",
            "allowed_tasks": ["kaggle:validation_pilot", PRIMARY_TASK],
            "evaluation_tasks": ["kaggle:validation_pilot", PRIMARY_TASK]}
        with self.assertRaises(BudgetStop):
            BudgetLedger.amend_allowance(old, new, path)
        with self.assertRaises(BudgetStop):
            BudgetLedger.amend_allowance(old, {**new, "allowed_tasks": [PRIMARY_TASK], "evaluation_tasks": [PRIMARY_TASK]}, path, authorize_evaluation=True)
        BudgetLedger.amend_allowance(old, new, path, authorize_evaluation=True)
        second = BudgetLedger(new, path, run_id="later", scope="kaggle")
        for field in ("attempts", "known_cost_usd", "unresolved_reserved_usd", "exposure_usd", "uncertain_attempts"):
            self.assertEqual(second.summary()[field], before[field])
        with self.assertRaises(BudgetStop):
            second.reserve("still_blocked_by_unknown", "test", 1, 1)


class IndependentKaggleReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / ".cache")
        cls.root = Path(cls.temp.name)
        cls.study = read(ROOT / "configs/study.json")
        cls.series = cls.study["kaggle"]["selection"]["selected_series"][0]
        prepared = cls.root / "inputs"
        prepare_dataset(ROOT / cls.study["dataset"]["path"], prepared, store_id=cls.series["store_id"],
            product_ids=[cls.series["product_id"]], episode_start="2023-04-02")
        for policy in ("adaptive", "scripted_fixture"):
            run_validation_fixture(cls.study, prepared, cls.root / policy, cls.series, "delivery_disruption", policy)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.case.cleanup)

    def clone(self, policy="adaptive"):
        destination = Path(self.case.name) / "episode"
        shutil.copytree(self.root / policy, destination)
        return destination

    def test_baseline_and_scripted_repairs_have_distinct_provenance(self):
        for policy, kind in (("adaptive", "baseline"), ("scripted_fixture", "scripted")):
            report = validate_run(self.root / policy)
            self.assertEqual(report["status"], "validated_complete", report["checks"])
            self.assertEqual(report["agent_kind"], kind)
            self.assertEqual(report["api_attempts"], 0)
            self.assertTrue(report["checks"]["private_demand_hidden_every_day"])

    def test_missing_day_and_mislabeled_primary_cannot_pass(self):
        folder = self.clone()
        path = folder / "observations.jsonl"
        path.write_text('\n'.join(path.read_text().splitlines()[:-1]) + '\n')
        self.assertNotEqual(validate_run(folder)["status"], "validated_complete")
        manifest = read(folder / "run_manifest.json")
        manifest["primary_evaluation"] = True
        write(folder / "run_manifest.json", manifest)
        self.assertFalse(validate_run(folder)["checks"]["provenance"])

    def test_rehashed_changed_observation_still_fails_independent_replay(self):
        folder = self.clone()
        path = folder / "observations.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines()]
        records[0]["observation"]["funds"] += 1
        from src.agents.llm import serialize_observation
        import hashlib
        records[0]["sha256"] = hashlib.sha256(serialize_observation(records[0]["observation"]).encode()).hexdigest()
        path.write_text('\n'.join(json.dumps(r) for r in records) + '\n')
        report = validate_run(folder)
        self.assertTrue(report["checks"]["observation_hashes"])
        self.assertFalse(report["checks"]["saved_observations_match_replay"])

    def test_changed_daily_contribution_or_fallback_flags_cannot_be_hidden(self):
        folder = self.clone("scripted_fixture")
        import pandas as pd
        path = folder / "daily_results.csv"
        frame = pd.read_csv(path)
        frame.loc[0, "contribution"] += 10
        frame.loc[:, "fallback_used"] = False
        frame.to_csv(path, index=False)
        report = validate_run(folder)
        self.assertFalse(report["checks"]["saved_daily_ledger_matches_replay"])
        self.assertFalse(report["checks"]["repair_fallback_exports"])

    def test_scripted_fixture_cannot_be_presented_as_genuine_llm(self):
        folder = self.clone("scripted_fixture")
        manifest = read(folder / "run_manifest.json")
        manifest["agent_kind"] = "genuine_llm"
        write(folder / "run_manifest.json", manifest)
        self.assertFalse(validate_run(folder)["checks"]["provenance"])

    def test_saved_validation_is_bound_to_action_and_response_evidence(self):
        folder = self.clone()
        validation = validate_run(folder)
        self.assertEqual(validation["evidence_sha256"], episode_evidence_digest(folder))
        with (folder / "actions.jsonl").open("a") as stream:
            stream.write('{}\n')
        self.assertNotEqual(validation["evidence_sha256"], episode_evidence_digest(folder))


if __name__ == "__main__":
    unittest.main()
