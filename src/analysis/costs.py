"""Measured pilot usage and explicitly partial projections; no model calls."""
import json
from datetime import datetime
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
        events = [json.loads(line) for line in (run / "api_attempts.jsonl").read_text(encoding="utf-8").splitlines()] if (run / "api_attempts.jsonl").exists() else []
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
            "models": sorted({e["requested_model"] for e in ends}),
            "elapsed_seconds": (datetime.fromisoformat(manifest["finished_at_utc"]) - datetime.fromisoformat(manifest["started_at_utc"])).total_seconds()})
    for path in sorted((root / "results/runs/kaggle_retailbench").glob("*/run_manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("purpose") != "pilot" or manifest.get("policy") != "llm_with_fallback":
            continue
        run = path.parent
        events = [json.loads(line) for line in (run / "api_attempts.jsonl").read_text(encoding="utf-8").splitlines()] if (run / "api_attempts.jsonl").exists() else []
        ends = [e for e in events if e["event"] == "finished"]
        summary = json.loads((run / "summary.json").read_text()) if (run / "summary.json").exists() else None
        observations.append({"task": "kaggle:validation_pilot", "scenario": manifest["scenario"], "run_id": run.name,
            "execution_status": manifest["status"], "validation_status": manifest["status"], "units": 1,
            "horizon": manifest["expected_days"], "attempts": sum(e["event"] == "started" for e in events),
            "finished_attempts": len(ends), "failed_attempts": sum(e["status"] != "completed" for e in ends),
            "input_tokens": sum((e.get("usage") or {}).get("prompt_tokens", 0) for e in ends),
            "output_tokens": sum((e.get("usage") or {}).get("completion_tokens", 0) for e in ends),
            "missing_usage_attempts": sum(e.get("cost_usd") is None for e in ends),
            "known_estimated_cost_usd": sum(e.get("cost_usd") or 0 for e in ends),
            "latency_seconds": [e["latency_seconds"] for e in ends], "native_score": None, "kaggle_summary": summary,
            "models": sorted({e["requested_model"] for e in ends}),
            "elapsed_seconds": (datetime.fromisoformat(manifest["finished_at_utc"]) - datetime.fromisoformat(manifest["started_at_utc"])).total_seconds()})
    for task in TASKS:
        plan = run_plan(task)
        pilots = [r for r in observations if r["task"] == task and r["validation_status"] == "validated_complete"]
        measurement = pilots[-1] if pilots else None
        base, seconds, calls, wall = None, None, None, None
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
            wall = measurement["elapsed_seconds"] * scale
        rows.append({"task": task, "measured_run_id": measurement["run_id"] if measurement else None,
            "projection_status": "linear_single_pilot_scenario" if measurement else "not_estimable_yet",
            "full_units": plan["expected_units"], "full_horizon": plan["configured_horizon"],
            "projected_calls_base": calls, "serialized_api_seconds_base": seconds,
            "projected_elapsed_seconds_base": wall,
            "cost_low_scenario_usd": base * .75 if base is not None else None,
            "cost_base_scenario_usd": base, "cost_high_scenario_usd": base * 2 if base is not None else None,
            "qualification": "0.75x/1x/2x planning assumptions, not statistical intervals; single pilots do not measure heterogeneity, late context or retries."})
    kaggle = [r for r in observations if r["task"] == "kaggle:validation_pilot" and r["validation_status"] == "validated_complete"]
    kaggle_days = sum(r["horizon"] for r in kaggle)
    kaggle_ready = {r["scenario"] for r in kaggle} >= {"control", "delivery_disruption"}
    base = sum(r["known_estimated_cost_usd"] for r in kaggle) * 252 / kaggle_days if kaggle_days else None
    rows.append({"task": "kaggle:primary_matrix", "projection_status": "linear_validation_pilot_scenario" if kaggle_days else "not_estimable_yet", "primary_decisions": 252,
        "maximum_attempts_with_repairs": 504, "cost_low_scenario_usd": None, "cost_base_scenario_usd": None,
        "cost_high_scenario_usd": None, "qualification": "Validation episodes only; price/case/context and repair frequency may differ in evaluation. Free/scripted runs excluded."})
    if kaggle_days:
        rows[-1].update(cost_low_scenario_usd=base * .75, cost_base_scenario_usd=base, cost_high_scenario_usd=base * 2,
            projected_calls_base=sum(r["attempts"] for r in kaggle) * 252 / kaggle_days,
            serialized_api_seconds_base=sum(sum(r["latency_seconds"]) for r in kaggle) * 252 / kaggle_days,
            projected_elapsed_seconds_base=sum(r["elapsed_seconds"] for r in kaggle) * 252 / kaggle_days)
    totals = {"attempts": sum(r["attempts"] for r in observations),
        "known_estimated_cost_usd": sum(r["known_estimated_cost_usd"] for r in observations),
        "missing_usage_attempts": sum(r["missing_usage_attempts"] for r in observations),
        "validated_native_pilot_tasks": sum(bool(r.get("measured_run_id")) for r in rows),
        "known_projection_subtotal_base_usd": sum(r["cost_base_scenario_usd"] or 0 for r in rows),
        "unmeasured_tasks": [r["task"] for r in rows if r["projection_status"] == "not_estimable_yet"],
        "full_suite_cost_estimate_usd": sum(r["cost_base_scenario_usd"] for r in rows) if kaggle_ready and all(r["cost_base_scenario_usd"] is not None for r in rows) else None,
        "budget_decision": "No large-run cap recommended until missing pilots and charging reconciliation are complete.",
        "qualification": "Gateway-credit tariff estimates, not independently verified billing. Subtotal excludes missing families; it is not a full-suite budget."}
    return {"purpose": "pilot_cost_planning_not_benchmark_evaluation", "observations": observations,
            "projections": rows, "totals": totals}
