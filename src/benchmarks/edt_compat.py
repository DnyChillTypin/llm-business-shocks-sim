"""Run FirmBench's native EDT ABM through BPTK's supported full-episode API.

The upstream runner makes one scenario decision, then no interventions. BPTK's
session/step API only handles SD models, so use run_scenarios for the same ABM.
Native schema normalization, scenario edits, agent model and SD equations remain.
"""
import inspect
import json
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path


async def run_episode(*, agent, sample, edt_cfg, log_dir, verbose):
    from SeriousGame.edt_scenario_generator import (
        load_scenario_document, extract_sm_document, extract_scenario,
        summarize_base_scenario, normalize_schema, apply_schema_to_scenario,
    )
    root = Path(__file__).resolve().parents[2]
    template = Path(edt_cfg["bptk"]["template_repo_root"])
    episode = Path(log_dir) / "edt_native_rollout"
    episode.mkdir(parents=True, exist_ok=True)
    (episode / "scenarios").mkdir(exist_ok=True)
    doc = load_scenario_document(str(template), "interactive.json")
    sm_doc = extract_sm_document(doc, "smEDT")
    original = extract_scenario(sm_doc, "interactive")
    summary = summarize_base_scenario(original)
    decision = agent._decide_edt_scenario_schema(base_summary=summary, scenario_meta={"scenario_id": sample["scenario_id"], "max_steps": 96})
    raw = await decision if inspect.isawaitable(decision) else decision
    schema = normalize_schema(raw, summary)
    generated = apply_schema_to_scenario(original, schema, summary)
    scenario_doc = {"smEDT": {**{k: v for k, v in sm_doc.items() if k != "scenarios"}, "scenarios": {"interactive": generated}}}
    (episode / "scenarios/interactive.json").write_text(json.dumps(scenario_doc, indent=2), encoding="utf-8")
    shutil.copytree(template / "simulation_models", episode / "simulation_models", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    with (episode / "rollout.log").open("w", encoding="utf-8") as log:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--root", str(episode),
                                 "--seed", str(edt_cfg.get("seed", 42))], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=120)
    if result.returncode:
        raise RuntimeError(f"Native EDT rollout failed. See {episode / 'rollout.log'}")
    data = json.loads((episode / "rollout.json").read_text(encoding="utf-8"))
    outcome = {"scenario_id": sample["scenario_id"], "schema": schema, "schema_raw": raw, "base_summary": summary,
               "steps": data["steps"], "metrics": data["metrics"], "total_reward": data["metrics"]["accumulated_earnings"],
               "generated": {"scenario_path": str(episode / "scenarios/interactive.json")},
               "execution": "native BPTK run_scenarios ABM; upstream SD-only session transport replaced"}
    assert data["steps"] == 96
    (episode / "episode.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
    if verbose:
        print(f"EDT: completed {data['steps']} native ABM steps. Accumulated earnings: {data['metrics']['accumulated_earnings']}")
    return outcome


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    folder = args.root.resolve()
    os.chdir(folder)
    sys.path.insert(0, str(folder))
    import numpy as np
    random.seed(args.seed)
    np.random.seed(args.seed)
    from BPTK_Py import bptk
    engine = bptk()
    properties = ["cash", "cash_flow", "profit_margin", "overall_profit_margin", "avg_utilization", "overall_avg_utilization",
                  "revenue_risk", "accumulated_earnings", "accumulated_revenue", "accumulated_expenses", "avg_consulting_fee", "overall_avg_consulting_fee"]
    try:
        frame = engine.run_scenarios(scenarios=["interactive"], scenario_managers=["smEDT"], agents=["controlling"],
                    agent_states=["active"], agent_properties=properties, agent_property_types=["total"], return_format="df")
        assert frame is not None and len(frame) == 96, "Native EDT did not produce all 96 steps"
        frame.to_csv(folder / "trajectory.csv")
        metrics = {}
        for name in properties:
            matches = [column for column in frame.columns if str(column) == f"smEDT_interactive_controlling_active_{name}_total"]
            if len(matches) != 1:
                raise RuntimeError(f"Cannot identify metric {name}: {list(frame.columns)}")
            metrics[name] = float(frame[matches[0]].iloc[-1])
        assert all(np.isfinite(value) for value in metrics.values())
        (folder / "rollout.json").write_text(json.dumps({"steps": len(frame), "seed": args.seed, "metrics": metrics}, indent=2), encoding="utf-8")
    finally:
        engine.destroy()


if __name__ == "__main__":
    main()
