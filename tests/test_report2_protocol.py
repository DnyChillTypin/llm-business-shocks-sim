"""Sampling must ignore evaluation outcomes and preserve explicit execution boundaries."""
import copy
import unittest

import pandas as pd

from src.research.report2 import ROOT, PROTOCOL, read_json, sample_series, validate_protocol, workload


class Report2ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = read_json(ROOT / PROTOCOL)
        dates = pd.date_range("2022-01-01", "2024-01-30")
        legacy = [(r["store_id"], r["product_id"])
                  for r in cls.protocol["sampling"]["legacy_series_excluded"]]
        keys = legacy + [(f"T{i % 5}", f"P{i:03d}") for i in range(18)]
        cls.frame = pd.DataFrame([
            {"Date": date, "Store ID": store, "Product ID": product,
             "Demand": 50 + (day % 5) * (index + 1)}
            for index, (store, product) in enumerate(keys) for day, date in enumerate(dates)
        ])

    def test_held_out_demand_cannot_change_selection_or_training_statistics(self):
        changed = self.frame.copy()
        changed.loc[changed["Date"] > "2023-04-01", "Demand"] = 1e12
        self.assertEqual(sample_series(self.frame, self.protocol), sample_series(changed, self.protocol))

    def test_row_order_cannot_change_selection(self):
        self.assertEqual(sample_series(self.frame, self.protocol),
                         sample_series(self.frame.sample(frac=1, random_state=12), self.protocol))

    def test_development_and_legacy_series_are_absent_from_evaluation(self):
        selected = sample_series(self.frame, self.protocol)["selected_series"]
        keys = {(r["store_id"], r["product_id"]) for r in selected}
        legacy = {(r["store_id"], r["product_id"])
                  for r in self.protocol["sampling"]["legacy_series_excluded"]}
        self.assertEqual(len(keys), 12)
        self.assertFalse(keys & legacy)
        self.assertEqual(sum(r["diagnostic_subset"] for r in selected), 6)

    def test_insufficient_coverage_does_not_silently_reduce_the_target(self):
        reduced = self.frame.loc[~self.frame["Product ID"].isin([f"P{i:03d}" for i in range(7)])]
        with self.assertRaisesRegex(ValueError, "Insufficient eligible"):
            sample_series(reduced, self.protocol)

    def test_duplicate_series_date_is_rejected(self):
        frame = pd.concat([self.frame, self.frame.iloc[:1]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "unique"):
            sample_series(frame, self.protocol)

    def test_overlapping_evaluation_and_out_of_split_development_are_rejected(self):
        overlap = copy.deepcopy(self.protocol)
        overlap["sampling"]["evaluation_windows"][1].update(start="2023-11-23", end="2023-12-13")
        with self.assertRaisesRegex(ValueError, "non-overlapping"):
            validate_protocol(overlap)
        leak = copy.deepcopy(self.protocol)
        leak["sampling"]["development_cases"][0].update(start="2023-11-03", end="2023-11-23")
        with self.assertRaisesRegex(ValueError, "validation dates"):
            validate_protocol(leak)

    def test_model_authorization_cannot_be_enabled_in_this_milestone(self):
        changed = copy.deepcopy(self.protocol)
        changed["execution"]["model_calls_authorized"] = True
        with self.assertRaisesRegex(ValueError, "manual only"):
            validate_protocol(changed)

    def test_diagnostic_selection_cannot_duplicate_a_series(self):
        changed = copy.deepcopy(self.protocol)
        changed["sampling"]["diagnostic_selected_indices_zero_based"] = [0, 0, 4, 7, 9, 11]
        with self.assertRaisesRegex(ValueError, "distinct"):
            validate_protocol(changed)

    def test_workload_reuses_controls_without_counting_them_as_new_calls(self):
        counts = workload(self.protocol)
        self.assertEqual(counts["main_llm_decisions"], 6048)
        self.assertEqual(counts["additional_history_llm_decisions"], 6048)
        self.assertEqual(counts["additional_elasticity_llm_decisions"], 6048)
        self.assertEqual(counts["production_llm_decisions"], 18144)
        self.assertEqual(counts["production_max_completions_before_transport_retries"], 36288)
        self.assertEqual(counts["development_llm_decisions"], 336)
        self.assertEqual(counts["production_baseline_branches"], 576)
        self.assertIsNone(counts["monetary_estimate"])


if __name__ == "__main__":
    unittest.main()
