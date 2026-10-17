"""Research validity checks: native reuse, demand, stock, time and information."""
import hashlib
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

import pandas as pd

from src.data.kaggle import PROJECT_ROOT, prepare_dataset
from src.envs.kaggle_retailbench import KaggleRetailEnvironment, native
from src.agents.baselines import run_baseline


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.raw = PROJECT_ROOT / "data/raw/kaggle/sales_data.csv"
        cls.raw_hash = hashlib.sha256(cls.raw.read_bytes()).hexdigest()
        cls.prepared = cls.root / "prepared"
        cls.manifest = prepare_dataset(cls.raw, cls.prepared)
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        assert hashlib.sha256(cls.raw.read_bytes()).hexdigest() == cls.raw_hash
        cls.temp.cleanup()

    def environment(self, scenario="control"):
        type(self).counter += 1
        return KaggleRetailEnvironment(self.prepared, self.root / f"run-{self.counter}", scenario)

    def test_real_native_environment_and_tools(self):
        env = self.environment()
        self.assertIsInstance(env, native.RetailEnvironment)
        self.assertTrue((env.run_dir / "records/records.db").is_file())
        self.assertIn("place_order", env.get_tools())
        self.assertNotIn("view_today_news", env.get_tools())

    def test_sales_use_kaggle_and_deplete_stock_without_reviews(self):
        env = self.environment()
        sku = next(iter(env.catalog))
        opening = len(env.inventory.items_by_sku.get(sku, []))
        expected = float(pd.read_csv(self.prepared / "episode.csv").iloc[0]["Demand"])
        env.step()
        row = env.ledger[-1]
        self.assertEqual(row["demand"], expected)
        self.assertEqual(row["sales"], min(opening, expected))
        self.assertEqual(len(env.inventory.items_by_sku.get(sku, [])), opening - row["sales"])
        self.assertFalse(env.review_manager.enabled)

    def test_empty_inventory_still_has_unmet_demand(self):
        env = self.environment()
        env.inventory.items_by_sku.clear()
        env.step()
        self.assertGreater(env.ledger[-1]["demand"], 0)
        self.assertEqual(env.ledger[-1]["sales"], 0)
        self.assertEqual(env.ledger[-1]["lost_sales"], env.ledger[-1]["demand"])

    def test_order_arrives_before_sales_on_correct_day(self):
        env = self.environment()
        sku = next(iter(env.catalog))
        env.inventory.items_by_sku.clear()
        env.place_order([{"sku_id": sku, "quantity": 7}], "assumed_supplier")
        self.assertEqual(env.order_manager.get_current_orders()[0].expected_delivery_date, env.start_date + timedelta(days=2))
        env.step()
        self.assertEqual(env.ledger[-1]["sales"], 0)
        env.step()
        self.assertEqual(env.ledger[-1]["sales"], 0)
        self.assertEqual(len(env.inventory.items_by_sku[sku]), 7)
        env.step()
        self.assertEqual(env.ledger[-1]["opening_inventory"], 7)

    def test_delivery_shock_does_not_reschedule_existing_orders(self):
        env = self.environment("delivery_disruption")
        for _ in range(6):
            env.step()
        sku = next(iter(env.catalog))
        env.place_order([{"sku_id": sku, "quantity": 1}], "assumed_supplier")
        previous = env.order_manager.get_current_orders()[0].expected_delivery_date
        env.step()  # Day 8: disruption starts.
        env.place_order([{"sku_id": sku, "quantity": 2}], "assumed_supplier")
        orders = env.order_manager.get_current_orders()
        self.assertEqual(orders[0].expected_delivery_date, previous)
        self.assertEqual(orders[-1].expected_delivery_date, env.current_date + timedelta(days=5))

    def test_price_response_and_invalid_prices(self):
        low, high = self.environment(), self.environment()
        sku = next(iter(low.catalog))
        reference = low.catalog[sku]["reference_price"]
        low.modify_sku_price(sku, reference * 0.9)
        high.modify_sku_price(sku, reference * 1.1)
        low.step()
        high.step()
        self.assertGreater(low.ledger[-1]["demand"], high.ledger[-1]["demand"])
        with self.assertRaises(ValueError):
            high.modify_sku_price(sku, float("nan"))
        with self.assertRaises(ValueError):
            high.modify_sku_price(sku, reference * 2)

    def test_future_information_is_absent_and_history_is_copied(self):
        env = self.environment("demand_surge")
        observation = env.observe()
        text = json.dumps(observation)
        self.assertNotIn("shock_start", text)
        self.assertNotIn("demand_surge", text)
        for product in observation["products"].values():
            self.assertTrue(all(row["date"] < observation["date"] for row in product["history"]))
        sku = next(iter(env.catalog))
        observation["products"][sku]["history"][0]["reference_demand"] = -999
        self.assertNotEqual(env.observe()["products"][sku]["history"][0]["reference_demand"], -999)

    def test_boundary_and_no_reset_from_future_csv_inventory(self):
        env = self.environment()
        sku = next(iter(env.catalog))
        initial = env.catalog[sku]["initial_inventory"]
        for _ in range(21):
            env.step()
        self.assertTrue(env.done)
        self.assertEqual(sum(row["sales"] for row in env.ledger), initial)
        self.assertEqual(len(env.inventory.items_by_sku.get(sku, [])), 0)
        with self.assertRaises(RuntimeError):
            env.step()

    def test_same_starting_conditions_across_scenarios(self):
        control, surge = self.environment(), self.environment("demand_surge")
        self.assertEqual(control.observe(), surge.observe())
        for _ in range(8):
            control.step()
            surge.step()
        self.assertEqual(control.ledger[:7], [dict(row, scenario="control") for row in surge.ledger[:7]])
        self.assertGreater(surge.ledger[7]["demand"], control.ledger[7]["demand"])

    def test_baseline_reruns_match_and_cash_is_reconciled(self):
        a, sa = run_baseline(self.prepared, self.root / "repeat-a", policy="adaptive")
        b, sb = run_baseline(self.prepared, self.root / "repeat-b", policy="adaptive")
        pd.testing.assert_frame_equal(a, b)
        self.assertEqual(sa, sb)
        self.assertAlmostEqual(sa["net_worth_change"], sa["contribution"], places=6)
        self.assertEqual(len(a), 21)
        self.assertTrue((a["closing_inventory"] >= 0).all())

    def test_daily_order_limit_includes_multiple_calls(self):
        env = self.environment()
        sku = next(iter(env.catalog))
        maximum = env.catalog[sku]["max_order_quantity"]
        env.place_order([{"sku_id": sku, "quantity": maximum}], "assumed_supplier")
        with self.assertRaises(ValueError):
            env.place_order([{"sku_id": sku, "quantity": 1}], "assumed_supplier")

    def test_prepared_checksum_rejects_tampering(self):
        import shutil
        target = self.root / "tampered"
        shutil.copytree(self.prepared, target)
        with (target / "episode.csv").open("a") as handle:
            handle.write("\n")
        with self.assertRaises(ValueError):
            KaggleRetailEnvironment(target, self.root / "tampered-run")


if __name__ == "__main__":
    unittest.main()
