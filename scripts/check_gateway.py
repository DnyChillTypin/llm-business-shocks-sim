"""Validate configured model access. --smoke makes four small paid calls."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.benchmarks.common import credentials, install_gateway_clients, settings
from src.benchmarks.budget import load_budget
from src.benchmarks.errors import BudgetStop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--budget", type=Path, help="Required approved allowance for --smoke; listing model access remains free.")
    args = parser.parse_args()
    if args.smoke and not args.budget:
        parser.error("--smoke makes paid calls and requires --budget; native pilots usually make this redundant.")
    import openai
    key, base = credentials()
    config = settings()
    client = openai.OpenAI(api_key=key, base_url=base, max_retries=0, timeout=45)
    available = {m.id for m in client.models.list().data}
    required = list(dict.fromkeys([config["primary_model"], config["judge_model"], *config["icbe_models"]]))
    missing = [name for name in required if name not in available]
    print(f"Model list: {len(available)} available. Missing configured models: {missing}", flush=True)
    if missing:
        return 1
    if not args.smoke:
        return 0
    session = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "results/gateway_checks" / session
    output.mkdir(parents=True)
    test_config = {**config, "max_output_tokens": 256, "max_api_calls_per_task": 4}
    budget = load_budget(args.budget.resolve(), run_id=session, scope="native", base_url=base, purpose="pilot")
    if "gateway:compatibility" not in budget.manifest.get("allowed_tasks", []):
        raise BudgetStop("Compatibility smoke calls are not listed in this allowance.")
    counts = install_gateway_clients(output, test_config, budget=budget)
    checks = []
    for model in required:
        client = openai.OpenAI()
        response = client.chat.completions.create(model=model, messages=[{"role": "user", "content": 'Return exactly this JSON object: {"status":"ready"}'}],
                    response_format={"type": "json_object"}, max_completion_tokens=256, temperature=0)
        good = json.loads(response.choices[0].message.content or "{}").get("status") == "ready"
        checks.append({"requested_model": model, "returned_model": response.model, "json_response_pass": good})
        print(f"JSON response {model}: {good}", flush=True)
        if not good:
            raise RuntimeError("Configured model failed the JSON compatibility test.")
    from src.benchmarks.worker import load_retail
    runner = load_retail()
    _, content, _, usage = runner.stream_chat(client=openai.OpenAI(), model=config["primary_model"],
                         messages=[{"role": "user", "content": "Reply with exactly READY."}], max_retries=0)
    passed = content.strip() == "READY" and usage is not None
    checks.append({"native_retail_stream_pass": passed})
    (output / "gateway_readiness.json").write_text(json.dumps({"checks": checks, "usage": counts}, indent=2), encoding="utf-8")
    print(f"Native RetailBench stream: {passed}. Usage: {counts}")
    print(f"Report: {output / 'gateway_readiness.json'}")
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
