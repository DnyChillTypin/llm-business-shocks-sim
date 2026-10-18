"""Synthetic recovery evidence and native aggregation checks; no real API calls."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.benchmarks.common import ROOT
from src.benchmarks.consulting_recovery import END, FIELDS, recover_case
from src.benchmarks.worker import load_file


class ConsultingRecoveryTests(unittest.TestCase):
    def fixture(self, folder):
        case = {"case_id": "synthetic_case", "case_text": "Synthetic case text"}
        config = {"primary_model": "mock_candidate", "judge_model": "mock_judge", "max_output_tokens": 4096, "consulting_turns": 12}
        events = []
        contents = [END + " Thank you", json.dumps({k: 8 for k in FIELDS})]
        for index, content in enumerate(contents):
            key = str(index)
            path = folder / "attempts" / key
            path.mkdir(parents=True)
            prompt = "Synthetic opening" if index == 0 else "=== CASE TEXT ===\nSynthetic case text\n\n=== DIALOGUE TRANSCRIPT ===\nINTERVIEWER: Thank you\n\n"
            request = {"model": "mock_judge", "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}]}
            digest = hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            usage = {"prompt_tokens": 4, "completion_tokens": 2}
            response = {"id": "synthetic_" + key, "usage": usage, "choices": [{"message": {"content": content}}]}
            (path / "request.json").write_text(json.dumps(request))
            (path / "response.json").write_text(json.dumps(response))
            events += [{"event": "started", "attempt_id": key, "context": {"case_id": case["case_id"], "validation_kind": "judge" if index else None}, "request_sha256": digest},
                       {"event": "finished", "attempt_id": key, "status": "completed", "cost_usd": .0001,
                        "request_sha256": digest, "response_id": response["id"], "usage": usage},
                       {"event": "parse_checked", "attempt_id": key, "parse_status": "valid"}]
        return case, config, events

    def test_completed_observed_session_reconstructs_native_history_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            case, config, events = self.fixture(folder)
            result = recover_case(folder, case, events, config)
            self.assertEqual(result["history"], [{"role": "interviewer", "content": "Thank you"}])
            self.assertEqual(result["judge_scores"]["overall"], 8)
            self.assertTrue(result["judge_scores"]["ended_by_interviewer"])
            self.assertEqual(result["judge_scores"]["turns_used"], 1)
            self.assertIsNone(recover_case(folder, case, events[:3], config))

    def test_incomplete_or_mismatched_judged_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            case, config, events = self.fixture(folder)
            events[4]["cost_usd"] = None
            with self.assertRaises(ValueError):
                recover_case(folder, case, events, config)
            events[4]["cost_usd"] = .0001
            path = folder / "attempts/0/request.json"
            request = json.loads(path.read_text())
            request["messages"][0]["content"] = "Changed request"
            path.write_text(json.dumps(request))
            with self.assertRaises(ValueError):
                recover_case(folder, case, events, config)

    def test_native_aggregation_of_independent_saved_sessions_is_unchanged(self):
        module = load_file("synthetic_native_consulting_aggregation", ROOT / "vendor/FirmBench/utils/consulting_tools.py")
        values = [7, 8, 9]
        outputs = [([{"role": "interviewer", "content": "synthetic"}], {k: value for k in FIELDS}) for value in values]
        cases = [{"case_id": "synthetic_" + str(i)} for i in range(3)]
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "_build_openai_client", return_value=object()), patch.object(module, "_run_single_interview", side_effect=outputs):
            result, errors = module.evaluate_consulting_set(agent=object(), test_samples=cases, config={"consulting_max_turns": 12}, log_dir=directory)
        self.assertEqual(result["num_finished"], 3)
        self.assertEqual(result["metrics"], {k: 8.0 for k in FIELDS})
        self.assertFalse(errors["failed_cases"])
