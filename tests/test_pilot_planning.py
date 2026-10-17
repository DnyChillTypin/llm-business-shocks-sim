import unittest

from src.benchmarks.common import ROOT, TASKS
from src.benchmarks.planning import run_plan


class PilotPlanningTests(unittest.TestCase):
    def test_all_task_families_have_bounded_pilots(self):
        for task in TASKS:
            plan = run_plan(task, config_path=ROOT / "configs/pilots/native.json")
            self.assertEqual(plan["purpose"], "pilot")
            self.assertFalse(plan["paid_calls_authorized_by_plan"])
            if task.startswith("retail:"):
                self.assertEqual(plan["configured_horizon"], 1)
            elif task == "icbe":
                self.assertEqual((plan["expected_units"], plan["configured_horizon"]), (6, 2))
            elif task == "firm:beergame":
                self.assertEqual((plan["expected_units"], plan["configured_horizon"]), (1, 25))
            elif task == "firm:edt":
                self.assertEqual((plan["expected_units"], plan["configured_horizon"]), (1, 96))
            else:
                self.assertEqual(plan["expected_units"], 1)

    def test_consulting_pilot_is_the_first_frozen_selected_case(self):
        plan = run_plan("firm:consulting", config_path=ROOT / "configs/pilots/native.json")
        self.assertEqual(plan["selected_case_ids"], ["case_0040"])

    def test_evaluation_cannot_be_shortened_or_model_substituted_by_pilot_config(self):
        with self.assertRaises(ValueError):
            run_plan("retail:dynamic_middle", config_path=ROOT / "configs/pilots/native.json", purpose="evaluation")
        with self.assertRaises(ValueError):
            run_plan("firm:FinCode", case_limit=1)
        with self.assertRaises(ValueError):
            run_plan("firm:FinCode", config_path={"purpose": "pilot", "settings": {"primary_model": "different"}})

    def test_full_evaluation_keeps_native_coverage(self):
        self.assertEqual(run_plan("firm:FinCode")["expected_units"], 7)
        self.assertEqual(run_plan("firm:consulting")["expected_units"], 10)
        self.assertEqual(run_plan("retail:dynamic_middle")["configured_horizon"], 180)
