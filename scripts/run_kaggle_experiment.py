"""Frozen Kaggle plans and sequential, explicitly authorized episode execution."""
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
from src.experiments.kaggle_protocol import (PRIMARY_TASK, read, write, episode_id, primary_matrix,
    require_primary_authorization, require_episode_available, require_fallback_reviews,
    remaining_primary_attempts, execution_lock, save_matrix_registry, require_existing_ledger, require_matching_baselines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/study.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--policies", nargs="+", choices=["fixed", "adaptive", "llm_with_fallback"])
    parser.add_argument("--scenario", choices=["control", "demand_surge", "demand_decline", "delivery_disruption"])
    parser.add_argument("--episode-index", type=int, help="One zero-based position in the frozen 36-episode primary matrix.")
    parser.add_argument("--execute-paid", action="store_true")
    parser.add_argument("--budget", type=Path)
    parser.add_argument("--execution-manifest", type=Path, help="Explicit primary run authorization; the checked-in template is unapproved.")
    parser.add_argument("--retry-failed", action="store_true", help="Fresh episode only after an evidence-bound failure review; never resume partial state.")
    args = parser.parse_args()
    from src.research.design import validate_design, canonical_hash
    validate_design(ROOT)
    study = read(ROOT / "configs/study.json")
    spec = read(args.config)
    pilot = spec.get("purpose") == "pilot"
    if pilot and spec != read(ROOT / "configs/pilots/kaggle.json"):
        parser.error("Use the unchanged checked-in pilot configuration.")
    if not pilot and spec != study:
        parser.error("Evaluation requires the unchanged frozen study.")
    design, matrix = study["kaggle"], primary_matrix(study)
    purpose, window = ("pilot", "validation_pilot") if pilot else ("evaluation", "primary_evaluation")
    series = [design["selection"]["selected_series"][i] for i in (spec["series_indices"] if pilot else range(3))]
    scenarios = spec["scenarios"] if pilot else design["scenarios"]
    if args.scenario:
        if not pilot or args.scenario not in scenarios:
            parser.error("Scenario subsets are only available for the bounded validation pilot.")
        scenarios = [args.scenario]
    policies = args.policies or (spec["policies"] if pilot else design["policy_ids"])
    if len(set(policies)) != len(policies):
        parser.error("Duplicate policy names would duplicate episodes.")
    episodes = [dict(series=s, scenario=c, policy=p, window=window, purpose=purpose)
                for s, c, p in itertools.product(series, scenarios, policies)]
    if args.episode_index is not None:
        if pilot or args.policies or not 0 <= args.episode_index < len(matrix["episodes"]):
            parser.error("Episode index requires the primary matrix without policy overrides.")
        episodes = [matrix["episodes"][args.episode_index]]
    plan = {"study_id": study["study_id"], "episodes": episodes, "horizon": design["horizon_days"],
            "matrix_sha256": canonical_hash(matrix),
            "primary_llm_decisions": sum(e["policy"] == "llm_with_fallback" for e in episodes) * 21,
            "paid_calls_authorized_by_plan": False}
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return 0
    paid = any(e["policy"] == "llm_with_fallback" for e in episodes)
    if args.execute_paid and not paid:
        parser.error("Do not mark a baseline run as paid execution.")
    if paid:
        if not (args.execute_paid and args.budget and len(episodes) == 1):
            parser.error("Paid execution requires one episode, --execute-paid and --budget.")
        if pilot:
            if not args.scenario or args.execution_manifest:
                parser.error("Paid pilot requires one --scenario and no primary authorization.")
        else:
            if args.episode_index is None or not args.execution_manifest:
                parser.error("Primary paid execution requires --episode-index and --execution-manifest.")
            # All authorization checks precede credentials, prepared primary data and gateway construction.
            require_primary_authorization(read(args.execution_manifest), read(args.budget), matrix)
            require_existing_ledger(read(args.budget))
    elif args.execution_manifest:
        parser.error("A primary spending manifest is only valid for a paid primary episode.")
    from src.data.kaggle import prepare_dataset
    from src.experiments.kaggle import run_episode
    from src.experiments.kaggle_validation import validate_run
    results = ROOT / "results/runs/kaggle_retailbench"
    with execution_lock(results):
        if not pilot:
            save_matrix_registry(results, matrix)
        for index, episode in enumerate(episodes):
            identity = episode_id(episode)
            if paid:
                require_fallback_reviews(results)
                if not pilot:
                    require_matching_baselines(results, episode)
            rerun_of = require_episode_available(results, identity, retry_failed=args.retry_failed)
            remaining = remaining_primary_attempts(results, matrix) if paid and not pilot else 42
            if paid and remaining < 21:
                raise ValueError("Insufficient remaining primary attempt slots for another full episode.")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            run = results / f"{purpose}_{stamp}_{index:02d}"
            run.mkdir()
            selected = episode["series"]
            prepared = ROOT / "data/processed/kaggle_retailbench" / f"{window}_{selected['store_id']}_{selected['product_id']}"
            manifest = {"episode_id": identity, **episode, "status": "running", "expected_days": 21, "rerun_of": rerun_of,
                "agent_kind": "genuine_llm" if paid else "baseline", "primary_evaluation": not pilot,
                "started_at_utc": datetime.now(timezone.utc).isoformat(), "study_sha256": canonical_hash(study),
                "project_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "project_tracked_dirty": bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True).strip())}
            write(run / "run_manifest.json", manifest)
            budget, counts, decide = None, None, None
            try:
                prepare_dataset(ROOT / study["dataset"]["path"], prepared, store_id=selected["store_id"],
                    product_ids=[selected["product_id"]], episode_start=design["windows"][window]["start"])
                manifest["prepared_checksums_sha256"] = hashlib.sha256((prepared / "artifact_checksums.json").read_bytes()).hexdigest()
                if paid:
                    from src.benchmarks.common import credentials, settings, install_gateway_clients
                    from src.benchmarks.budget import load_budget
                    from src.agents.llm import LLMPolicy
                    _, base = credentials()
                    budget = load_budget(args.budget, run_id=run.name, scope="kaggle", base_url=base, purpose=purpose)
                    task = "kaggle:validation_pilot" if pilot else PRIMARY_TASK
                    if task not in budget.manifest["allowed_tasks"]:
                        raise ValueError("The cumulative allowance does not authorize this Kaggle task.")
                    config = {**settings(), "max_output_tokens": design["model"]["max_output_tokens"],
                        "max_api_calls_per_task": min(42, remaining), "_purpose": purpose, "_run_id": run.name,
                        "_request_context": {"task_id": task, "episode_id": identity}}
                    counts = install_gateway_clients(run, config, budget=budget)
                    import openai
                    decide = LLMPolicy(openai.OpenAI(), design["model"])
                    manifest.update(budget_id=budget.manifest["budget_id"], allowance_sha256=budget.fingerprint)
                _, summary = run_episode(prepared, run, scenario=episode["scenario"], policy=episode["policy"], decide=decide)
                manifest.update(status="execution_finished_requires_artifact_review", completed_days=summary["days"],
                    fallback_review_required=paid and summary["fallback_days"] / summary["decision_opportunities"] > .05)
                write(run / "run_manifest.json", manifest)
                if budget:
                    write(run / "budget_summary.json", budget.summary())
                validation = validate_run(run)
                write(run / "validation.json", validation)
                if validation["status"] != "validated_complete":
                    raise RuntimeError("Saved episode failed independent replay/provenance/accounting checks.")
                manifest["status"] = "validated_complete"
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
                if not pilot:
                    save_matrix_registry(results, matrix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
