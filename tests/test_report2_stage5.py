import unittest

import numpy as np
import pandas as pd

from src.analysis.report2_stage5 import (
    OUTCOMES, block_means, describe, history_contrasts, paired_contrasts, recovery_delay, reliability,
)


def days(values_by_day, default):
    """14-element sequence for days 8..21 with overrides {day: value}."""
    return [values_by_day.get(d, default) for d in range(8, 22)]


class TestRecoveryRule(unittest.TestCase):
    control = days({}, 100.0)

    def test_immediate_recovery_at_day_15(self):
        self.assertEqual(recovery_delay(days({}, 100.0), days({}, 0), self.control), 1)

    def test_onset_day_19_qualifying_through_day_21(self):
        inv = days({d: 0.0 for d in range(8, 19)}, 100.0)
        self.assertEqual(recovery_delay(inv, days({}, 0), self.control), 5)

    def test_onset_after_day_19_is_censored(self):
        inv = days({d: 0.0 for d in range(8, 20)}, 100.0)
        self.assertIsNone(recovery_delay(inv, days({}, 0), self.control))

    def test_lost_sales_break_the_run(self):
        lost = days({16: 3}, 0)
        self.assertEqual(recovery_delay(days({}, 100.0), lost, self.control), 3)  # 17,18,19

    def test_tolerance_is_inclusive_and_relative_to_control(self):
        self.assertEqual(recovery_delay(days({}, 120.0), days({}, 0), self.control), 1)
        self.assertIsNone(recovery_delay(days({}, 120.1), days({}, 0), self.control))

    def test_zero_control_inventory_uses_floor_of_one(self):
        zero = days({}, 0.0)
        self.assertEqual(recovery_delay(days({}, 0.2), days({}, 0), zero), 1)
        self.assertIsNone(recovery_delay(days({}, 0.3), days({}, 0), zero))


def llm_rows(block, scenario, contributions, history="full", elasticity=1.5):
    rows = []
    for r, c in enumerate(contributions):
        row = {k: 0.0 for k in OUTCOMES}
        row.update(block_id=block, scenario=scenario, history=history, elasticity=elasticity,
                   realization=r, contribution=c, fill_rate=1.0)
        rows.append(row)
    return rows


def base_rows(block, scenario, adaptive, fixed, elasticity=1.5):
    out = []
    for policy, c in (("adaptive", adaptive), ("fixed", fixed)):
        row = {k: 0.0 for k in OUTCOMES}
        row.update(block_id=block, scenario=scenario, elasticity=elasticity, policy=policy,
                   contribution=c, fill_rate=0.9)
        out.append(row)
    return out


class TestContrasts(unittest.TestCase):
    def setUp(self):
        llm = (llm_rows("B1", "control", [100, 110, 120]) + llm_rows("B1", "demand_surge", [90, 90, 120])
               + llm_rows("B1", "control", [80, 80, 80], history="none")
               + llm_rows("B1", "demand_surge", [60, 60, 60], history="none")
               + llm_rows("B1", "control", [110, 110, 110], history="frozen")
               + llm_rows("B1", "demand_surge", [130, 130, 130], history="frozen"))
        base = base_rows("B1", "control", 130, 50) + base_rows("B1", "demand_surge", 140, 40)
        self.blocks = block_means(pd.DataFrame(llm))
        self.contrasts = paired_contrasts(self.blocks, pd.DataFrame(base))

    def get(self, scenario, history="full"):
        c = self.contrasts
        return c[(c["scenario"] == scenario) & (c["history"] == history)].iloc[0]

    def test_realizations_averaged_before_contrast(self):
        self.assertAlmostEqual(self.get("control")["contribution"], 110)
        self.assertEqual(self.get("control")["realizations"], 3)
        self.assertEqual((self.get("demand_surge")["contribution_min"], self.get("demand_surge")["contribution_max"]), (90, 120))

    def test_raw_and_adjusted_signs(self):
        self.assertAlmostEqual(self.get("control")["raw_vs_adaptive"], -20)
        self.assertAlmostEqual(self.get("demand_surge")["raw_vs_adaptive"], -40)
        # (100 - 110) - (140 - 130) = -20
        self.assertAlmostEqual(self.get("demand_surge")["adjusted_vs_adaptive"], -20)
        self.assertTrue(np.isnan(self.get("control")["adjusted_vs_adaptive"]))
        self.assertAlmostEqual(self.get("demand_surge")["raw_vs_fixed"], 60)

    def test_control_adjustment_stays_within_history(self):
        # none: (60 - 80) - (140 - 130) = -30
        self.assertAlmostEqual(self.get("demand_surge", "none")["adjusted_vs_adaptive"], -30)

    def test_history_contrast_full_minus_ablation(self):
        h = history_contrasts(self.blocks, {"B1"})
        none = h[h["ablation"] == "none"].set_index("scenario")
        self.assertAlmostEqual(none.loc["control", "full_minus_ablation"], 30)
        self.assertAlmostEqual(none.loc["demand_surge", "full_minus_ablation"], 40)
        self.assertAlmostEqual(none.loc["demand_surge", "shock_minus_control"], 10)
        frozen = h[h["ablation"] == "frozen"].set_index("scenario")
        self.assertAlmostEqual(frozen.loc["demand_surge", "full_minus_ablation"], -30)
        self.assertAlmostEqual(frozen.loc["demand_surge", "shock_minus_control"], -30)

    def test_missing_baseline_fails(self):
        with self.assertRaises(ValueError):
            paired_contrasts(self.blocks, pd.DataFrame(base_rows("B1", "control", 1, 1)))


class TestSummaries(unittest.TestCase):
    def test_describe_counts_signs_and_ignores_missing(self):
        d = describe(pd.Series([-2.0, 0.0, 3.0, np.nan]))
        self.assertEqual((d["n_blocks"], d["n_positive"], d["n_negative"]), (3, 1, 1))
        self.assertEqual((d["min"], d["median"], d["max"]), (-2.0, 0.0, 3.0))

    def test_reliability_denominators(self):
        llm = pd.DataFrame([{
            "setting": "main", "completed_decisions": 14, "first_pass_valid": 10, "repair_attempts": 4,
            "successful_repairs": 3, "fallback_days": 1, "api_attempts": 18, "input_tokens": 1,
            "output_tokens": 1, "known_credits": 0.01, "latency_total": 28.0}] * 2)
        r = reliability(llm).iloc[0]
        self.assertEqual(r["scheduled_decisions"], 28)
        self.assertAlmostEqual(r["first_pass_valid_share"], 20 / 28)
        self.assertAlmostEqual(r["repair_success_rate"], 6 / 8)
        self.assertAlmostEqual(r["fallback_share"], 2 / 28)
        # first-pass valid + successful repairs + fallback = all decisions
        self.assertEqual(r["first_pass_valid"] + r["successful_repairs"] + r["fallback_days"], r["completed_decisions"])


if __name__ == "__main__":
    unittest.main()
