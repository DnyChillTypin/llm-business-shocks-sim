"""Offline contract/leakage/accounting checks; no genuine model results."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.agents.baselines import choose_actions, run_baseline
from src.agents.llm import LLMPolicy, decode_action, serialize_observation
from src.benchmarks.common import ROOT
from src.benchmarks.errors import GatewayFailure
from src.data.kaggle import prepare_dataset
from src.envs.kaggle_retailbench import KaggleRetailEnvironment, SCENARIOS
from src.experiments.kaggle import apply_actions, run_episode


class KagglePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.prepared = cls.root / "prepared"
        cls.manifest = prepare_dataset(ROOT / "data/raw/kaggle/sales_data.csv", cls.prepared,
            store_id="S001", product_ids=["P0001"], episode_start="2023-04-02")
        cls.settings = json.loads((ROOT / "configs/study.json").read_text())["kaggle"]["model"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def env(self, name, scenario="control"):
        return KaggleRetailEnvironment(self.prepared, self.root / name, scenario)

    def test_validation_window_preserves_training_and_split_boundaries(self):
        self.assertEqual(self.manifest["train_end"], "2023-04-01")
        self.assertEqual(self.manifest["test_start"], "2023-04-02")
        self.assertEqual(self.manifest["episode_end"], "2023-04-22")
        self.assertEqual(self.manifest["validation_end"], "2023-08-31")
        self.assertAlmostEqual(self.manifest["catalog"][0]["training_mean_demand"], 91.662280701754)

    def test_invalid_portfolio_is_atomic_and_not_coerced(self):
        env = self.env("atomic")
        observation = env.observe()
        sku = next(iter(observation["products"]))
        before = serialize_observation(observation)
        invalid = [
            {sku: {"order_quantity": 1.0, "price_multiplier": .9}},
            {sku: {"order_quantity": True, "price_multiplier": .9}},
            {sku: {"order_quantity": 0, "price_multiplier": 1.05}},
            {sku: {"order_quantity": 0, "price_multiplier": .9, "extra": 1}},
            {sku: {"order_quantity": 0, "price_multiplier": .9}, "EXTRA": {}},
            {sku: {"order_quantity": 10**9, "price_multiplier": .9}},
        ]
        tight = json.loads(before)
        tight["funds"] = 0
        with self.assertRaises(ValueError):
            decode_action(json.dumps({sku: {"order_quantity": 1, "price_multiplier": 1}}), tight)
        for action in invalid:
            with self.assertRaises(ValueError):
                apply_actions(env, observation, action)
            self.assertEqual(serialize_observation(env.observe()), before)
        with self.assertRaises(ValueError):
            decode_action('{"P0001":{},"P0001":{}}', observation)

    def test_private_future_and_scenario_label_do_not_change_current_serialization(self):
        control = self.env("privacy_control")
        disrupted = self.env("privacy_delivery", "delivery_disruption")
        original = serialize_observation(control.observe())
        control._episode.loc[:, "Demand"] = 100000
        self.assertEqual(original, serialize_observation(control.observe()))
        self.assertEqual(original, serialize_observation(disrupted.observe()))
        for product in control.observe()["products"].values():
            self.assertTrue(all(row["date"] < control.observe()["date"] for row in product["history"]))
        self.assertNotIn("scenario", original)

    def test_shared_runner_matches_legacy_baselines_and_mock_completes_all_scenarios(self):
        for scenario in SCENARIOS:
            for policy in ("fixed", "adaptive"):
                legacy, summary = run_baseline(self.prepared, self.root / f"legacy_{scenario}_{policy}", scenario=scenario, policy=policy)
                shared, other = run_episode(self.prepared, self.root / f"shared_{scenario}_{policy}", scenario=scenario, policy=policy)
                pd.testing.assert_frame_equal(legacy, shared[legacy.columns])
                self.assertEqual(summary, {key: other[key] for key in summary})
            def scripted(observation):
                return choose_actions(observation, "adaptive"), {"source": "scripted_fixture", "fallback_used": False,
                    "repair_attempted": False, "invalid_responses": 0}
            frame, summary = run_episode(self.prepared, self.root / f"scripted_{scenario}", scenario=scenario,
                policy="scripted_not_llm", decide=scripted)
            self.assertEqual(summary["days"], 21)
            self.assertTrue(summary["accounting_reconciled"])
            self.assertEqual(len(frame), 21)

    def client(self, answers):
        sequence = iter(answers)
        def create(**kwargs):
            answer = next(sequence)
            if isinstance(answer, BaseException):
                raise answer
            if isinstance(answer, SimpleNamespace):
                return answer
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=answer))])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def test_repair_and_fallback_survive_daily_exports(self):
        observation = self.env("repair_observation").observe()
        valid = json.dumps(choose_actions(observation, "adaptive"))
        repaired = LLMPolicy(self.client(["bad", valid]), self.settings)
        _, detail = repaired(observation)
        self.assertTrue(detail["repair_attempted"])
        self.assertFalse(detail["fallback_used"])
        empty = LLMPolicy(self.client([SimpleNamespace(choices=[]), valid]), self.settings)
        _, detail = empty(observation)
        self.assertEqual(detail["invalid_responses"], 1)
        self.assertFalse(detail["fallback_used"])
        fallback = LLMPolicy(self.client(["bad"] * 42), self.settings)
        frame, summary = run_episode(self.prepared, self.root / "fallback", policy="llm_with_fallback", decide=fallback)
        self.assertEqual(summary["fallback_days"], 21)
        self.assertEqual(summary["invalid_responses"], 42)
        self.assertTrue(frame["fallback_used"].all())
        saved = pd.read_csv(self.root / "fallback/daily_results.csv")
        self.assertTrue(saved["fallback_used"].all())
        with self.assertRaises(GatewayFailure):
            LLMPolicy(self.client([GatewayFailure("scripted outage")]), self.settings)(observation)
