import unittest

import pandas as pd

from src.analysis.metrics import relative_gain, interaction, service, recovery, behavioral_response, checked_days, episode_financials


def days(inventory=0, lost=0):
    return pd.DataFrame(dict(episode_day=range(1, 22), closing_inventory=[inventory] * 21, lost_sales=[lost] * 21,
        order_quantity=[0] * 21, price_multiplier=[1.] * 21))


class FrozenAnalysisTests(unittest.TestCase):
    def test_raw_underperformance_can_have_a_positive_control_adjusted_response(self):
        self.assertLess(-8 - (-1), 0)
        self.assertEqual(interaction(-8, -10, -1, 0), 3)

    def test_relative_gain_uses_absolute_negative_baseline_and_near_zero_na(self):
        self.assertEqual(relative_gain(-5, -10), 50)
        self.assertIsNone(relative_gain(2, 1e-9))
        self.assertIsNone(relative_gain(-2, -1e-10))

    def test_service_is_demand_weighted_and_zero_demand_explicit(self):
        f = pd.DataFrame(dict(demand=[1, 99], sales=[1, 0], lost_sales=[0, 99]))
        self.assertEqual(service(f)["fill_rate"], .01)
        self.assertFalse(service(f)["zero_demand"])
        f.loc[:, ["demand", "sales", "lost_sales"]] = 0
        self.assertEqual(service(f)["fill_rate"], 1)
        self.assertTrue(service(f)["zero_demand"])

    def test_first_recovery_start_needs_three_observed_days(self):
        r = recovery(days(10), days(10))
        self.assertEqual((r["recovery_start_day"], r["confirmation_day"], r["recovery_delay_days"]), (15, 17, 1))

    def test_last_admissible_start_is_day_19_confirmed_at_21(self):
        s = days(20)
        s.loc[s.episode_day >= 19, "closing_inventory"] = 10
        r = recovery(s, days(10))
        self.assertEqual((r["recovery_start_day"], r["confirmation_day"], r["recovery_delay_days"]), (19, 21, 5))

    def test_two_terminal_qualifying_days_remain_censored_not_imputed(self):
        s = days(20)
        s.loc[s.episode_day >= 20, "closing_inventory"] = 10
        r = recovery(s, days(10))
        self.assertTrue(r["right_censored"])
        self.assertIsNone(r["recovery_delay_days"])
        self.assertIsNone(r["recovery_start_day"])

    def test_recovery_uses_one_unit_floor_and_each_days_lost_sales(self):
        s = days(.2)
        self.assertEqual(recovery(s, days(0))["recovery_start_day"], 15)
        s.loc[s.episode_day == 16, "lost_sales"] = 1
        self.assertEqual(recovery(s, days(0))["recovery_start_day"], 17)
        self.assertTrue(recovery(days(.21), days(0))["right_censored"])

    def test_missing_or_duplicate_days_stop_instead_of_filling(self):
        for f in (days().iloc[:-1], pd.concat([days().iloc[:-1], days().iloc[[0]]])):
            with self.assertRaises(ValueError):
                checked_days(f)

    def test_pre_shock_divergence_is_reported_but_response_starts_at_eight(self):
        s = days()
        s.loc[s.episode_day == 2, "order_quantity"] = 2
        s.loc[s.episode_day == 10, "price_multiplier"] = 1.1
        r = behavioral_response(s, days())
        self.assertEqual((r["pre_shock_different_action_days"], r["first_divergence_day"]), (1, 10))

    def test_terminal_arrival_is_on_hand_and_unarrived_order_remains_pipeline(self):
        f = days()
        for key in ("arrivals_next_day", "sales", "revenue", "holding_cost", "contribution", "fallback_used", "repair_attempted", "invalid_responses", "demand"):
            f[key] = 0
        f["observed_funds"], f["observed_inventory"], f["observed_on_order"], f["unit_cost"] = 10., 0, 0, 2.
        f.loc[f.episode_day == 21, ["order_quantity", "arrivals_next_day"]] = [3, 1]
        r = episode_financials(f, 4.)
        self.assertEqual((r["terminal_on_hand_units"], r["terminal_pipeline_units"]), (1, 2))
        self.assertEqual(r["contribution"], 0)
        with self.assertRaises(ValueError):
            episode_financials(f, 5.)


if __name__ == "__main__":
    unittest.main()
