"""Replay saved BeerGame actions offline to audit unusually large native totals."""
import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.benchmarks.worker import load_file


def audit(folder):
    module = load_file("beer_saved_action_audit", ROOT / "vendor/FirmBench/SeriousGame/beergame_mcp_server.py")
    episodes = []
    for path in sorted(Path(folder).rglob("episode_*.json")):
        saved = json.loads(path.read_text(encoding="utf-8"))
        if not {"episode_config", "steps", "metrics"} <= saved.keys():
            continue
        env = module.BeerGameEnv(module.BeerGameConfig(**saved["episode_config"]))
        obs_checks, transition_checks, backlogs = [], [], []
        for step in saved["steps"]:
            obs_checks.append(env._obs(env.cfg.controlled_role) == step["obs"])
            transition_checks.append(env.step(step["action"]["order_qty"]) == step["step_out"])
            backlogs.append(step["step_out"]["obs"]["backorder"])
        replay = env.metrics()
        costs = {role: sum(values) for role, values in env.cost_history.items()}
        episodes.append({"scenario_id": saved["scenario_id"], "weeks": len(saved["steps"]),
            "all_saved_observations_match": all(obs_checks), "all_saved_transitions_match": all(transition_checks),
            "all_native_metrics_match": replay == saved["metrics"],
            "chain_cost_equals_sum_of_role_costs": sum(costs.values()) == replay["total_cost_supply_chain"],
            "role_total_costs": costs,
            "role_maximum_orders": {role: max(values) for role, values in env.orders_history.items()},
            "native_backlog_proxy": replay["avg_backlog_controlled"],
            "derived_time_average_backlog_controlled": statistics.mean(backlogs),
            "qualification": "Native backlog metric repeats the final backlog rather than averaging historical backlogs; the derived time average is separately labeled. Large upstream costs are retained, not clipped."})
    checks = ("all_saved_observations_match", "all_saved_transitions_match", "all_native_metrics_match", "chain_cost_equals_sum_of_role_costs")
    return {"status": "passed" if episodes and all(all(e[k] for k in checks) for e in episodes) else "requires_review",
            "paid_api_calls": 0, "episodes": episodes,
            "scope": "Offline deterministic replay of actual saved LLM orders through pinned native environment; not a new policy run."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    report = audit(args.run)
    (args.run / "beer_audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
