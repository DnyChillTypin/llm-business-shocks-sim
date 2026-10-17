"""Measured pilot usage and explicitly partial projections; no model calls."""
import json
from pathlib import Path

from src.benchmarks.common import ROOT, TASKS
from src.benchmarks.planning import run_plan


def cost_report(root=ROOT):
    root = Path(root)
    observations, rows = [], []
    for path in sorted((root / "results/benchmarks").glob("*/*/run_manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["purpose"] != "pilot":
            continue
        run = path.parent
        events = [json.loads(line) for line in (run / "api_attempts.jsonl").read_text(encoding="utf-8").splitlines()]
        ends = [e for e in events if e["event"] == "finished"]
        validation = json.loads((run / "validation.json").read_text()) if (run / "validation.json").exists() else {}
        observations.append({"task": manifest["task"], "run_id": run.name, "execution_status": manifest["status"],
            "validation_status": validation.get("status", "not_validated"),
            "units": manifest["expected_units"], "horizon": manifest["configured_horizon"],
            "attempts": sum(e["event"] == "started" for e in events), "finished_attempts": len(ends),
            "failed_attempts": sum(e["status"] != "completed" for e in ends),
            "input_tokens": sum((e.get("usage") or {}).get("prompt_tokens", 0) for e in ends),
            "output_tokens": sum((e.get("usage") or {}).get("completion_tokens", 0) for e in ends),
            "missing_usage_attempts": sum(e.get("cost_usd") is None for e in ends),
            "known_estimated_cost_usd": sum(e.get("cost_usd") or 0 for e in ends),
            "latency_seconds": [e["latency_seconds"] for e in ends], "native_score": validation.get("native_score"),
            "models": sorted({e["requested_model"] for e in ends})})
    for task in TASKS:
        plan = run_plan(task)
        pilots = [r for r in observations if r["task"] == task and r["validation_status"] == "validated_complete"]
        measurement = pilots[-1] if pilots else None
        base, seconds, calls = None, None, None
        if measurement:
            if task.startswith("retail:"):
                scale = plan["configured_horizon"] / measurement["horizon"]
            elif task == "icbe":
                scale = plan["expected_units"] * plan["configured_horizon"] / (measurement["units"] * measurement["horizon"])
            else:
                scale = plan["expected_units"] / measurement["units"]
            base = measurement["known_estimated_cost_usd"] * scale
            seconds = sum(measurement["latency_seconds"]) * scale
            calls = measurement["attempts"] * scale
        rows.append({"task": task, "measured_run_id": measurement["run_id"] if measurement else None,
            "projection_status": "linear_single_pilot_scenario" if measurement else "not_estimable_yet",
            "full_units": plan["expected_units"], "full_horizon": plan["configured_horizon"],
            "projected_calls_base": calls, "serialized_api_seconds_base": seconds,
            "cost_low_scenario_usd": base * .75 if base is not None else None,
            "cost_base_scenario_usd": base, "cost_high_scenario_usd": base * 2 if base is not None else None,
            "qualification": "0.75x/1x/2x planning assumptions, not statistical intervals; single pilots do not measure heterogeneity, late context or retries."})
    rows.append({"task": "kaggle:primary_matrix", "projection_status": "not_estimable_yet", "primary_decisions": 252,
        "maximum_attempts_with_repairs": 504, "cost_low_scenario_usd": None, "cost_base_scenario_usd": None,
        "cost_high_scenario_usd": None, "qualification": "Validation LLM episodes not yet measured; free/scripted runs excluded."})
    totals = {"attempts": sum(r["attempts"] for r in observations),
        "known_estimated_cost_usd": sum(r["known_estimated_cost_usd"] for r in observations),
        "missing_usage_attempts": sum(r["missing_usage_attempts"] for r in observations),
        "validated_native_pilot_tasks": sum(bool(r.get("measured_run_id")) for r in rows),
        "known_projection_subtotal_base_usd": sum(r["cost_base_scenario_usd"] or 0 for r in rows),
        "unmeasured_tasks": [r["task"] for r in rows if r["projection_status"] == "not_estimable_yet"],
        "full_suite_cost_estimate_usd": None,
        "budget_decision": "No large-run cap recommended until missing pilots and charging reconciliation are complete.",
        "qualification": "Gateway-credit tariff estimates, not independently verified billing. Subtotal excludes missing families; it is not a full-suite budget."}
    return {"purpose": "pilot_cost_planning_not_benchmark_evaluation", "observations": observations,
            "projections": rows, "totals": totals}
