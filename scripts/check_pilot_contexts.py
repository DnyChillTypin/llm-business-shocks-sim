"""Unpaid late-phase prompt construction and synthetic Retail context sizing.

Scripted choices verify native prompt/payoff paths, never model performance.
Retail stress payloads are synthetic sizing scenarios, not late-day observations.
"""
import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from src.benchmarks.worker import load_icbe
    captured = []
    async def scripted(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="DECISION: OPTION A"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=scripted)))
    with patch("openai.AsyncOpenAI", return_value=client):
        module = load_icbe()
    module.client = client
    expected = {1: [(3, 3), (0, 5), (5, 0), (1, 1)], 26: [(1, 1), (0, 4), (4, 0), (3, 3)],
                51: [(4, 4), (-3, 5), (5, -3), (2, 2)], 76: [(1, 1), (-1, 3), (3, -1), (-2, -2)]}
    phases = []
    async def exercise():
        for number, payoffs in expected.items():
            actual = [module.analyze_round(a, b, number)[:2] for a in ("COOPERATE", "EXPLOIT") for b in ("COOPERATE", "EXPLOIT")]
            assert actual == payoffs
            result = await module.get_decision("gpt-4.1-mini-2025-04-14", number, ["COOPERATE", "EXPLOIT"] * 50)
            assert result == "COOPERATE"
            payload = json.dumps(captured[-1], ensure_ascii=False, sort_keys=True).encode("utf-8")
            phases.append({"round": number, "phase": module.get_current_phase(number)["rules"],
                "request_bytes": len(payload), "request_sha256": hashlib.sha256(payload).hexdigest(),
                "max_output_tokens": captured[-1]["max_tokens"], "verified_payoff_pairs": len(actual)})
    asyncio.run(exercise())
    retail = []
    for task in (ROOT / "results/benchmarks").glob("retail_*"):
        requests = sorted(task.glob("*/attempts/*/request.json"))
        if not requests:
            continue
        # Use the largest saved request as the starting point; append clearly
        # synthetic records to test the local byte envelope without any model.
        path = max(requests, key=lambda p: p.stat().st_size)
        request = json.loads(path.read_text(encoding="utf-8"))
        base_bytes = len(json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        scenarios = []
        for extra in (0, 10000, 50000, 200000):
            payload = {**request, "messages": [*request["messages"], {"role": "user", "content": "SYNTHETIC CONTEXT STRESS RECORD. " + "x" * extra}]}
            envelope = len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")) + 4096
            scenarios.append({"additional_synthetic_bytes": extra, "input_token_envelope": envelope,
                              "fits_current_262144_envelope": envelope <= 262144})
        retail.append({"task": task.name, "source_request": str(path.relative_to(ROOT)), "base_request_bytes": base_bytes,
                       "synthetic_sizing_scenarios": scenarios})
    report = {"status": "passed", "paid_api_calls": 0, "scripted_icbe_decisions": 4,
        "icbe_phases": phases, "retail_context_stress": retail,
        "qualification": "No late-phase model behavior or late-day Retail cost measured. Native daily conversation resets and token trimming do not prove constant context size. Stress bytes are hypothetical, not simulated business outcomes."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
