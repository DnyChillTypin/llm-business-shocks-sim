"""One observation/action/transition loop for both rules and the LLM policy."""
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from src.agents.baselines import choose_actions
from src.agents.llm import serialize_observation, validate_actions
from src.envs.kaggle_retailbench import KaggleRetailEnvironment


def append(path, record):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")


def apply_actions(env, observation, actions):
    # Validate the complete portfolio before the first mutation.
    validate_actions(actions, observation)
    for sku, action in actions.items():
        result = env.exec_tools("modify_sku_price", sku_id=sku,
                                new_price=observation["products"][sku]["reference_price"] * action["price_multiplier"])
        if "error" in result["result"]:
            raise RuntimeError(result["result"]["error"])
    lines = [{"sku_id": sku, "quantity": a["order_quantity"]} for sku, a in actions.items() if a["order_quantity"]]
    if lines:
        result = env.exec_tools("place_order", items=lines, supplier_id="assumed_supplier")
        if "error" in result["result"]:
            raise RuntimeError(result["result"]["error"])
    result = env.exec_tools("end_today")
    if "error" in result["result"]:
        raise RuntimeError(result["result"]["error"])


def run_episode(prepared_dir, run_dir, *, scenario="control", policy="fixed", decide=None):
    run_dir = Path(run_dir)
    if (run_dir / "actions.jsonl").exists():
        raise ValueError("Never restart a partial/completed episode in the same directory.")
    env = KaggleRetailEnvironment(prepared_dir, run_dir, scenario)
    initial_net_worth = env.funds + env.inventory.compute_net_worth(env.current_date)
    decisions = []
    while not env.done:
        observation = env.observe()
        serialized = serialize_observation(observation)
        append(run_dir / "observations.jsonl", {"date": observation["date"], "observation": observation,
            "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest()})
        if decide:
            actions, details = decide(observation)
        else:
            actions = choose_actions(observation, policy)
            details = {"source": policy, "fallback_used": False, "repair_attempted": False, "invalid_responses": 0}
        # Preserve the decision before applying tools, including any eventual failure.
        record = {"date": observation["date"], "policy": policy, "actions": actions, **details}
        append(run_dir / "actions.jsonl", record)
        apply_actions(env, observation, actions)
        decisions.append(record)
    frame = pd.DataFrame(env.ledger)
    frame["policy"] = policy
    flags = {r["date"]: r for r in decisions}
    for name in ("fallback_used", "repair_attempted", "invalid_responses"):
        frame[name] = frame["date"].astype(str).map(lambda day: flags[day][name])
    final_net_worth = env.funds + env.inventory.compute_net_worth(env.current_date) + sum(
        order.cost for order in env.order_manager.get_current_orders())
    if not math.isclose(final_net_worth - initial_net_worth, float(frame["contribution"].sum()), abs_tol=1e-6):
        raise AssertionError("Cash, inventory, pipeline assets and contribution do not reconcile.")
    summary = {"scenario": scenario, "policy": policy, "days": frame["date"].nunique(), "products": len(env.catalog),
        "contribution": float(frame["contribution"].sum()), "revenue": float(frame["revenue"].sum()),
        "fill_rate": float(frame["sales"].sum() / frame["demand"].sum()) if frame["demand"].sum() else 1.0,
        "stockout_sku_days": int((frame["lost_sales"] > 0).sum()),
        "mean_closing_inventory": float(frame.groupby("date")["closing_inventory"].sum().mean()),
        "final_funds": float(env.funds), "net_worth_change": float(final_net_worth - initial_net_worth),
        "decision_opportunities": len(decisions), "fallback_days": sum(r["fallback_used"] for r in decisions),
        "repair_days": sum(r["repair_attempted"] for r in decisions),
        "invalid_responses": sum(r["invalid_responses"] for r in decisions),
        "accounting_reconciled": True}
    frame.to_csv(run_dir / "daily_results.csv", index=False)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return frame, summary
