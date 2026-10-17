"""Selection must not depend on later demand, prices or stock outcomes."""
import unittest
import json
import tempfile
from pathlib import Path

import pandas as pd

from src.research.design import training_selection, text_hash, validate_design


class ResearchDesignTests(unittest.TestCase):
    def frame(self):
        dates = pd.date_range("2020-01-01", periods=20)
        return pd.DataFrame([
            {"Date": date, "Store ID": "S1", "Product ID": f"P{product}",
             "Demand": 20 + (day % 3 - 1) * product, "Price": 10, "Inventory Level": 50,
             "Units Sold": 10, "Units Ordered": 10}
            for product in range(1, 5) for day, date in enumerate(dates)
        ])

    def test_held_out_outcomes_cannot_change_series_selection(self):
        original = self.frame()
        before = training_selection(original, 0.6, [0.25, 0.5, 0.75])
        changed = original.copy()
        changed.loc[changed["Date"] > "2020-01-12",
                    ["Demand", "Price", "Inventory Level", "Units Sold", "Units Ordered"]] = 1e9
        after = training_selection(changed, 0.6, [0.25, 0.5, 0.75])
        self.assertEqual(before, after)

    def test_ties_and_input_order_have_deterministic_selection(self):
        frame = self.frame()
        frame["Demand"] = 20
        first = training_selection(frame, 0.6, [0.25, 0.5, 0.75])
        shuffled = training_selection(frame.sample(frac=1, random_state=7), 0.6, [0.25, 0.5, 0.75])
        self.assertEqual(first, shuffled)
        self.assertEqual([s["product_id"] for s in first[1]], ["P2", "P3", "P4"])

    def test_changed_frozen_configuration_is_rejected_before_data_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "configs").mkdir()
            (root / "docs/results").mkdir(parents=True)
            config = root / "configs/study.json"
            config.write_text('{"study_id": "original"}', encoding="utf-8")
            freeze = {"artifact_text_sha256": {"configs/study.json": text_hash(config)}}
            (root / "docs/results/study_design_manifest.json").write_text(json.dumps(freeze), encoding="utf-8")
            config.write_text('{"study_id": "changed"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen_text_artifacts"):
                validate_design(root)
