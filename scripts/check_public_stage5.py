"""Validate historical preparation and saved primary aggregates; no model or episode runs."""
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check_public_stage2 import check
from src.experiments.kaggle_protocol import read, primary_matrix, authorization_template
from src.research.design import canonical_hash


def check_execution(public, matrix, before):
    status, qc = read(public / "status.json"), read(public / "qc_summary.json")
    manifest = read(public / "artifact_manifest.json")
    assert manifest["hash_rule"] == "SHA-256 UTF-8 text with CRLF normalized to LF"
    expected_files = {p.name for p in public.iterdir() if p.is_file()} - {"artifact_manifest.json"}
    assert set(manifest["files"]) == expected_files
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((public / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest
    rows = lambda name: list(csv.DictReader((public / name).read_text(encoding="utf-8").splitlines()))
    coverage, daily, matches, failures = (rows(name) for name in ("coverage.csv", "daily_results.csv", "matched_inputs.csv", "retained_failures.csv"))
    count = status["through_matrix_index"] + 1
    assert count in (12, 24, 36) and len(coverage) == count and len(daily) == count * 21
    assert status["completed_episodes"] == qc["validated_episodes"] == count
    assert status["missing_matrix_indices"] == list(range(count, 36))
    assert status["completed_policy_days"] == qc["validated_policy_days"] == 21 * count
    assert status["completed_llm_episodes"] == qc["completed_llm_episodes"] == count // 3
    assert status["completed_primary_decisions"] == qc["completed_primary_decision_opportunities"] == 21 * count // 3
    assert status["exit_gate_passed"] is (count == 36)
    assert status["status"] == ("complete" if count == 36 else "in_progress_checkpoint")
    assert status["matrix_sha256"] == canonical_hash(matrix)
    assert status["study_sha256"] == matrix["study_sha256"] and all(qc["checks"].values())
    assert status["planned_episodes"] == 36 and status["planned_policy_days"] == 756
    assert status["planned_llm_episodes"] == 12 and status["planned_primary_decisions"] == 252
    from datetime import date, timedelta
    start = date.fromisoformat(status["primary_window"]["start"])
    expected_days = [(start + timedelta(days=i)).isoformat() for i in range(21)]
    llm = []
    series_base_paths = {}
    for index, row in enumerate(coverage):
        episode = matrix["episodes"][index]
        assert row["matrix_index"] == str(index) and row["status"] == "validated_complete"
        assert row["days"] == row["decision_opportunities"] == "21"
        assert re.fullmatch(r"[0-9a-f]{64}", row["evidence_sha256"])
        assert row["store_id"] == episode["series"]["store_id"] and row["product_id"] == episode["series"]["product_id"]
        assert row["scenario"] == episode["scenario"] and row["policy"] == episode["policy"]
        data = [r for r in daily if r["matrix_index"] == str(index)]
        assert [r["date"] for r in data] == expected_days
        for day in data:
            assert all(day[k] == row[k] for k in ("store_id", "product_id", "scenario", "policy"))
            assert day["sku_id"] == row["product_id"]
            assert math.isclose(float(day["contribution"]), float(day["revenue"]) - float(day["cost_of_goods_sold"]) - float(day["holding_cost"]), abs_tol=1e-6)
            assert float(day["sales"]) + float(day["lost_sales"]) == float(day["demand"])
        for metric in ("contribution", "revenue"):
            assert math.isclose(float(row[metric]), sum(float(r[metric]) for r in data), abs_tol=1e-6)
        assert math.isclose(float(row["net_worth_change"]), float(row["contribution"]), abs_tol=1e-6)
        demand = sum(float(r["demand"]) for r in data)
        assert math.isclose(float(row["fill_rate"]), sum(float(r["sales"]) for r in data) / demand if demand else 1, abs_tol=1e-9)
        assert int(row["stockout_sku_days"]) == sum(float(r["lost_sales"]) > 0 for r in data)
        assert math.isclose(float(row["mean_closing_inventory"]), sum(float(r["closing_inventory"]) for r in data) / 21, abs_tol=1e-6)
        repairs = sum(r["repair_attempted"] == "True" for r in data)
        fallbacks = sum(r["fallback_used"] == "True" for r in data)
        assert all(r[k] in ("True", "False") for r in data for k in ("repair_attempted", "fallback_used"))
        assert int(row["repair_days"]) == repairs and int(row["fallback_days"]) == fallbacks
        assert int(row["invalid_responses"]) == sum(int(r["invalid_responses"]) for r in data)
        assert int(row["attempted_cohorts"]) == 1 + int(row["retained_incomplete_cohorts"])
        key = (row["store_id"], row["product_id"])
        base_path = [(r["date"], r["base_demand"]) for r in data]
        assert series_base_paths.setdefault(key, base_path) == base_path
        if episode["policy"] == "llm_with_fallback":
            assert row["agent_kind"] == "genuine_llm" and int(row["validation_checks"]) == 28
            assert 0 <= fallbacks <= repairs <= 21
            assert int(row["first_pass_valid_decisions"]) == 21 - repairs
            assert int(row["model_decisions_after_repair"]) == 21 - fallbacks
            assert int(row["invalid_responses"]) == repairs + fallbacks
            assert int(row["successful_cohort_attempts"]) == 21 + repairs
            llm.append(row)
        else:
            assert row["agent_kind"] == "baseline" and int(row["validation_checks"]) == 22
            assert repairs == fallbacks == int(row["successful_cohort_attempts"]) == 0
            assert float(row["all_cohort_exposure_credits"]) == 0
    assert len(matches) == qc["matched_scenario_cells"] == count // 3
    assert len({(r["store_id"], r["product_id"], r["scenario"]) for r in matches}) == len(matches)
    for row in matches:
        assert row["policies"] == "3" and row["initial_conditions_match"] == row["base_demand_match"] == "True"
        assert re.fullmatch(r"[0-9a-f]{64}", row["initial_observation_sha256"])
        assert re.fullmatch(r"[0-9a-f]{64}", row["base_demand_sha256"])
    for field in ("first_pass_valid_decisions", "model_decisions_after_repair", "repair_days", "fallback_days", "invalid_responses", "successful_cohort_attempts"):
        assert qc[field] == sum(int(r[field]) for r in llm)
    assert len(failures) == qc["retained_incomplete_cohorts"] == sum(int(r["retained_incomplete_cohorts"]) for r in coverage)
    assert all(r["status"] == "retained_incomplete" and re.fullmatch(r"[0-9a-f]{64}", r["evidence_sha256"]) for r in failures)
    budget = status["budget_snapshot"]
    assert budget["all_primary_attempts"] == qc["all_primary_attempts"] == qc["successful_cohort_attempts"] + sum(int(r["started_attempts"]) for r in failures)
    assert qc["all_primary_attempts"] <= qc["maximum_primary_attempts"] == 504
    assert budget["total_project_attempts"] == before["total_project_attempts"] + qc["all_primary_attempts"]
    assert budget["total_project_attempts"] <= budget["global_attempt_ceiling"] == 3000
    assert budget["pending_attempts"] == budget["blocking_unknown_attempts"] == 0
    assert budget["inclusive_cap_credits"] == 10 and budget["unallocated_reserve_credits"] == 2
    assert math.isclose(budget["primary_exposure_credits"], sum(float(r["all_cohort_exposure_credits"]) for r in coverage), abs_tol=1e-9)
    successful_cost = sum(float(r["successful_cohort_cost_credits"]) for r in llm)
    assert math.isclose(budget["successful_primary_cohort_cost_credits"], successful_cost, abs_tol=1e-9)
    assert math.isclose(budget["primary_exposure_credits"], successful_cost + sum(float(r["known_cost_credits"]) + float(r["fully_held_unknown_credits"]) for r in failures), abs_tol=1e-9)
    assert math.isclose(budget["inclusive_project_exposure_credits"], before["inclusive_project_exposure_credits"] + budget["primary_exposure_credits"], abs_tol=1e-9)
    assert math.isclose(budget["known_project_cost_credits"] + budget["retained_unknown_charge_credits"], budget["inclusive_project_exposure_credits"], abs_tol=1e-9)
    assert math.isclose(budget["kaggle_scope_exposure_credits"], before["prior_kaggle_exposure_credits"] + budget["primary_exposure_credits"], abs_tol=1e-9)
    assert math.isclose(budget["remaining_kaggle_scope_credits"] + budget["kaggle_scope_exposure_credits"], budget["kaggle_scope_cap_credits"], abs_tol=1e-9)
    assert budget["inclusive_project_exposure_credits"] <= budget["inclusive_cap_credits"]
    print(f"Stage 5 saved execution evidence passed: {count}/36 episodes, {len(daily)} policy-days; financial, reliability, matching and cost totals reconcile.")


def main():
    public = ROOT / "docs/results/stage5"
    files = {"preparation.json", "launch_plan.csv"}
    executed = (public / "status.json").exists()
    if executed:
        files |= {"coverage.csv", "daily_results.csv", "matched_inputs.csv", "retained_failures.csv", "status.json", "qc_summary.json", "artifact_manifest.json"}
    assert {p.name for p in public.iterdir() if p.is_file()} == files
    for path in public.iterdir():
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b[0-9a-f]{32}\b|\b20\d{6}T\d{12,}Z\b", text), path.name
        if path.suffix == ".json":
            check(json.loads(text))
        else:
            for row in csv.DictReader(text.splitlines()):
                check(row)
    saved = read(public / "preparation.json")
    study = read(ROOT / "configs/study.json")
    matrix = primary_matrix(study)
    assert saved["stage"] == 5 and saved["status"] == "prepared_not_executed"
    assert saved["study_sha256"] == canonical_hash(study)
    assert saved["matrix_sha256"] == canonical_hash(matrix)
    assert saved["stage4_exit_gate_passed"] and saved["frozen_design_checks"] == 31
    assert saved["primary_episodes"] == 36 and saved["baseline_episodes"] == 24
    assert saved["llm_episodes"] == 12 and saved["policy_days"] == 756
    assert saved["primary_llm_decisions"] == 252 and saved["maximum_attempts_including_repairs"] == 504
    assert saved["llm_matrix_indices"] == list(range(2, 36, 3))
    assert saved["new_model_completion_calls"] == saved["new_primary_policy_episodes"] == 0
    assert saved["allowance_amendment_applied"] is saved["paid_primary_authorized"] is False
    assert all(saved[field] is True for field in ("current_template_rejected", "all_primary_episode_ids_available",
        "historical_fallback_reviews_passed", "no_active_execution_lock", "ledger_and_allowance_unchanged"))
    gateway = saved["gateway_check"]
    assert gateway["models_available"] and gateway["frozen_tariffs_match"] and gateway["model_completion_calls"] == 0
    assert gateway["source"] == "https://api.shopaikey.com/pricing"
    assert read(ROOT / "configs/runs/kaggle_primary.template.json") == authorization_template(matrix)
    budget = saved["budget_snapshot"]
    historical = read(ROOT / "docs/results/stage4/preparation.json")["budget_snapshot"]
    for field in ("total_project_attempts", "inclusive_project_exposure_credits", "inclusive_cap_credits",
                  "prior_kaggle_attempts", "prior_kaggle_exposure_credits", "kaggle_scope_cap_credits",
                  "remaining_kaggle_scope_credits", "primary_base_projection_credits",
                  "primary_high_planning_projection_credits", "primary_projected_attempts"):
        assert math.isclose(budget[field], historical[field], rel_tol=1e-12, abs_tol=1e-12), field
    assert budget["pending_attempts"] == budget["blocking_unknown_attempts"] == 0
    assert budget["retained_unknown_attempts"] == 8
    assert math.isclose(budget["retained_unknown_charge_credits"], .059084209)
    high = budget["primary_high_planning_projection_credits"]
    headroom = budget["kaggle_scope_cap_credits"] - budget["prior_kaggle_exposure_credits"]
    assert 0 < budget["primary_base_projection_credits"] <= high < headroom
    assert math.isclose(budget["kaggle_headroom_after_high_projection_credits"], headroom - high, abs_tol=1e-9)
    assert math.isclose(budget["project_exposure_after_high_projection_credits"],
                        budget["inclusive_project_exposure_credits"] + high, abs_tol=1e-9)
    assert budget["total_project_attempts"] + 504 <= budget["global_attempt_ceiling"] == 3000
    assert budget["project_exposure_after_high_projection_credits"] < budget["inclusive_cap_credits"]
    rows = list(csv.DictReader((public / "launch_plan.csv").read_text(encoding="utf-8").splitlines()))
    assert len(rows) == len(matrix["episodes"]) == 36
    for i, (row, episode) in enumerate(zip(rows, matrix["episodes"])):
        assert row["matrix_index"] == str(i) and row["execution_status"] == "not_executed"
        assert row["planned_days"] == "21"
        assert row["store_id"] == episode["series"]["store_id"] and row["product_id"] == episode["series"]["product_id"]
        assert row["scenario"] == episode["scenario"] and row["policy"] == episode["policy"]
        expected = f"& $py scripts/run_kaggle_experiment.py --config configs/study.json --episode-index {i}"
        paid = episode["policy"] == "llm_with_fallback"
        if paid:
            expected += " --execute-paid --budget .cache/approvals/stage5_allowance.approved.json --execution-manifest .cache/approvals/stage5_primary.approved.json"
        assert row["launch_command"] == expected
        checkpoint = "first_llm_review" if i == 2 else ("series_block_review" if i in (11, 23, 35)
                     else ("episode_review" if paid else "baseline_replay"))
        assert row["checkpoint"] == checkpoint
    print("Historical Stage 5 preparation passed: 36 frozen launch commands; original snapshot preserved.")
    if executed:
        check_execution(public, matrix, saved["budget_snapshot"])


if __name__ == "__main__":
    main()
