"""One native benchmark task per process to isolate vendor module namespaces."""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import random
import re
import sys
import types
from pathlib import Path

from .common import ROOT, TASKS, install_gateway_clients, settings, verify_sources


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def retail_config(kind, output):
    from util import default_config
    config = getattr(default_config, f"create_{kind}_config")()
    vendor = ROOT / "vendor/RetailBench"
    for name in ("data_dir", "customer_data_path", "init_sql_path", "review_model_path", "review_source_path", "news_source_path"):
        if config.get(name):
            relative = config[name]
            if name == "news_source_path" and relative.startswith("data/simulate_data/"):
                relative = relative.replace("data/", "data/dynamic/" if kind.startswith("dynamic") else "data/still/", 1)
            config[name] = str(vendor / relative)
    config["order_record_dir"] = str(output / "records")
    config["log_dir"] = str(output / "native_logs")
    config["debug"] = False
    return config


def load_retail():
    vendor = ROOT / "vendor/RetailBench"
    sys.path.insert(0, str(vendor))
    sys.modules["sku"] = importlib.import_module("module.sku")
    os.chdir(vendor)
    return load_file("native_retail_runner", vendor / "run_env.py")


def run_retail(kind, output, config):
    runner = load_retail()
    import openai
    runner.create_openai_client = lambda **kwargs: openai.OpenAI()
    runner.build_log_path = lambda: (output / "retail_trace.json", str(output / "native_logs"))
    for name in ("dynamic_middle", "dynamic_hard", "still_middle", "still_hard"):
        setattr(runner, f"create_{name}_config", lambda n=name: retail_config(n, output))
    sys.argv = ["run_env.py", "--config_type", kind, "--model", config["primary_model"],
                "--max_days", str(config["retail_days"]), "--max_strategy_turns", str(config["retail_strategy_turns"]),
                "--max_execution_turns", str(config["retail_execution_turns"]), "--checkpoint_dir", str(output / "checkpoints")]
    runner.main()


def load_firm(config):
    vendor = ROOT / "vendor/FirmBench"
    sys.path.insert(0, str(vendor))
    os.chdir(vendor)
    import utils.llm as llm
    original = llm.timed_llm_call

    def bounded(*args, **kwargs):
        kwargs.update(retries_on_timeout=2, sleep_seconds=1)
        return original(*args, **kwargs)
    llm.timed_llm_call = bounded
    import utils.consulting_tools as consulting
    consulting.OPENAI_BASE_URL = os.environ["OPENAI_URL"]
    consulting.CONSULTING_LLM_MODEL = config["judge_model"]
    from Agents.cot import ChainOfThoughtAgent
    if os.name == "nt":
        import StructuredReasoning.data_processor as processor
        from .formula_exec import exec_python_windows
        processor.exec_python = exec_python_windows
    import utils.seriousgame_tools as games
    from .edt_compat import run_episode
    async def edt_episode(**kwargs):
        kwargs["edt_cfg"] = {**kwargs["edt_cfg"], "seed": config["seed"]}
        return await run_episode(**kwargs)
    games._run_one_edt_episode_scenario_level = edt_episode

    async def call_tool(server, name, arguments):
        result = await server.call_tool(name, arguments)
        content = getattr(result, "content", None) or (result.get("content", []) if isinstance(result, dict) else [])
        text = "\n".join(c.get("text", "") if isinstance(c, dict) else getattr(c, "text", "") for c in content)
        is_error = result.get("isError", False) if isinstance(result, dict) else getattr(result, "isError", False)
        if is_error:
            raise RuntimeError(f"MCP {name}: {text[:2000]}")
        payload = games._safe_json_loads(text)
        if payload.get("error"):
            raise RuntimeError(f"MCP {name}: {payload}")
        return payload
    games._mcp_call = call_tool
    return ChainOfThoughtAgent


def structured_samples(task):
    from StructuredReasoning.data_processor import DataProcessor, load_data
    vendor = ROOT / "vendor/FirmBench"
    source = vendor / "StructuredReasoning/data/aoa_sampled_test/task_config_aoa_sampled_test_50.json"
    task_config = json.loads(source.read_text(encoding="utf-8"))[task]
    raw_path = vendor / task_config["test_data"]
    raw = load_data(str(raw_path))
    if task == "factset":
        # The repository ships this dataset but its DataProcessor rejects it.
        # Treat binary supplier selection as a documented local extension, using
        # the existing exact numeric-span scorer; never expose label provenance.
        processor = DataProcessor("SEC-NUM")
        processor.task_name = "factset"
        raw = [{"question": s["question"], "answer": s["answer"],
                "context": re.sub(r",?\s*source_label=[^\n]*", "", s.get("context", ""))} for s in raw]
    else:
        processor = DataProcessor(task)
    return processor, processor.process_task_data(raw), raw_path


