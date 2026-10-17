"""Two simple policies executed through RetailBench's real tool dispatch."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from src.envs.kaggle_retailbench import KaggleRetailEnvironment, SCENARIOS


def choose_actions(observation: dict, policy: str) -> dict:
    if policy not in ("fixed", "adaptive"):
        raise ValueError(f"Unknown policy: {policy}")
    remaining_funds = observation["funds"]
    actions = {}
    for sku, product in observation["products"].items():
        if policy == "fixed":
            mean = product["training_mean_demand"]
            price_multiplier = 1.0
        else:
            past = product["history"][-14:]
            mean = sum(row["reference_demand"] for row in past) / len(past) if past else product["training_mean_demand"]
            coverage = product["inventory"] / max(mean, 1e-9)
            price_multiplier = 1.1 if coverage < 2 else (0.9 if coverage > 7 else 1.0)
        target_order = max(0, math.ceil(5 * mean - product["inventory"] - product["on_order"]))
        affordable = max(0, math.floor(remaining_funds / product["unit_cost"]))
        quantity = min(target_order, product["max_order_quantity"], affordable)
        remaining_funds -= quantity * product["unit_cost"]
        actions[sku] = {"order_quantity": quantity, "price_multiplier": price_multiplier}
    return actions


def run_baseline(prepared_dir: str | Path, run_dir: str | Path, *, scenario="control", policy="fixed") -> tuple[pd.DataFrame, dict]:
    run_dir = Path(run_dir)
    env = KaggleRetailEnvironment(prepared_dir, run_dir, scenario)
    initial_net_worth = env.funds + env.inventory.compute_net_worth(env.current_date)
    while not env.done:
        observation = env.observe()
        actions = choose_actions(observation, policy)
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
        with (run_dir / "actions.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"date": observation["date"], "policy": policy, "actions": actions}) + "\n")
        result = env.exec_tools("end_today")
        if "error" in result["result"]:
            raise RuntimeError(result["result"]["error"])
    frame = pd.DataFrame(env.ledger)
    frame["policy"] = policy
    final_net_worth = env.funds + env.inventory.compute_net_worth(env.current_date) + sum(
        order.cost for order in env.order_manager.get_current_orders())
    if not math.isclose(final_net_worth - initial_net_worth, float(frame["contribution"].sum()), abs_tol=1e-6):
        raise AssertionError("Cash, inventory, pipeline assets and contribution do not reconcile.")
    summary = {
        "scenario": scenario, "policy": policy,
        "days": frame["date"].nunique(), "products": len(env.catalog),
        "contribution": float(frame["contribution"].sum()),
        "revenue": float(frame["revenue"].sum()),
        "fill_rate": float(frame["sales"].sum() / frame["demand"].sum()) if frame["demand"].sum() else 1.0,
        "stockout_sku_days": int((frame["lost_sales"] > 0).sum()),
        "mean_closing_inventory": float(frame.groupby("date")["closing_inventory"].sum().mean()),
        "final_funds": float(env.funds),
        "net_worth_change": float(final_net_worth - initial_net_worth),
    }
    frame.to_csv(run_dir / "daily_results.csv", index=False)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return frame, summary


def run_baseline_matrix(prepared_dir: str | Path, output_dir: str | Path):
    frames, summaries = [], []
    for scenario in SCENARIOS:
        for policy in ("fixed", "adaptive"):
            frame, summary = run_baseline(prepared_dir, Path(output_dir) / f"{scenario}_{policy}",
                                          scenario=scenario, policy=policy)
            frames.append(frame)
            summaries.append(summary)
    combined, summary_frame = pd.concat(frames, ignore_index=True), pd.DataFrame(summaries)
    combined.to_csv(Path(output_dir) / "all_daily_results.csv", index=False)
    summary_frame.to_csv(Path(output_dir) / "summary.csv", index=False)
    return combined, summary_frame
