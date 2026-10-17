"""Synthetic artifact fixtures, never research results."""
import json
import tempfile
import unittest
from pathlib import Path

from src.benchmarks.validation import validate_run


class RunValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.write("run_manifest.json", {"task": "firm:CodeFinQA", "purpose": "scripted_fixture",
            "status": "execution_finished_requires_artifact_review", "expected_units": 1,
            "selected_case_ids": ["case0"], "started_at_utc": "2026-01-01T00:00:00+00:00",
            "finished_at_utc": "2026-01-01T00:00:02+00:00"})
        self.write("exit_status.json", {"exit_code": 0})
        self.write("usage_totals.json", {"attempts": 1, "input_tokens": 4, "output_tokens": 3})
        self.write("budget_summary.json", {"pending_attempts": 0, "uncertain_attempts": 0})
        self.result = {"total": 1, "no_answer": 0, "correct": 0, "accuracy": 0}
        self.write("native_result.json", self.result)
        self.write("native/test_results.json", {"test_results": self.result})
        self.write("runtime_identity.json", {"model": "SCRIPTED_NOT_A_MODEL"})
        self.write("attempts/a/request.json", {})
        self.write("attempts/a/response.json", {})
        self.events = [{"event": "started", "attempt_id": "a", "context": {"case_id": "case0"}, "requested_model": "SCRIPTED"},
            {"event": "finished", "attempt_id": "a", "status": "completed", "usage": {"prompt_tokens": 4, "completion_tokens": 3},
             "cost_usd": .00001, "latency_seconds": 1, "returned_model": "SCRIPTED"},
            {"event": "parse_checked", "attempt_id": "a", "parse_status": "valid"}]
        self.events_write()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, value):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def events_write(self):
        (self.folder / "api_attempts.jsonl").write_text("\n".join(map(json.dumps, self.events)), encoding="utf-8")

    def test_wrong_but_valid_answer_is_complete_and_score_tampering_is_detected(self):
        self.assertEqual(validate_run(self.folder)["status"], "validated_complete")
        self.write("native_result.json", {**self.result, "correct": 1, "accuracy": 1})
        report = validate_run(self.folder)
        self.assertEqual(report["status"], "requires_review")
        self.assertFalse(report["checks"]["native_score_artifact"])

    def test_failure_with_missing_usage_and_native_output_is_never_zero_cost_success(self):
        self.events[1].update(status="failed", usage=None, cost_usd=None)
        self.events.pop()
        self.events_write()
        (self.folder / "native_result.json").unlink()
        self.write("usage_totals.json", {"attempts": 1, "input_tokens": 0, "output_tokens": 0})
        self.write("budget_summary.json", {"pending_attempts": 0, "uncertain_attempts": 1})
        report = validate_run(self.folder)
        self.assertEqual(report["status"], "requires_review")
        self.assertEqual(report["missing_usage_attempts"], 1)
        self.assertFalse(report["checks"]["budget_exposure_accounted"])

    def test_consulting_requires_one_real_judge_response_for_every_frozen_case(self):
        path = self.folder / "run_manifest.json"
        manifest = json.loads(path.read_text())
        manifest.update(task="firm:consulting", expected_units=2, selected_case_ids=["case0", "case1"])
        self.write("run_manifest.json", manifest)
        result = {"num_cases": 2, "num_finished": 2, "num_failed": 0, "metrics": {"overall": 8}}
        self.write("native_result.json", result)
        self.write("native/test_results.json", {"test_results": result})
        self.events[0]["context"]["validation_kind"] = "judge"
        self.events_write()
        report = validate_run(self.folder)
        self.assertTrue(report["checks"]["native_coverage"])
        self.assertTrue(report["checks"]["judge_observed"])
        self.assertFalse(report["checks"]["every_frozen_case_judged_once"])
        self.assertEqual(report["status"], "requires_review")
