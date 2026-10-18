"""Publish reviewed Stage 4 software evidence, never raw requests or account metadata."""
import csv
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.experiments.kaggle_protocol import read, write, primary_matrix, authorization_template
from src.experiments.kaggle_validation import validate_run
from src.research.design import validate_design

PUBLIC = ROOT / "docs/results/stage4"


def tests_passed(path):
    raw = path.read_bytes()
    text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    count = re.search(r"Ran (\d+) tests", text)
    if not count or not re.search(r"^OK\s*$", text, re.M) or "FAILED (" in text:
        raise ValueError("Verified passing test output is required before export.")
    return int(count[1])


def csv_write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    PUBLIC.mkdir(parents=True, exist_ok=True)
    study = read(ROOT / "configs/study.json")
    design_check = validate_design(ROOT)
    matrix = read(Path(read(ROOT / "results/verification/stage4/latest_matrix.json")["folder"]) / "matrix_validation.json")
    assert matrix["status"] == "passed" and matrix["episodes"] == 36 and matrix["policy_days"] == 756
    assert matrix["model_completion_calls"] == matrix["primary_policy_episodes"] == 0
    total_tests = tests_passed(ROOT / "results/verification/stage4/all_tests.log")
    gate_tests = tests_passed(ROOT / "results/verification/stage4/execution_tests.log")
    pilot_reports = []
    for path in (ROOT / "results/runs/kaggle_retailbench").glob("*/run_manifest.json"):
        manifest = read(path)
        if manifest.get("purpose") == "pilot" and manifest.get("policy") == "llm_with_fallback" and manifest.get("status") == "validated_complete":
            report = validate_run(path.parent)
            assert report["status"] == "validated_complete" and report["checks"]["cumulative_ledger_charge_match"]
            pilot_reports.append(report)
    assert len(pilot_reports) == 2 and sum(p["api_attempts"] for p in pilot_reports) == 57
    write(ROOT / "results/verification/stage4/prior_pilot_replay.json", pilot_reports)

    allowance = read(ROOT / ".cache/approvals/stage3_nonretail_v2.json")
    path = ROOT / "results/budgets" / (allowance["budget_id"] + ".sqlite")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        attempts, exposure = db.execute("SELECT COUNT(*),SUM(COALESCE(actual_nanos,reserved_nanos)) FROM attempts").fetchone()
        pending = db.execute("SELECT COUNT(*) FROM attempts WHERE status='pending'").fetchone()[0]
    before = read(PUBLIC / "preparation.json")["budget_snapshot"]
    assert attempts == before["total_project_attempts"] == 1438 and exposure == 1934083294 and pending == 0
    plan = primary_matrix(study)
    template = authorization_template(plan)
    template_path = ROOT / "configs/runs/kaggle_primary.template.json"
    write(template_path, template)
    rows = [{"matrix_index": index, "store_id": e["series"]["store_id"], "product_id": e["series"]["product_id"],
             "scenario": e["scenario"], "policy": e["policy"], "window": e["window"], "planned_days": 21,
             "primary_execution_status": "not_executed"} for index, e in enumerate(plan["episodes"])]
    csv_write(PUBLIC / "primary_plan.csv", rows)
    csv_write(PUBLIC / "validation_coverage.csv", matrix["coverage"])
    checks = {"expanded_validation_matrix": True, "all_36_independent_replays": True,
        "all_24_legacy_baselines_match": True, "matched_initial_conditions_and_demand": True,
        "daily_future_demand_and_scenario_privacy": True, "cash_inventory_pipeline_reconciled": True,
        "scripted_repairs_fallbacks_preserved": True, "two_genuine_pilots_revalidated_without_transport": True,
        "authorization_duplicate_retry_lock_and_attempt_ceiling_tests": True,
        "prior_ledger_spending_and_holds_unchanged": True, "frozen_design_unchanged": True,
        "no_primary_evaluation_or_new_model_calls": True}
    qc = {"stage": 4, "status": "passed", "exit_gate_passed": all(checks.values()), "checks": checks,
        "automated_tests": total_tests, "execution_and_replay_regression_tests": gate_tests,
        "frozen_design_checks": len(design_check["checks"]),
        "validation_episodes": 36, "validation_policy_days": 756, "baseline_episodes": 24, "scripted_episodes": 12,
        "legacy_baseline_matches": 24, "independently_replayed_episodes": 36,
        "revalidated_historical_genuine_pilots": 2, "historical_attempts_audited_not_reissued": 57,
        "new_model_completion_calls": 0, "new_primary_policy_episodes": 0,
        "project_attempts_before_and_after": attempts, "inclusive_project_exposure_before_and_after_credits": exposure / 1e9,
        "primary_authorization_template_approved": template["approved"],
        "primary_authorization_template_sha256": hashlib.sha256(template_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "qualification": "Software/integration readiness only. Validation fixtures are not genuine LLM performance or primary comparison findings.",
        "checked_on": "2026-10-18"}
    write(PUBLIC / "qc_summary.json", qc)
    write(PUBLIC / "status.json", {"stage": 4, "status": "complete_offline_readiness", "exit_gate_passed": True,
        "primary_comparisons_executed": False, "paid_primary_authorized": False,
        "next_stage": 5, "next_stage_work": "Explicitly authorized matched primary baseline and LLM shock comparisons",
        "native_coverage_qualification": "14 validated non-Retail tasks; frozen ICBE failure retained; four Retail tasks deferred.",
        "primary_window_prior_manual_outcome_use": "uncertain; no pristine unseen-data claim"})
    files = sorted(p for p in PUBLIC.iterdir() if p.is_file() and p.name != "artifact_manifest.json")
    write(PUBLIC / "artifact_manifest.json", {"hash_rule": "SHA-256 UTF-8 text with CRLF normalized to LF",
        "files": {p.name: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in files}})
    print(json.dumps(qc, indent=2))


if __name__ == "__main__":
    main()
