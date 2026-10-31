"""Matched-prefix, information-treatment, replay and manual execution regressions."""
import copy
import importlib.util
import json
import random
import runpy
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import numpy as np

from src.agents.baselines import choose_actions
from src.experiments.report2 import (ROOT, advance, create_prefix, economic_state, evidence_hashes,
    restore_prefix, rng_state, run_branch, simulator_rng, treat_history, validate_branch)
from src.experiments.report2_fixtures import prepare_case, scripted_policy
from src.experiments.kaggle_protocol import write
from src.research.report2 import PROTOCOL, canonical_hash, read_json


class Report2RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.protocol = read_json(ROOT / PROTOCOL)
        cls.case = cls.protocol["sampling"]["development_cases"][0]
        cls.prepared = prepare_case(cls.case, cls.root / "prepared")
        cls.prefix = create_prefix(cls.prepared, cls.root / "prefix")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def path(self, suffix):
        return self.root / f"{self._testMethodName}_{suffix}"

    def branch(self, suffix, *, history="full", policy="adaptive", decide=None):
        path = self.path(suffix)
        summary = run_branch(self.prepared, self.prefix, path, scenario="control", history=history,
                             policy=policy, decide=decide)
        return path, summary

    def rebind(self, run):
        manifest = read_json(run / "run_manifest.json")
        manifest["evidence_sha256"] = evidence_hashes(run)
        write(run / "run_manifest.json", manifest)

    def test_disk_prefix_restores_identical_state_before_every_shock(self):
        prefix = read_json(self.root / "prefix/prefix.json")
        for scenario in self.protocol["branching"]["conditions"]:
            env = restore_prefix(self.prepared, prefix, self.path(scenario), scenario)
            self.assertEqual(economic_state(env), prefix["state"])
            self.assertEqual((env.current_date - env.start_date).days, 7)
            self.assertEqual(env.observe()["lead_days"], 5 if scenario == "delivery_disruption" else 2)

    def test_rehashed_prefix_fund_edit_fails_economic_replay(self):
        changed = copy.deepcopy(self.prefix)
        changed["state"]["funds"] += 1
        changed["state_sha256"] = canonical_hash(changed["state"])
        changed["prefix_sha256"] = canonical_hash({k: v for k, v in changed.items() if k != "prefix_sha256"})
        with self.assertRaisesRegex(ValueError, "Restored cash"):
            restore_prefix(self.prepared, changed, self.path("edited"), "control")

    def test_frozen_and_empty_histories_remain_treated_through_fallback(self):
        for history in ("full", "frozen", "none"):
            decide, calls = scripted_policy(self.protocol["model"])
            run, summary = self.branch(history, history=history, policy="scripted_fixture", decide=decide)
            self.assertEqual((summary["first_pass_valid"], summary["successful_repairs"], summary["fallback_days"], len(calls)), (12, 1, 1, 16))
            observations = [json.loads(s)["observation"] for s in (run / "observations.jsonl").read_text().splitlines()]
            actions = [json.loads(s) for s in (run / "actions.jsonl").read_text().splitlines()]
            sku = self.case["product_id"]
            for observation in observations:
                rows = observation["products"][sku]["history"]
                self.assertTrue(all(row["date"] < observation["date"] for row in rows))
                if history == "none":
                    self.assertEqual(rows, [])
                if history == "frozen":
                    self.assertEqual(rows, observations[0]["products"][sku]["history"])
            self.assertEqual(actions[1]["actions"], choose_actions(observations[1], "adaptive"))
            validate_branch(self.prepared, self.prefix, run, self.path("replay_" + history))

    def test_history_treatment_does_not_mutate_state_or_expose_future_rows(self):
        env = restore_prefix(self.prepared, self.prefix, self.path("env"), "control")
        original = env.observe()
        frozen = {sku: p["history"] for sku, p in original["products"].items()}
        empty = treat_history(original, "none", frozen)
        empty["products"][self.case["product_id"]]["inventory"] = -100
        self.assertEqual(env.observe(), original)
        env._episode.loc[:, "Demand"] = 999999
        self.assertEqual(env.observe(), original)
        bad = copy.deepcopy(original)
        bad["products"][self.case["product_id"]]["history"][0]["date"] = original["date"]
        with self.assertRaisesRegex(ValueError, "future"):
            treat_history(bad, "full", frozen)

    def test_rng_is_restored_and_fixture_randomness_cannot_change_transitions(self):
        before = rng_state()
        env = restore_prefix(self.prepared, self.prefix, self.path("rng"), "control")
        observation = env.observe()
        advance(env, observation, choose_actions(observation, "adaptive"))
        self.assertEqual(rng_state(), before)
        first, _ = self.branch("first")
        for _ in range(37):
            random.random()
        second, _ = self.branch("second")
        pd.testing.assert_frame_equal(pd.read_csv(first / "daily_results.csv"), pd.read_csv(second / "daily_results.csv"))
        quiet, _ = scripted_policy(self.protocol["model"])
        noisy, _ = scripted_policy(self.protocol["model"])

        def with_sdk_randomness(observation):
            random.random()
            np.random.normal(size=37)
            return noisy(observation)

        normal, _ = self.branch("normal_fixture", policy="scripted_fixture", decide=quiet)
        perturbed, _ = self.branch("noisy_fixture", policy="scripted_fixture", decide=with_sdk_randomness)
        pd.testing.assert_frame_equal(pd.read_csv(normal / "daily_results.csv"), pd.read_csv(perturbed / "daily_results.csv"))

    def test_delivery_disruption_preserves_existing_arrival_dates(self):
        env = restore_prefix(self.prepared, self.prefix, self.path("delivery"), "delivery_disruption")
        before = {o.order_id: o.expected_delivery_date for o in env.order_manager.get_current_orders()}
        self.assertTrue(before)
        with simulator_rng(env):
            env.place_order([{"sku_id": self.case["product_id"], "quantity": 1}], "assumed_supplier")
        for order in env.order_manager.get_current_orders():
            if order.order_id in before:
                self.assertEqual(order.expected_delivery_date, before[order.order_id])
            else:
                self.assertEqual(order.delivery_time, 5)

    def test_rehashed_summary_or_intervention_edit_is_rejected(self):
        decide, _ = scripted_policy(self.protocol["model"])
        run, _ = self.branch("original", policy="scripted_fixture", decide=decide)
        summary = read_json(run / "summary.json")
        summary["fallback_days"] += 1
        write(run / "summary.json", summary)
        self.rebind(run)
        with self.assertRaisesRegex(ValueError, "denominators"):
            validate_branch(self.prepared, self.prefix, run, self.path("replay"))

    def test_rehashed_observation_edit_is_rejected(self):
        run, _ = self.branch("original")
        rows = [json.loads(s) for s in (run / "observations.jsonl").read_text().splitlines()]
        rows[0]["observation"]["funds"] += 1
        rows[0]["sha256"] = canonical_hash(rows[0]["observation"])
        (run / "observations.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        self.rebind(run)
        with self.assertRaisesRegex(ValueError, "independent state"):
            validate_branch(self.prepared, self.prefix, run, self.path("replay"))

    def test_incomplete_branch_cannot_be_reissued_or_hidden(self):
        fail = Mock(side_effect=RuntimeError("scripted transport interruption"))
        run = self.path("partial")
        with self.assertRaises(RuntimeError):
            run_branch(self.prepared, self.prefix, run, scenario="control", policy="scripted_fixture", decide=fail)
        self.assertEqual(read_json(run / "run_manifest.json")["status"], "incomplete")
        retry = Mock()
        with self.assertRaises(FileExistsError):
            run_branch(self.prepared, self.prefix, run, scenario="control", policy="scripted_fixture", decide=retry)
        retry.assert_not_called()

    def test_model_branch_cannot_bypass_manual_runner(self):
        decide = Mock()
        with self.assertRaisesRegex(ValueError, "manual runner"):
            run_branch(self.prepared, self.prefix, self.path("denied"), scenario="control",
                       policy="llm_with_fallback", decide=decide)
        decide.assert_not_called()
        self.assertFalse(self.path("denied").exists())


class ManualPilotBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("manual_report2", ROOT / "scripts/run_report2_pilot.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_unapproved_or_wrong_branch_authorization_cannot_pass(self):
        plan = {"episodes": list(range(24)), "task_id": "report2:development"}
        auth = self.module.authorization_template(plan)
        with self.assertRaises(ValueError):
            self.module.validate_authorization(auth, {}, plan, 0)
        auth.update(approved=True, approval_reference="mock manual approval")
        with self.assertRaisesRegex(ValueError, "subset"):
            self.module.validate_authorization(auth, {}, plan, 1)

    def test_rejected_cli_never_loads_credentials(self):
        plan = {"episodes": list(range(24)), "task_id": "report2:development"}
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            write(folder / "auth.json", self.module.authorization_template(plan))
            write(folder / "budget.json", {})
            argv = ["run_report2_pilot.py", "--execute-model", "--branch-index", "0",
                    "--authorization", str(folder / "auth.json"), "--budget", str(folder / "budget.json")]
            with patch("sys.argv", argv), patch("src.research.report2_runtime.verify_implementation"), \
                 patch("src.experiments.report2.development_plan", return_value=plan), \
                 patch("src.benchmarks.common.credentials") as credentials:
                with self.assertRaises(ValueError):
                    runpy.run_path(str(ROOT / "scripts/run_report2_pilot.py"), run_name="__main__")
                credentials.assert_not_called()

    def test_mocked_manual_transport_completes_once_and_blocks_a_second_call(self):
        """Exercise the manual positive path with scripted responses, never a real SDK transport."""
        protocol = read_json(ROOT / PROTOCOL)
        plan = {"task_id": "report2:development", "episodes": [
            {"case_id": c["id"], "scenario": s, "history": h, "realization": 0}
            for c in protocol["sampling"]["development_cases"]
            for s in protocol["branching"]["conditions"] for h in protocol["policies"]["history_variants"]]}
        allowance = {"approved": True, "allowed_tasks": [plan["task_id"]], "allowed_purposes": ["pilot"],
                     "rates_verified": True, "rates_source": "https://fixture.example/mock-tariff",
                     "rates_verified_at_utc": "2026-10-31T00:00:00Z", "cap_usd": 1,
                     "scope_caps_usd": {"kaggle": 1}, "rates": {protocol["model"]["requested_id"]: {}}}
        auth = self.module.authorization_template(plan)
        auth.update(approved=True, approval_reference="offline mock only", budget_sha256=self.module.budget_hash(allowance))
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            write(folder / "configs/report2/protocol.json", protocol)
            write(folder / "auth.json", auth)
            write(folder / "budget.json", allowance)
            counts = {"attempts": 0}
            scripted, _ = scripted_policy(protocol["model"])
            original_create = scripted.client.chat.completions.create
            request_folder = []

            def install(output, config, budget):
                output.mkdir(parents=True)
                request_folder.append(output)
                return counts

            def create(**kwargs):
                counts["attempts"] += 1
                with (request_folder[0] / "api_attempts.jsonl").open("a") as stream:
                    stream.write(json.dumps({"event": "started", "kind": "offline_mock"}) + "\n")
                return original_create(**kwargs)

            @contextmanager
            def client():
                yield SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

            argv = ["run_report2_pilot.py", "--execute-model", "--branch-index", "0",
                    "--authorization", str(folder / "auth.json"), "--budget", str(folder / "budget.json")]
            with patch.object(self.module, "ROOT", folder), patch("sys.argv", argv), \
                 patch("src.research.report2_runtime.verify_implementation"), \
                 patch("src.experiments.report2.development_plan", return_value=plan), \
                 patch("src.experiments.kaggle_protocol.require_existing_ledger"), \
                 patch("src.benchmarks.common.credentials", return_value=("fixture", "https://fixture.example/v1")), \
                 patch("src.benchmarks.budget.load_budget", return_value=SimpleNamespace(summary=lambda: {"offline_mock": True})), \
                 patch("src.benchmarks.common.install_gateway_clients", side_effect=install), \
                 patch("openai.OpenAI", side_effect=client):
                self.assertEqual(self.module.main(), 0)
                self.assertEqual(counts["attempts"], 16)
                with self.assertRaisesRegex(ValueError, "already ran"):
                    self.module.main()
                self.assertEqual(counts["attempts"], 16)
                (request_folder[0] / "api_attempts.jsonl").write_text("changed mock request log\n")
                with self.assertRaisesRegex(ValueError, "evidence changed"):
                    self.module.main()
                self.assertEqual(counts["attempts"], 16)


if __name__ == "__main__":
    unittest.main()
