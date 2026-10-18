"""Validate the aggregate-only Stage 5 preparation plan; no model or episode runs."""
import csv
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


def main():
    public = ROOT / "docs/results/stage5"
    assert {p.name for p in public.iterdir() if p.is_file()} == {"preparation.json", "launch_plan.csv"}
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
    print("Stage 5 preparation passed: 36 frozen launch commands, unchanged budget snapshot, no primary execution or authorization.")


if __name__ == "__main__":
    main()
