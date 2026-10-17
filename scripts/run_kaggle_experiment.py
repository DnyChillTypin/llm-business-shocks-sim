"""Frozen shared-loop Kaggle plans, free baselines, or one explicitly budgeted pilot."""
import argparse
import hashlib
import itertools
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/study.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--policies", nargs="+", choices=["fixed", "adaptive", "llm_with_fallback"])
    parser.add_argument("--scenario", choices=["control", "demand_surge", "demand_decline", "delivery_disruption"])
    parser.add_argument("--execute-paid", action="store_true")
    parser.add_argument("--budget", type=Path)
    args = parser.parse_args()
    from src.research.design import validate_design, canonical_hash
    validate_design(ROOT)
    study = json.loads((ROOT / "configs/study.json").read_text(encoding="utf-8"))
    spec = json.loads(args.config.read_text(encoding="utf-8"))
    pilot = spec.get("purpose") == "pilot"
    if pilot and spec != json.loads((ROOT / "configs/pilots/kaggle.json").read_text(encoding="utf-8")):
        parser.error("Use the checked-in pilot configuration without silent overrides.")
    if not pilot and spec != study:
        parser.error("Evaluation requires the unchanged frozen study.")
    design = study["kaggle"]
    purpose, window = ("pilot", "validation_pilot") if pilot else ("evaluation", "primary_evaluation")
    series = [design["selection"]["selected_series"][i] for i in (spec["series_indices"] if pilot else range(3))]
    scenarios = spec["scenarios"] if pilot else design["scenarios"]
    if args.scenario:
        if not pilot or args.scenario not in scenarios:
            parser.error("Scenario subsets are only available for the bounded pilot.")
        scenarios = [args.scenario]
    policies = args.policies or (spec["policies"] if pilot else design["policy_ids"])
    episodes = [{"series": s, "scenario": c, "policy": p, "window": window, "purpose": purpose}
                for s, c, p in itertools.product(series, scenarios, policies)]
    plan = {"study_id": study["study_id"], "episodes": episodes, "horizon": design["horizon_days"],
            "primary_llm_decisions": sum(e["policy"] == "llm_with_fallback" for e in episodes) * design["horizon_days"],
            "paid_calls_authorized_by_plan": False}
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return 0
    paid = any(e["policy"] == "llm_with_fallback" for e in episodes)
    if paid and not (args.execute_paid and args.budget and pilot and args.scenario and len(episodes) == 1):
        parser.error("Initial paid execution requires one pilot --scenario, --execute-paid and --budget; evaluation is excluded.")
    if args.execute_paid and not paid:
        parser.error("Do not mark a baseline run as paid execution.")
    from src.data.kaggle import prepare_dataset
    from src.experiments.kaggle import run_episode
    from src.benchmarks.common import credentials, settings, install_gateway_clients
    from src.benchmarks.budget import load_budget
    from src.agents.llm import LLMPolicy
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    results = ROOT / "results/runs/kaggle_retailbench"
    for index, episode in enumerate(episodes):
        episode_id = canonical_hash({**episode, "frozen_design_sha256": hashlib.sha256((ROOT / "docs/results/study_design_manifest.json").read_bytes()).hexdigest()})
        if paid:
            for existing in results.glob("*/run_manifest.json"):
                prior = json.loads(existing.read_text())
                if prior.get("fallback_review_required"):
                    parser.error("A previous episode exceeded the fallback review trigger; resolve that quality gate first.")
                if prior.get("episode_id") == episode_id:
                    parser.error("Pilot episode already has a saved attempt; inspect it rather than silently rerunning.")
        run = results / f"{purpose}_{stamp}_{index:02d}"
        run.mkdir(parents=True)
        selected = episode["series"]
        prepared = ROOT / "data/processed/kaggle_retailbench" / f"{window}_{selected['store_id']}_{selected['product_id']}"
        prepare_dataset(ROOT / study["dataset"]["path"], prepared, store_id=selected["store_id"],
            product_ids=[selected["product_id"]], episode_start=design["windows"][window]["start"])
        manifest = {"episode_id": episode_id, **episode, "status": "running", "expected_days": design["horizon_days"],
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "project_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "project_tracked_dirty": bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True).strip()),
            "prepared_checksums_sha256": hashlib.sha256((prepared / "artifact_checksums.json").read_bytes()).hexdigest(),
            "study_sha256": canonical_hash(study), "primary_evaluation": not pilot}
        write(run / "run_manifest.json", manifest)
        budget, counts, decide = None, None, None
        try:
            if paid:
                _, base = credentials()
                budget = load_budget(args.budget, run_id=run.name, scope="kaggle", base_url=base, purpose=purpose)
                if "kaggle:validation_pilot" not in budget.manifest["allowed_tasks"]:
                    raise ValueError("The allowance does not authorize this pilot.")
                config = {**settings(), "max_output_tokens": design["model"]["max_output_tokens"],
                    "max_api_calls_per_task": 42, "_purpose": purpose, "_run_id": run.name,
                    "_request_context": {"task_id": "kaggle:validation_pilot", "episode_id": episode_id}}
                counts = install_gateway_clients(run, config, budget=budget)
                import openai
                decide = LLMPolicy(openai.OpenAI(), design["model"])
                manifest.update(budget_id=budget.manifest["budget_id"], allowance_sha256=budget.fingerprint)
            frame, summary = run_episode(prepared, run, scenario=episode["scenario"], policy=episode["policy"], decide=decide)
            if summary["days"] != design["horizon_days"] or not summary["accounting_reconciled"]:
                raise RuntimeError("Episode horizon/accounting validation failed.")
            if budget and (budget.summary()["pending_attempts"] or budget.summary()["blocking_uncertain_attempts"]):
                raise RuntimeError("Unresolved paid attempt accounting.")
            manifest.update(status="validated_complete", completed_days=summary["days"],
                fallback_review_required=summary["fallback_days"] / summary["decision_opportunities"] > .05)
            print(json.dumps({"run": str(run), "status": manifest["status"], **summary}, indent=2), flush=True)
        except BaseException as exc:
            manifest.update(status="incomplete", failure_category=type(exc).__name__)
            raise
        finally:
            if budget:
                write(run / "budget_summary.json", budget.summary())
                write(run / "usage_totals.json", counts)
            manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            write(run / "run_manifest.json", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
