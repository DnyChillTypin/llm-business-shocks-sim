import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from budget_fixture import manifest
from src.benchmarks.budget import BudgetLedger
from src.benchmarks.errors import BudgetStop, DecisionFailure, GatewayFailure
from src.benchmarks.reasoning_records import recording_evaluator


class EvaluationTransitionTests(unittest.TestCase):
    def test_explicit_transition_preserves_attempts_and_unknown_holds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.sqlite"
            old = {**manifest(), "allowed_tasks": ["firm:FinCode", "retail:dynamic_middle"]}
            first = BudgetLedger(old, path, run_id="pilot")
            first.reserve("paid", "test", 10, 10)
            first.settle("paid", input_tokens=5, output_tokens=5)
            first.reserve("unknown", "test", 10, 10)
            first.settle("unknown", uncertain_reason="api_APITimeoutError_http_unknown")
            prior = first.summary()
            new = {**old, "approval_reference": "User requests proposed evaluation route",
                   "cap_usd": 6, "scope_caps_usd": {"native": 4.2, "kaggle": .6},
                   "max_attempts": 3000, "allowed_purposes": ["pilot", "evaluation"],
                   "evaluation_tasks": ["firm:FinCode"]}
            with self.assertRaises(BudgetStop):
                BudgetLedger.amend_allowance(old, new, path)
            BudgetLedger.amend_allowance(old, new, path, authorize_evaluation=True)
            second = BudgetLedger(new, path, run_id="evaluation")
            self.assertEqual(second.summary()["attempts"], 2)
            self.assertEqual(second.summary()["exposure_usd"], prior["exposure_usd"])
            with self.assertRaises(BudgetStop):
                second.reserve("blocked", "test", 10, 10)
            bad = {**new, "approval_reference": "bad", "rates": {}}
            with self.assertRaises(BudgetStop):
                BudgetLedger.amend_allowance(new, bad, path, authorize_evaluation=True)


class CaseRecordingTests(unittest.TestCase):
    def test_completed_case_persists_and_cannot_be_paid_again_implicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            result = {"success": True, "is_correct": False, "index": 0,
                      "final_answer": "wrong", "target": "right"}
            native = Mock(return_value=(result, None))
            evaluate = recording_evaluator(native, directory, ["frozen_case"])
            self.assertEqual(evaluate((0, {"question": "test"}), None), (result, None))
            record = json.loads((Path(directory) / "0000.json").read_text())
            self.assertEqual(record["case_id"], "frozen_case")
            self.assertFalse(record["result"]["is_correct"])
            with self.assertRaises(DecisionFailure):
                evaluate((0, {"question": "test"}), None)
            self.assertEqual(native.call_count, 1)

    def test_failure_stops_queued_cases_before_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            native = Mock(side_effect=GatewayFailure("transport failed"))
            evaluate = recording_evaluator(native, directory, ["one", "two"])
            with self.assertRaises(GatewayFailure):
                evaluate((0, {}), None)
            with self.assertRaises(DecisionFailure):
                evaluate((1, {}), None)
            self.assertEqual(native.call_count, 1)
            self.assertFalse(list(Path(directory).glob("*.json")))

    def test_recording_failure_also_stops_queued_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            native = Mock(return_value=({"success": True, "is_correct": True}, None))
            evaluate = recording_evaluator(native, directory, ["one", "two"])
            with patch("src.benchmarks.reasoning_records.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    evaluate((0, {}), None)
            with self.assertRaises(DecisionFailure):
                evaluate((1, {}), None)
            self.assertEqual(native.call_count, 1)
