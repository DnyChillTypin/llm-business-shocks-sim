"""Export independently replayed primary episodes and aggregate ledger evidence; no API calls."""
import argparse
import csv
import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.experiments.kaggle_protocol import (read, write, primary_matrix, prior_runs,
    require_fallback_reviews, failure_evidence_digest)
from src.experiments.kaggle_validation import validate_run
from src.research.design import canonical_hash, validate_design

PUBLIC = ROOT / "docs/results/stage5"


def csv_write(path, rows, fields=None):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through-index", type=int, choices=(11, 23, 35), default=35)
    args = parser.parse_args()
    study = read(ROOT / "configs/study.json")
    design_check = validate_design(ROOT)
    execution_paths = ["src/agents", "src/envs", "src/data", "src/benchmarks/gateway.py", "src/benchmarks/budget.py",
        "src/experiments/kaggle.py", "src/experiments/kaggle_protocol.py", "src/experiments/kaggle_validation.py",
        "scripts/run_kaggle_experiment.py", "configs/study.json", "configs/kaggle_retailbench.json", "prompts"]
    assert not subprocess.check_output(["git", "diff", "3d856a8", "--", *execution_paths], cwd=ROOT), "Execution code changed after preparation."
    matrix = primary_matrix(study)
    allowance = read(ROOT / ".cache/approvals/stage5_allowance.approved.json")
    results = ROOT / "results/runs/kaggle_retailbench"
    assert not (results / ".kaggle_execution.lock").exists(), "Snapshot only between episodes."
    require_fallback_reviews(results)
    planned = {e["episode_id"]: i for i, e in enumerate(matrix["episodes"])}
    found = {}
    for run, manifest in prior_runs(results):
        if manifest.get("episode_id") in planned:
            index = planned[manifest["episode_id"]]
            assert index <= args.through_index, "Checkpoint must include every primary cohort."
            assert manifest["status"] in {"validated_complete", "incomplete"}
            found.setdefault(index, []).append((run, manifest))
    assert set(found) == set(range(args.through_index + 1))
    ledger_path = ROOT / "results/budgets" / (allowance["budget_id"] + ".sqlite")
    with closing(sqlite3.connect(ledger_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        ledger = {r[0]: dict(run=r[1], scope=r[2], status=r[3], actual=r[4], reserve=r[5]) for r in
                  db.execute("SELECT id,run_id,scope,status,actual_nanos,reserved_nanos FROM attempts")}
        held_ids = {r[0] for r in db.execute("SELECT attempt_id FROM bounded_holds")}
    assert not any(r["status"] == "pending" or (r["status"] == "uncertain" and k not in held_ids) for k, r in ledger.items())
    before = read(PUBLIC / "preparation.json")["budget_snapshot"]
    coverage, daily, failures, reports = [], [], [], []
    started_ids, matched = set(), {}
    returned_models = set()
    for index in range(args.through_index + 1):
        episode, cohorts = matrix["episodes"][index], found[index]
        complete = [(r, m) for r, m in cohorts if m["status"] == "validated_complete"]
        assert len(complete) == 1, "Every included planned episode needs exactly one complete cohort."
        all_cost = 0
        for run, manifest in cohorts:
            events = [json.loads(s) for s in (run / "api_attempts.jsonl").read_text(encoding="utf-8").splitlines()] if (run / "api_attempts.jsonl").exists() else []
            starts = [e for e in events if e["event"] == "started"]
            for event in starts:
                identity = event["attempt_id"]
                assert identity not in started_ids
                started_ids.add(identity)
                assert ledger[identity]["run"] == run.name and ledger[identity]["scope"] == "kaggle"
                row = ledger[identity]
                all_cost += row["actual"] if row["actual"] is not None else row["reserve"]
            if manifest["status"] == "incomplete":
                review = read(run / "failure_review.json")
                known = sum(ledger[e["attempt_id"]]["actual"] or 0 for e in starts)
                held = sum(ledger[e["attempt_id"]]["reserve"] for e in starts if ledger[e["attempt_id"]]["actual"] is None)
                failures.append(dict(matrix_index=index, status="retained_incomplete", failure_category=manifest.get("failure_category"),
                    started_attempts=len(starts), known_cost_credits=known / 1e9, fully_held_unknown_credits=held / 1e9,
                    evidence_sha256=failure_evidence_digest(run), review_decision=review["decision"]))
        run, manifest = complete[0]
        report = validate_run(run)
        assert report["status"] == "validated_complete" and all(report["checks"].values())
        reports.append(report)
        write(ROOT / f"results/verification/stage5/final_replay_{index:02d}.json", report)
        summary = read(run / "summary.json")
        paid = episode["policy"] == "llm_with_fallback"
        metadata = dict(matrix_index=index, store_id=episode["series"]["store_id"], product_id=episode["series"]["product_id"],
            scenario=episode["scenario"], policy=episode["policy"])
        coverage.append({**metadata, "status": "validated_complete", "agent_kind": manifest["agent_kind"],
            **{k: summary[k] for k in ("days", "contribution", "revenue", "fill_rate", "stockout_sku_days",
                "mean_closing_inventory", "final_funds", "net_worth_change", "decision_opportunities", "repair_days", "fallback_days", "invalid_responses")},
            "first_pass_valid_decisions": 21 - summary["repair_days"] if paid else 0,
            "model_decisions_after_repair": 21 - summary["fallback_days"] if paid else 0,
            "successful_cohort_attempts": report["api_attempts"], "successful_cohort_cost_credits": report["estimated_gateway_credit_usd"],
            "all_cohort_exposure_credits": all_cost / 1e9, "attempted_cohorts": len(cohorts),
            "retained_incomplete_cohorts": len(cohorts) - 1, "validation_checks": len(report["checks"]),
            "evidence_sha256": report["evidence_sha256"]})
        frame = pd.read_csv(run / "daily_results.csv")
        for _, row in frame.iterrows():
            daily.append({**metadata, **row.to_dict()})
        key = (metadata["store_id"], metadata["product_id"], metadata["scenario"])
        matched.setdefault(key, []).append(report)
        if paid:
            for line in (run / "api_attempts.jsonl").read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event["event"] == "finished":
                    returned_models.add(event["returned_model"])
    assert len(started_ids) <= 504
    assert len(ledger) == before["total_project_attempts"] + len(started_ids)
    primary_exposure = sum(ledger[i]["actual"] if ledger[i]["actual"] is not None else ledger[i]["reserve"] for i in started_ids)
    project_exposure = sum(r["actual"] if r["actual"] is not None else r["reserve"] for r in ledger.values())
    assert project_exposure == round(before["inclusive_project_exposure_credits"] * 1e9) + primary_exposure
    matches, base_by_series = [], {}
    for (store, product, scenario), items in matched.items():
        assert len(items) == 3
        initial = {r["initial_observation_sha256"] for r in items}
        demand = {r["base_demand_sha256"] for r in items}
        assert len(initial) == len(demand) == 1
        base_by_series.setdefault((store, product), set()).update(demand)
        matches.append(dict(store_id=store, product_id=product, scenario=scenario, policies=3,
            initial_conditions_match=True, base_demand_match=True,
            initial_observation_sha256=next(iter(initial)), base_demand_sha256=next(iter(demand))))
    assert all(len(v) == 1 for v in base_by_series.values())
    csv_write(PUBLIC / "coverage.csv", coverage)
    csv_write(PUBLIC / "daily_results.csv", daily)
    csv_write(PUBLIC / "matched_inputs.csv", matches)
    csv_write(PUBLIC / "retained_failures.csv", failures, fields=("matrix_index", "status", "failure_category", "started_attempts",
        "known_cost_credits", "fully_held_unknown_credits", "evidence_sha256", "review_decision"))
    llm = [r for r in coverage if r["policy"] == "llm_with_fallback"]
    checks = dict(frozen_design_unchanged=True, execution_code_unchanged_since_preparation=True, all_complete_episodes_independently_replayed=True,
        matched_initial_conditions_and_base_paths=True, identical_base_paths_across_scenarios=True,
        exact_policy_requests_and_known_usage=True, all_attempts_and_held_charges_reconciled=True,
        fallback_and_failure_reviews_current=True, cash_inventory_pipeline_reconciled=True,
        no_duplicate_complete_episodes=True, all_fallback_days_retained=True, no_unresolved_charge=True)
    qc = dict(stage=5, status="passed", checks=checks, frozen_design_checks=len(design_check["checks"]),
        validated_episodes=len(coverage), validated_policy_days=len(daily), completed_llm_episodes=len(llm),
        completed_primary_decision_opportunities=21 * len(llm), first_pass_valid_decisions=sum(r["first_pass_valid_decisions"] for r in llm),
        model_decisions_after_repair=sum(r["model_decisions_after_repair"] for r in llm),
        repair_days=sum(r["repair_days"] for r in llm), fallback_days=sum(r["fallback_days"] for r in llm),
        invalid_responses=sum(r["invalid_responses"] for r in llm), successful_cohort_attempts=sum(r["successful_cohort_attempts"] for r in llm),
        all_primary_attempts=len(started_ids), maximum_primary_attempts=504, retained_incomplete_cohorts=len(failures),
        matched_scenario_cells=len(matches), matched_series_blocks=len(base_by_series))
    write(PUBLIC / "qc_summary.json", qc)
    kg_exposure = sum(r["actual"] if r["actual"] is not None else r["reserve"] for r in ledger.values() if r["scope"] == "kaggle")
    unknown = [r for r in ledger.values() if r["status"] == "uncertain"]
    complete = len(coverage) == 36
    status = dict(stage=5, status="complete" if complete else "in_progress_checkpoint", exit_gate_passed=complete,
        checked_on="2026-10-18", through_matrix_index=args.through_index, study_sha256=canonical_hash(study), matrix_sha256=canonical_hash(matrix),
        planned_episodes=36, completed_episodes=len(coverage), missing_matrix_indices=list(range(args.through_index + 1, 36)),
        completed_policy_days=len(daily), planned_policy_days=756, completed_llm_episodes=len(llm), planned_llm_episodes=12,
        completed_primary_decisions=21 * len(llm), planned_primary_decisions=252,
        requested_model=study["kaggle"]["model"]["requested_id"], returned_models=sorted(returned_models),
        primary_window=study["kaggle"]["windows"]["primary_evaluation"],
        budget_snapshot=dict(currency="USD_gateway_credit", inclusive_cap_credits=allowance["cap_usd"],
            native_scope_cap_credits=allowance["scope_caps_usd"]["native"], kaggle_scope_cap_credits=allowance["scope_caps_usd"]["kaggle"],
            unallocated_reserve_credits=round(allowance["cap_usd"] - sum(allowance["scope_caps_usd"].values()), 9),
            total_project_attempts=len(ledger), inclusive_project_exposure_credits=project_exposure / 1e9,
            known_project_cost_credits=sum(r["actual"] or 0 for r in ledger.values()) / 1e9,
            retained_unknown_attempts=len(unknown), retained_unknown_charge_credits=sum(r["reserve"] for r in unknown) / 1e9,
            all_primary_attempts=len(started_ids), primary_exposure_credits=primary_exposure / 1e9,
            successful_primary_cohort_cost_credits=sum(r["successful_cohort_cost_credits"] for r in llm),
            kaggle_scope_exposure_credits=kg_exposure / 1e9, remaining_kaggle_scope_credits=(round(allowance["scope_caps_usd"]["kaggle"] * 1e9) - kg_exposure) / 1e9,
            global_attempt_ceiling=allowance["max_attempts"], pending_attempts=0, blocking_unknown_attempts=0,
            qualification="Token-derived project estimates with full unknown-charge holds, not independently verified provider billing; local limits depend on tariffs and gateway token ceilings."),
        primary_window_prior_manual_outcome_use="uncertain; no pristine unseen-data claim",
        interpretation="Three matched series-window blocks with dependent daily rows; one LLM realization per condition. Synthetic simulator outcomes, not real-world causal evidence.",
        native_coverage_qualification="14 validated non-Retail tasks; ICBE validity failure retained; four Retail tasks deferred.")
    write(PUBLIC / "status.json", status)
    names = ("preparation.json", "launch_plan.csv", "coverage.csv", "daily_results.csv", "matched_inputs.csv", "retained_failures.csv", "qc_summary.json", "status.json")
    write(PUBLIC / "artifact_manifest.json", dict(hash_rule="SHA-256 UTF-8 text with CRLF normalized to LF",
        files={name: hashlib.sha256((PUBLIC / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for name in names}))
    print(json.dumps(dict(status=status["status"], episodes=len(coverage), policy_days=len(daily), primary_attempts=len(started_ids),
        primary_exposure_credits=primary_exposure / 1e9, project_exposure_credits=project_exposure / 1e9, fallback_days=qc["fallback_days"])))


if __name__ == "__main__":
    main()
