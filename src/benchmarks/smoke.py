"""Native local checks. Deterministic stand-ins exercise orchestration, not LLM quality."""
import argparse
import asyncio
import contextlib
import importlib
import io
import json
import os
import sys
from pathlib import Path

from .common import ROOT, TASKS, install_gateway_clients, settings
from .worker import beer_toolmap, load_firm, load_icbe, load_retail, retail_config, structured_samples


def check_retail(kind, output):
    runner = load_retail()
    config = retail_config(kind, output)
    for name in ("data_dir", "customer_data_path", "init_sql_path", "review_model_path", "review_source_path"):
        assert Path(config[name]).exists(), f"Missing {name}: {config[name]}"
    if config.get("enable_new"):
        assert Path(config["news_source_path"]).exists()
    env = runner.RetailEnvironment(config)
    tools = env.get_tools()
    assert tools
    result = env.step()
    return {"config": kind, "tool_count": len(tools), "one_native_day": True, "step_result_type": type(result).__name__}


def check_structured(task, output, config):
    load_firm(config)
    processor, samples, path = structured_samples(task)
    expected = 7 if task == "FinCode" else 50
    assert len(samples) == expected
    assert all(s.get("question") and s.get("target") is not None for s in samples)
    if task == "factset":
        assert not any("source_label=" in s["context"] for s in samples)
        assert processor.answer_is_correct("[[1]]", "1")
        assert not processor.answer_is_correct("[[0]]", "1")
    elif task in ("FinCode", "CodeFinQA", "CodeTAT-QA", "SEC-NUM", "TAT-QA", "ConvFinQA", "formula"):
        assert processor.answer_is_correct("[[42]]", "42")
        assert not processor.answer_is_correct("[[0]]", "42")
    elif task == "FinKnow":
        assert processor.answer_is_correct("[[A]]", {"label": "A", "options": ["yes", "no"]})
        assert not processor.answer_is_correct("[[B]]", {"label": "A", "options": ["yes", "no"]})
    elif task == "FormulaEval":
        assert processor.answer_is_correct("return 2", {"prompt": "def answer():\n", "completion": "    return 2"})
        target = samples[0]["target"]
        assert processor.answer_is_correct(target["completion"], target), "Native FormulaEval could not score a reference completion"
    return {"samples": len(samples), "native_processor": type(processor).__name__, "source": str(path.relative_to(ROOT)),
            "extension": task == "factset"}


def check_consulting(output, config):
    load_firm(config)
    from Consulting.run import load_consulting_cases
    import utils.consulting_tools as tools
    import random
    cases = load_consulting_cases("Consulting/agsm_cases_all.json")
    selected = random.Random(config["seed"]).sample(cases, config["consulting_cases"])
    tools._chat_text = lambda *a, **kw: "What costs and revenues should we examine?"
    tools._chat_json = lambda *a, **kw: {"overall_score": 3}

    class Agent:
        def reply(self, case_id, history):
            return "Compare revenue, variable costs and fixed costs."
    result = tools._run_single_interview(agent=Agent(), client=None, case=selected[0], max_turns=4)
    assert result
    return {"available_cases": len(cases), "selected_cases": len(selected), "scripted_interview_and_judge": True}


def check_beer(output, config):
    load_firm(config)
    from SeriousGame.beergame_data_processor import BeerGameDataProcessor
    from utils.seriousgame_tools import evaluate_beergame_set
    samples = BeerGameDataProcessor.process_task_data(BeerGameDataProcessor.load_scenarios(None))
    results, errors = evaluate_beergame_set(test_samples=samples, policy_fn=lambda obs, meta: 400,
        config={"mcp": {"command": sys.executable, "args": [str(ROOT / "vendor/FirmBench/SeriousGame/beergame_mcp_server.py")],
                        "timeout_sec": 90}, "toolmap": beer_toolmap()}, log_dir=str(output))
    assert results
    return {"episodes": len(samples), "weeks_each": 25, "mcp_full_horizon": True, "metrics": results}


def check_edt(output, config):
    load_firm(config)
    from SeriousGame.edt_data_processor import EDTDataProcessor
    from utils.seriousgame_tools import evaluate_edt_set, build_edt_decision_context, normalize_edt_schema

    class Agent:
        def _decide_edt_scenario_schema(self, *, base_summary, scenario_meta):
            context = build_edt_decision_context(base_summary=base_summary, scenario_meta=scenario_meta)
            return normalize_edt_schema({}, context)
    native = ROOT / "vendor/FirmBench/SeriousGame"
    cfg = {"max_steps": 96, "mcp": {"command": sys.executable, "args": [str(native / "edt_mcp_server_local.py")]},
           "bptk": {"template_repo_root": str(native), "script": str(native / "run_bptk_server.py"), "host": "127.0.0.1", "start_timeout_sec": 90}}
    stats, detail = evaluate_edt_set(agent=Agent(), test_samples=EDTDataProcessor.load_scenarios(), edt_cfg=cfg, log_dir=str(output))
    assert not detail["errors"], detail["errors"]
    assert len(detail["episodes"]) == 1
    assert detail["episodes"][0]["steps"] == 96
    return {"episodes": 1, "native_horizon": 96, "native_bptk_abm_rollout": True, "metric_names": list(stats)}


def check_icbe(output, config):
    module = load_icbe()
    module.MODELS = config["icbe_models"]
    module.NUM_ROUNDS = 100
    module.ROUND_DELAY_SECONDS = 0

    async def decision(model, current_round, history):
        return "COOPERATE" if current_round % 2 else "EXPLOIT"
    module.get_decision = decision
    os.chdir(output)
    with contextlib.redirect_stdout(io.StringIO()):
        asyncio.run(module.main())
    import pandas as pd
    artifact = output / "Business_Sim_Dynamic_Market_100Rounds.xlsx"
    logs = pd.read_excel(artifact, sheet_name="Detailed Logs")
    assert len(logs) == 600 and logs["Match ID"].nunique() == 6 and logs["Market Phase"].nunique() == 4
    # All sixteen phase/action combinations use the native payoff table.
    for round_number in (1, 26, 51, 76):
        for a in ("COOPERATE", "EXPLOIT"):
            for b in ("COOPERATE", "EXPLOIT"):
                pa, pb, _ = module.analyze_round(a, b, round_number)
                assert isinstance(pa, int) and isinstance(pb, int)
    return {"ordered_matches": 6, "rounds_per_match": 100, "market_phases": 4, "excel_export": True, "scripted_decisions": True}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=[*TASKS, "dependencies"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = settings()
    config["_runtime_output"] = str(output)
    counts = install_gateway_clients(output, config, offline=True)
    if args.task == "dependencies":
        modules = ("sentence_transformers", "faiss", "openpyxl", "tabulate", "bs4", "BPTK_Py", "mcp.server.fastmcp", "agents.mcp")
        for name in modules:
            importlib.import_module(name)
        result = {"imports": list(modules)}
    elif args.task.startswith("retail:"):
        result = check_retail(args.task.split(":", 1)[1], output)
    elif args.task == "firm:consulting":
        result = check_consulting(output, config)
    elif args.task == "firm:beergame":
        result = check_beer(output, config)
    elif args.task == "firm:edt":
        result = check_edt(output, config)
    elif args.task.startswith("firm:"):
        result = check_structured(args.task.split(":", 1)[1], output, config)
    else:
        result = check_icbe(output, config)
    assert counts["attempts"] == 0
    result["paid_api_calls"] = 0
    (output / "check_result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("PASS", args.task)


if __name__ == "__main__":
    main()
