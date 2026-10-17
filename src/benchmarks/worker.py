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
import inspect
import math
from datetime import datetime, timezone
from pathlib import Path

from .common import ROOT, TASKS, install_gateway_clients, settings, verify_sources
from .common import credentials
from .budget import load_budget
from .errors import BudgetStop, CallLimitReached, DecisionFailure, GatewayFailure
from .gateway import request_context, CONTEXT
from .planning import run_plan


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


def load_retail(*, reject_forced=False):
    vendor = ROOT / "vendor/RetailBench"
    sys.path.insert(0, str(vendor))
    sys.modules["sku"] = importlib.import_module("module.sku")
    os.chdir(vendor)
    if not reject_forced:
        return load_file("native_retail_runner", vendor / "run_env.py")
    path = vendor / "run_env.py"
    source = path.read_text(encoding="utf-8")
    forced = 'env.exec_tools("end_today")'
    if source.count(forced) != 2:
        raise RuntimeError("Retail forced-transition source changed; inspect the failure adapter.")
    source = source.replace(forced, "reject_forced_transition()")
    module = types.ModuleType("native_retail_runner")
    module.__file__ = str(path)
    def reject():
        raise DecisionFailure("Native Retail exhausted tool/turn limits; no forced end_today substituted.")
    module.reject_forced_transition = reject
    sys.modules[module.__name__] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def run_retail(kind, output, config):
    runner = load_retail(reject_forced=True)
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
        call = inspect.signature(original).bind_partial(*args, **kwargs).arguments
        call_id = str(call.get("call_id", "unknown"))
        case_id = CONTEXT.get().get("case_id", call_id)
        match = re.fullmatch(r"test_eval_(\d+)", call_id)
        if match and config.get("_selected_case_ids"):
            case_id = config["_selected_case_ids"][int(match.group(1))]
        kind = ("beer" if "beergame" in call_id else "candidate" if "consulting" in call_id else
                "reasoning" if config.get("_task", "").startswith("firm:") and
                config["_task"] not in {"firm:edt", "firm:consulting", "firm:beergame"} else None)
        with request_context(logical_request_id=call_id, case_id=case_id, native_call_id=call_id,
                             role=call.get("role"), validation_kind=kind):
            return original(*args, **kwargs)
    llm.timed_llm_call = bounded
    import utils.consulting_tools as consulting
    consulting.OPENAI_BASE_URL = os.environ["OPENAI_URL"]
    consulting.CONSULTING_LLM_MODEL = config["judge_model"]
    from Agents.cot import ChainOfThoughtAgent
    if config.get("_purpose") in {"pilot", "evaluation"}:
        original_interview = consulting._run_single_interview
        def interview(**kwargs):
            with request_context(case_id=kwargs["case"]["case_id"]):
                return original_interview(**kwargs)
        consulting._run_single_interview = interview
        original_judge = consulting._chat_json
        def judge(*args, **kwargs):
            with request_context(role="interviewer_judge", validation_kind="judge"):
                return original_judge(*args, **kwargs)
        consulting._chat_json = judge
        original_edt = ChainOfThoughtAgent._decide_edt_scenario_schema
        async def decide_edt(self, *args, **kwargs):
            with request_context(case_id="interactive", validation_kind="edt", role="scenario_candidate"):
                return await original_edt(self, *args, **kwargs)
        ChainOfThoughtAgent._decide_edt_scenario_schema = decide_edt
        agent_module = sys.modules[ChainOfThoughtAgent.__module__]
        normalize = agent_module.normalize_edt_schema
        def audited_schema(raw, ctx):
            projects, horizon, cmax = len(ctx["projects"]), ctx["horizon_steps"], ctx["C_max"]
            valid = (isinstance(raw, dict) and type(raw.get("C")) is int and 0 <= raw["C"] <= cmax
                     and type(raw.get("R")) in (int, float) and math.isfinite(raw["R"]) and 0 <= raw["R"] <= 1
                     and isinstance(raw.get("P"), list) and len(raw["P"]) == projects)
            if valid:
                valid = all(type(p) is int and p == 0 or isinstance(p, list) and len(p) == 3 and
                            all(type(v) is int for v in p) and p[0] == 1 and 0 <= p[1] <= p[2] <= horizon
                            for p in raw["P"])
            if not valid:
                path = Path(config["_runtime_output"]) / "decision_events.jsonl"
                with path.open("a", encoding="utf-8") as log:
                    log.write(json.dumps({"event": "invalid_edt_schema", "status": "failed", "fallback_used": False}) + "\n")
                raise DecisionFailure("EDT schema has invalid/missing fields; no native default substituted.")
            result = normalize(raw, ctx)
            path = Path(config["_runtime_output"]) / "decision_events.jsonl"
            with path.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"event": "native_edt_normalization", "raw_schema": raw,
                                      "normalized_schema": result, "projection_applied": result != raw}) + "\n")
            return result
        agent_module.normalize_edt_schema = audited_schema
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
        if config.get("_case_limit"):
            samples = samples[:config["_case_limit"]]
        if config.get("_purpose") == "evaluation":
            import utils.tools as native_tools
            from .reasoning_records import recording_evaluator
            native_tools.evaluate_single_test_sample = recording_evaluator(
                native_tools.evaluate_single_test_sample, output / "case_records", config["_selected_case_ids"])
        return agent.run("eval_only", samples, processor, {"task_name": task, "save_dir": str(output),
                         "test_workers": config["workers"], "json_mode": True, "source_file": str(path)})
    if task == "consulting":
        from Consulting.run import load_consulting_cases
        cases = load_consulting_cases("Consulting/agsm_cases_all.json")
        cases = random.Random(config["seed"]).sample(cases, min(config["consulting_cases"], len(cases)))
        if config.get("_case_limit"):
            cases = cases[:config["_case_limit"]]
        return agent.run("eval_only", cases, None, {"task_name": "Consulting", "save_dir": str(output),
                         "consulting_max_turns": config["consulting_turns"], "consulting_judge": True})
    if task == "beergame":
        from SeriousGame.beergame_data_processor import BeerGameDataProcessor
        samples = BeerGameDataProcessor.process_task_data(BeerGameDataProcessor.load_scenarios(None))
        if config.get("_case_limit"):
            samples = samples[:config["_case_limit"]]
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
    if source.count("max_tokens=150") != 1:
        raise RuntimeError("ICBE native output-limit adapter no longer matches the pinned source.")
    source = source.replace("max_tokens=150", "max_tokens=ICBE_OUTPUT_TOKENS")
    # Preserve native payoffs, phases, prompts, ordered pairs and Excel exporter.
    # API/parse failures must be failures, not fabricated cooperation decisions.
    source = source.replace('return "COOPERATE" # Fallback', 'raise ValueError("Unparseable ICBE decision")')
    source = source.replace('else:\n                return "COOPERATE"', 'else:\n                raise')
    source = source.replace('    return "COOPERATE"\n\n# ================= MAIN LOOP', '    raise RuntimeError("ICBE retries exhausted")\n\n# ================= MAIN LOOP')
    source = source.replace("await asyncio.sleep(0.1)", "await asyncio.sleep(ROUND_DELAY_SECONDS)")
    source = source.replace("task_a = get_decision(model_a, r, hist_b)",
                            "task_a = scoped_decision(model_a, r, hist_b, match_counter, 'A')")
    source = source.replace("task_b = get_decision(model_b, r, hist_a)",
                            "task_b = scoped_decision(model_b, r, hist_a, match_counter, 'B')")
    module = types.ModuleType("native_icbe")
    module.__file__ = str(path)
    module.ROUND_DELAY_SECONDS = 0.1
    module.ICBE_OUTPUT_TOKENS = 4096
    exec(compile(source, str(path), "exec"), module.__dict__)
    async def scoped_decision(model, round_number, history, match, actor):
        with request_context(case_id=f"ordered_pair_{match-1:02d}", round=round_number, actor=actor,
                             logical_request_id=f"pair{match}:round{round_number}:{actor}", validation_kind="icbe"):
            return await module.get_decision(model, round_number, history)
    module.scoped_decision = scoped_decision
    return module


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=TASKS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--budget", type=Path, required=True)
    args = parser.parse_args()
    from src.research.design import validate_design
    validate_design(ROOT)
    plan = json.loads(args.plan.read_text(encoding="utf-8")) if args.plan else run_plan(args.task)
    base = settings()
    expected = run_plan(args.task, config_path={"purpose": plan["purpose"], "case_limit": plan["case_limit"],
                      "settings": {k: v for k, v in plan["settings"].items() if base.get(k) != v}})
    if plan != expected:
        raise ValueError("Launch plan differs from the validated bounded/frozen selection.")
    config = plan["settings"]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config["_runtime_output"] = str(output)
    config.update(_purpose=plan["purpose"], _case_limit=plan["case_limit"], _task=args.task,
                  _run_id=output.name, _selected_case_ids=plan["selected_case_ids"],
                  _request_context={"task_id": args.task})
    (output / "run_config.json").write_text(json.dumps({"task": args.task, **config}, indent=2), encoding="utf-8")
    _, base_url = credentials()
    budget = load_budget(args.budget.resolve(), run_id=output.name, scope="native", base_url=base_url, purpose=plan["purpose"])
    if args.task not in budget.manifest.get("allowed_tasks", []):
        raise BudgetStop("This task is not listed in the approved allowance.")
    if plan["purpose"] == "evaluation" and args.task not in budget.manifest.get("evaluation_tasks", []):
        raise BudgetStop("This task is not listed in the approved evaluation scope.")
    counts = install_gateway_clients(output, config, budget=budget)
    import subprocess
    from src.research.design import canonical_hash, text_hash
    identity = {"project_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "project_tracked_dirty": bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True).strip()),
                "source_pins": json.loads((ROOT / "configs/sources.json").read_text(encoding="utf-8")),
                "study_manifest_sha256": text_hash(ROOT / "docs/results/study_design_manifest.json"),
                "run_config_sha256": canonical_hash(config), "allowance_sha256": budget.fingerprint,
                "provider": "ShopAIKey", "base_url": base_url}
    (output / "runtime_identity.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
    manifest = {"task": args.task, "purpose": plan["purpose"], "status": "running",
                "expected_units": plan["expected_units"], "configured_horizon": plan["configured_horizon"],
                "selected_case_ids": plan["selected_case_ids"], "pilot_qualification": plan["pilot_qualification"],
                "started_at_utc": datetime.now(timezone.utc).isoformat(), "budget_id": budget.manifest["budget_id"]}
    (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    result = None
    try:
        if args.task.startswith("retail:"):
            run_retail(args.task.split(":", 1)[1], output, config)
        elif args.task.startswith("firm:"):
            result = run_firm(args.task.split(":", 1)[1], output, config)
        else:
            module = load_icbe()
            module.MODELS = config["icbe_models"]
            module.NUM_ROUNDS = config["icbe_rounds"]
            module.ICBE_OUTPUT_TOKENS = config["max_output_tokens"]
            os.chdir(output)
            asyncio.run(module.main())
        (output / "native_result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        budget_state = budget.summary()
        if budget_state["pending_attempts"] or budget_state["blocking_uncertain_attempts"]:
            raise BudgetStop("Run has unresolved attempts; it cannot be marked complete.")
        if isinstance(result, dict) and "total" in result and result["total"] != plan["expected_units"]:
            raise RuntimeError("Native scorer did not account for every selected case.")
        manifest["status"] = "execution_finished_requires_artifact_review"
    except BaseException as exc:
        manifest.update(status="incomplete" if isinstance(exc, CallLimitReached) else "failed",
                        failure_category=type(exc).__name__)
        raise
    finally:
        (output / "usage_totals.json").write_text(json.dumps(counts, indent=2), encoding="utf-8")
        (output / "budget_summary.json").write_text(json.dumps(budget.summary(), indent=2), encoding="utf-8")
        manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
