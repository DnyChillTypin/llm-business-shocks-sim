"""Replay saved observation/action contracts and accounting without API calls."""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.agents.llm import serialize_observation, validate_actions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    run = args.run
    read = lambda name: json.loads((run / name).read_text(encoding="utf-8"))
    lines = lambda name: [json.loads(line) for line in (run / name).read_text(encoding="utf-8").splitlines()]
    manifest, summary, budget = read("run_manifest.json"), read("summary.json"), read("budget_summary.json")
    observations, actions, events = lines("observations.jsonl"), lines("actions.jsonl"), lines("api_attempts.jsonl")
    frame = pd.read_csv(run / "daily_results.csv")
    starts = [e for e in events if e["event"] == "started"]
    finishes = [e for e in events if e["event"] == "finished"]
    obs = {r["date"]: r["observation"] for r in observations}
    checks = {"validated_execution": manifest["status"] == "validated_complete",
        "validation_window_only": manifest["purpose"] == "pilot" and manifest["window"] == "validation_pilot" and not manifest["primary_evaluation"],
        "full_21_days": len(obs) == len(actions) == frame["date"].nunique() == summary["days"] == 21,
        "attempts_complete": {e["attempt_id"] for e in starts} == {e["attempt_id"] for e in finishes},
        "usage_known_for_this_run": all(e["status"] == "completed" and e["cost_usd"] is not None for e in finishes),
        "no_blocking_charge": budget["pending_attempts"] == budget.get("blocking_uncertain_attempts", budget["uncertain_attempts"]) == 0,
        "observation_hashes": all(r["sha256"] == hashlib.sha256(serialize_observation(r["observation"]).encode("utf-8")).hexdigest() for r in observations),
        "strictly_past_history": all(h["date"] < day for day, o in obs.items() for p in o["products"].values() for h in p["history"]),
        "no_hidden_scenario_label": all("scenario" not in o and "future_demand" not in o for o in obs.values()),
        "repairs_accounted": len(starts) == 21 + sum(a["repair_attempted"] for a in actions),
        "fallbacks_accounted": sum(a["fallback_used"] for a in actions) == summary["fallback_days"] == int(frame["fallback_used"].sum()),
        "contribution_reconciles": math.isclose(float(frame["contribution"].sum()), summary["contribution"], abs_tol=1e-6) and math.isclose(summary["net_worth_change"], summary["contribution"], abs_tol=1e-6)}
    checks["all_actions_valid"] = True
    for action in actions:
        validate_actions(action["actions"], obs[action["date"]])
    checks["exact_shared_observation_sent"] = True
    for event in starts:
        request = read(f"attempts/{event['attempt_id']}/request.json")
        day = event["context"]["case_id"]
        checks["exact_shared_observation_sent"] &= json.loads(request["messages"][1]["content"]) == obs[day]
    ordered_days = sorted(obs)
    first = obs[ordered_days[0]]
    purchase_cost = sum(a["actions"][sku]["order_quantity"] * obs[a["date"]]["products"][sku]["unit_cost"] for a in actions for sku in a["actions"])
    cash = first["funds"] - purchase_cost + float(frame["revenue"].sum()) - float(frame["holding_cost"].sum())
    checks["cash_reconciles"] = math.isclose(cash, summary["final_funds"], abs_tol=1e-6)
    checks["inventory_conservation"] = bool(((frame["opening_inventory"] - frame["sales"]) == frame["closing_inventory"]).all())
    report = {"status": "validated_complete" if all(checks.values()) else "requires_review", "checks": checks,
        "run_id": run.name, "scenario": manifest["scenario"], "purpose": manifest["purpose"], "summary": summary,
        "api_attempts": len(starts), "estimated_gateway_credit_usd": sum(e["cost_usd"] for e in finishes),
        "initial_observation_sha256": observations[0]["sha256"], "prepared_checksums_sha256": manifest["prepared_checksums_sha256"],
        "base_demand_sha256": hashlib.sha256(frame[["date", "sku_id", "base_demand"]].to_csv(index=False).encode()).hexdigest(),
        "qualification": "Genuine validation pilot, not primary test evaluation; synthetic data and assumed price/shock responses."}
    (run / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "validated_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