def run_firm(task, output, config):
    Agent = load_firm(config)
    agent = Agent(api_provider="openai", generator_model=config["primary_model"],
                  max_tokens=config["max_output_tokens"], agent_method="cot")
    if task not in ("consulting", "beergame", "edt"):
        processor, samples, path = structured_samples(task)
        return agent.run("eval_only", samples, processor, {"task_name": task, "save_dir": str(output),
                         "test_workers": config["workers"], "json_mode": True, "source_file": str(path)})
    if task == "consulting":
        from Consulting.run import load_consulting_cases
        cases = load_consulting_cases("Consulting/agsm_cases_all.json")
        cases = random.Random(config["seed"]).sample(cases, min(config["consulting_cases"], len(cases)))
        return agent.run("eval_only", cases, None, {"task_name": "Consulting", "save_dir": str(output),
                         "consulting_max_turns": config["consulting_turns"], "consulting_judge": True})
    if task == "beergame":
        from SeriousGame.beergame_data_processor import BeerGameDataProcessor
        samples = BeerGameDataProcessor.process_task_data(BeerGameDataProcessor.load_scenarios(None))
        return agent.run("eval_only", samples, None, {"task_name": "SeriousGame/BeerGame", "save_dir": str(output),
                         "mcp": {"command": sys.executable, "args": [str(ROOT / "vendor/FirmBench/SeriousGame/beergame_mcp_server.py")],
                                 "timeout_sec": 90, "max_retry_attempts": 2},
                         "toolmap": beer_toolmap()})
    # The native EDT runner supplies its scenario generation and BPTK/MCP config.
    import SeriousGame.run_edt as runner
    sys.argv = ["run_edt", "--mode", "eval_only", "--agent_method", "cot", "--api_provider", "openai",
                "--generator_model", config["primary_model"], "--max_tokens", str(config["max_output_tokens"]),
                "--save_dir", str(output), "--bptk_repo_root", str(ROOT / "vendor/FirmBench/SeriousGame")]
    return runner.main()


def beer_toolmap():
    return {"new_episode": "init-beer-env", "step": "step-beer-env", "metrics": "get-beer-metrics", "close": "close-beer-env"}


def load_icbe():
    path = ROOT / "vendor/icbe-2026-strategic-behavior/LLMs_Business_Simulation.py"
    source = path.read_text(encoding="utf-8-sig")
    # Preserve native payoffs, phases, prompts, ordered pairs and Excel exporter.
    # API/parse failures must be failures, not fabricated cooperation decisions.
    source = source.replace('return "COOPERATE" # Fallback', 'raise ValueError("Unparseable ICBE decision")')
    source = source.replace('else:\n                return "COOPERATE"', 'else:\n                raise')
    source = source.replace('    return "COOPERATE"\n\n# ================= MAIN LOOP', '    raise RuntimeError("ICBE retries exhausted")\n\n# ================= MAIN LOOP')
    source = source.replace("await asyncio.sleep(0.1)", "await asyncio.sleep(ROUND_DELAY_SECONDS)")
    module = types.ModuleType("native_icbe")
    module.__file__ = str(path)
    module.ROUND_DELAY_SECONDS = 0.1
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=TASKS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify_sources()
    config = settings()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config["_runtime_output"] = str(output)
    (output / "run_config.json").write_text(json.dumps({"task": args.task, **config}, indent=2), encoding="utf-8")
    counts = install_gateway_clients(output, config)
    try:
        if args.task.startswith("retail:"):
            run_retail(args.task.split(":", 1)[1], output, config)
        elif args.task.startswith("firm:"):
            run_firm(args.task.split(":", 1)[1], output, config)
        else:
            module = load_icbe()
            module.MODELS = config["icbe_models"]
            module.NUM_ROUNDS = config["icbe_rounds"]
            os.chdir(output)
            asyncio.run(module.main())
    finally:
        (output / "usage_totals.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
