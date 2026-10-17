"""Exercise native CoT/scoring plus new telemetry using a SCRIPTED mock response.

Requires installed benchmark dependencies and pinned FirmBench. Output is strictly
verification evidence, never a measured LLM benchmark or model-cost observation.
No real credentials are loaded by the gateway and all completion HTTP is mocked.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import openai

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from budget_fixture import ledger
from src.benchmarks.common import install_gateway_clients
from src.benchmarks.planning import run_plan
from src.benchmarks.worker import run_firm


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    session = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "results/verification/stage2/offline_native_pilot" / session
    output.mkdir(parents=True)
    plan = run_plan("firm:CodeFinQA", config_path=ROOT / "configs/pilots/native.json")
    config = {**plan["settings"], "_purpose": "scripted_fixture", "_case_limit": 1,
              "_task": plan["task"], "_selected_case_ids": plan["selected_case_ids"],
              "_runtime_output": str(output), "_run_id": session, "_request_context": {"task_id": plan["task"]}}
    source = ROOT / "vendor/FirmBench/StructuredReasoning/data/aoa_sampled_test/sampled_jsonl/CodeFinQA__sample_50_seed42.jsonl"
    reference = json.loads(source.read_text(encoding="utf-8").splitlines()[0])["answer"]

    def handler(request):
        if request.url.host != "gateway.example":
            raise RuntimeError("Offline fixture refused an unexpected completion host.")
        return httpx.Response(200, json={"id": "scripted-fixture", "object": "chat.completion", "created": 0,
            "model": "SCRIPTED_NOT_A_MODEL", "choices": [{"index": 0, "message": {"role": "assistant",
            "content": json.dumps({"reasoning": "Scripted reference fixture, not model reasoning.", "final_answer": reference})},
            "finish_reason": "stop"}], "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}})

    original = openai.OpenAI
    class MockClient(original):
        def __init__(self, *args, **kwargs):
            kwargs["http_client"] = httpx.Client(transport=httpx.MockTransport(handler))
            super().__init__(*args, **kwargs)

    allowance = ledger(output, run_id=session)
    with patch.object(openai, "OpenAI", MockClient), patch("src.benchmarks.common.credentials",
                       return_value=("private-test-key", "https://gateway.example/v1")):
        counts = install_gateway_clients(output, config, budget=allowance)
        result = run_firm("CodeFinQA", output, config)
    if result.get("total") != 1 or result.get("correct") != 1 or counts["completed"] != 1:
        raise RuntimeError("Scripted native scoring/telemetry fixture failed.")
    events = [json.loads(line) for line in (output / "api_attempts.jsonl").read_text().splitlines()]
    if events[-1].get("parse_status") != "valid" or events[0]["context"]["case_id"] != "CodeFinQA:row_0000":
        raise RuntimeError("Native fixture did not preserve parsing/case identity.")
    record = {"status": "passed", "purpose": "scripted_fixture_not_research", "paid_api_calls": 0,
              "scripted_completions": 1, "native_scored_cases": 1,
              "model_identity": "SCRIPTED_NOT_A_MODEL", "tokens_and_cost_are_synthetic": True}
    (output / "verification_result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**record, "evidence_directory": str(output)}, indent=2))


if __name__ == "__main__":
    main()
