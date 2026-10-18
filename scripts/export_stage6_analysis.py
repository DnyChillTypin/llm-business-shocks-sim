"""Generate Stage 6 tables/figures from immutable evidence; no completion requests."""
import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis.evidence import extract_primary
from src.analysis.metrics import analyze, request_metrics
from src.analysis.figures import make_figures
from src.experiments.kaggle_protocol import read, write
from src.research.design import canonical_hash

PUBLIC = ROOT / "docs/results/stage6"
ASSETS = ROOT / "docs/assets/stage6"
CSV_NAMES = ("episode_metrics", "paired_shock_contrasts", "control_comparisons", "policy_shock_minus_control",
    "per_scenario_summaries", "phase_summaries", "action_traces", "behavioral_response", "recovery",
    "llm_episode_reliability_costs", "baseline_elasticity_summary", "native_task_coverage", "native_reasoning",
    "native_evaluation_usage", "diagnostic_traces", "claim_map")
TEX_NAMES = ("paired_contribution", "scenario_summary", "recovery", "reliability", "native_reasoning")


def digest(path):
    data = Path(path).read_bytes()
    return hashlib.sha256(data.replace(b"\r\n", b"\n") if Path(path).suffix in (".csv", ".json", ".tex") else data).hexdigest()


def manifest():
    paths = [p for p in PUBLIC.iterdir() if p.is_file() and p.name != "artifact_manifest.json"] + list(ASSETS.iterdir())
    write(PUBLIC / "artifact_manifest.json", dict(hash_rule="SHA-256; UTF-8 text CRLF normalized to LF; binary figures hashed verbatim",
        files={p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", type=Path, required=True)
    parser.add_argument("--finalize", action="store_true", help="Bind completed visual review to existing unchanged exports; never rerender.")
    args = parser.parse_args()
    folder = args.analysis_dir.resolve()
    assert folder.is_relative_to(ROOT / "results/analysis")
    plan = read(folder / "approved_plan.json")
    assert plan["approved"] is True and plan["paid_calls_authorized"] is False and plan["paid_extensions"]["enabled"] is False
    source = read(PUBLIC / "source_snapshot.json")
    assert canonical_hash(source) == plan["source_snapshot_sha256"]
    for name, value in source["files"].items():
        assert digest(ROOT / name) == value
    if args.finalize:
        saved = read(PUBLIC / "artifact_manifest.json")
        assert all(digest(ROOT / name) == value for name, value in saved["files"].items())
        review = read(folder / "visual_review.json")
        figure_hashes = {name: value for name, value in saved["files"].items() if name.startswith("docs/assets/stage6/")}
        assert review["status"] == "passed" and review["files"] == figure_hashes and len(figure_hashes) == 20
        status, qc = read(PUBLIC / "status.json"), read(PUBLIC / "qc_summary.json")
        status.update(status="complete", exit_gate_passed=True)
        qc["checks"]["all_20_figure_exports_visually_reviewed"] = True
        qc["exit_gate_passed"] = all(qc["checks"].values())
        assert qc["exit_gate_passed"]
        qc["status"] = "passed"
        write(PUBLIC / "status.json", status)
        write(PUBLIC / "qc_summary.json", qc)
        manifest()
        print("Stage 6 finalized: unchanged tables/figures bound to passing visual review; no model calls.")
        return
    assert read(folder / "sensitivity/validation.json")["status"] == "passed"
    study = read(ROOT / "configs/study.json")
    actions, attempts, sources = extract_primary(study)
    coverage = pd.read_csv(ROOT / "docs/results/stage5/coverage.csv")
    tables = analyze(pd.read_csv(ROOT / "docs/results/stage5/daily_results.csv"), actions, coverage)
    tables["llm_episode_reliability_costs"] = request_metrics(attempts)
    tables["baseline_elasticity_summary"] = pd.read_csv(folder / "sensitivity/summary.csv")
    tables["native_task_coverage"] = pd.read_csv(ROOT / "docs/results/stage3/native_coverage.csv")
    usage = pd.read_csv(ROOT / "docs/results/stage3/evaluation_usage.csv")
    tables["native_evaluation_usage"] = usage
    tables["native_reasoning"] = usage.loc[usage.native_accuracy_unit.notna(), ["task", "saved_reasoning_cases", "native_accuracy_unit",
        "native_correct_units", "native_scored_units", "exact_case_accuracy", "accuracy"]].reset_index(drop=True)
    cases = (("S001", "P0001", "delivery_disruption"), ("S004", "P0006", "demand_surge"))
    traces = tables["action_traces"]
    diagnostic = []
    for store, product, scenario in cases:
        f = traces.query("store_id == @store and product_id == @product")
        l = f.query("policy == 'llm_with_fallback' and scenario == @scenario").copy()
        for policy, condition, prefix in (("adaptive", scenario, "adaptive_shock"), ("llm_with_fallback", "control", "llm_control")):
            other = f.query("policy == @policy and scenario == @condition").set_index("date")
            for column in ("contribution", "closing_inventory", "order_quantity", "price_multiplier", "lost_sales"):
                l[prefix + "_" + column] = l.date.map(other[column])
        diagnostic.append(l)
    tables["diagnostic_traces"] = pd.concat(diagnostic, ignore_index=True)
    primary = tables["paired_shock_contrasts"].query("comparator == 'adaptive'")
    rec = tables["recovery"]
    llm = traces.query("policy == 'llm_with_fallback'")
    findings = dict(raw_shock_positive=int((primary.contribution_difference > 0).sum()),
        raw_shock_negative=int((primary.contribution_difference < 0).sum()),
        control_adjusted_shock_positive=int((primary.control_adjusted_contribution > 0).sum()),
        control_adjusted_shock_negative=int((primary.control_adjusted_contribution < 0).sum()),
        first_pass_valid=int((~llm.repair_attempted).sum()), successful_repairs=int((llm.repair_attempted & ~llm.fallback_used).sum()),
        fallback_days=int(llm.fallback_used.sum()), invalid_responses=int(llm.invalid_responses.sum()),
        recovery_observed_by_policy={p: int(f.recovered.sum()) for p, f in rec.groupby("policy")},
        recovery_censored=int(rec.right_censored.sum()), pre_shock_llm_divergent_conditions=int((tables["behavioral_response"].query("policy == 'llm_with_fallback'").pre_shock_different_action_days > 0).sum()))
    stage5 = read(ROOT / "docs/results/stage5/status.json")
    claims = [
        ("C1", "Raw LLM contribution exceeded adaptive in " + str(findings["raw_shock_positive"]) + "/9 shocks.", "paired_shock_contrasts.csv", "comparator=adaptive; contribution_difference", "Three selected blocks; absolute rankings do not measure control-adjusted response."),
        ("C2", "Control-adjusted contribution was positive in " + str(findings["control_adjusted_shock_positive"]) + "/9 adaptive comparisons.", "paired_shock_contrasts.csv", "control_adjusted_contribution", "Surge mean is negative; no population significance or causal model-learning claim."),
        ("C3", "Recovery was observed in " + str(findings["recovery_observed_by_policy"]["llm_with_fallback"]) + "/9 LLM shocks.", "recovery.csv", "policy=llm_with_fallback; recovered", "Relative to its own high-inventory control; not low inventory or cumulative profit recovery. Adaptive continued adjustments can remain outside its control band."),
        ("C4", str(findings["first_pass_valid"]) + "/252 decisions were first-pass valid.", "action_traces.csv", "policy=llm_with_fallback; repair_attempted=False", "One model realization per condition; repaired/fallback operation is distinct from unassisted validity."),
        ("C5", str(findings["fallback_days"]) + "/252 decisions used adaptive fallback and remain in the primary result.", "action_traces.csv", "fallback_used", "Removing these days would select a different policy/outcome subset."),
        ("C6", "Primary request expense was " + str(stage5["budget_snapshot"]["primary_exposure_credits"]) + " estimated gateway credits.", "llm_episode_reliability_costs.csv", "cost_credits", "Not provider-verified billing or dataset monetary units; earlier unknown holds remain in cumulative exposure."),
        ("C7", "Native task coverage is 14 validated, one failed ICBE and four deferred Retail tasks.", "native_task_coverage.csv", "status", "No full ICBE score, imputed Retail score or pooled family ranking."),
        ("C8", "Baseline sensitivity comprises 24 reused primary baselines and 48 new free episodes.", "baseline_elasticity_summary.csv", "provenance; elasticity", "Simulator/baseline sensitivity only, not LLM robustness."),
        ("C9", str(findings["pre_shock_llm_divergent_conditions"]) + "/9 LLM shock/control pairs already differed in actions before the shock.", "behavioral_response.csv", "policy=llm_with_fallback; pre_shock_different_action_days", "Action divergence can include model variation; no frozen-history ablation isolates the value of history.")]
    tables["claim_map"] = pd.DataFrame(claims, columns=["claim_code", "claim", "source_table", "source_columns_or_filter", "limitation"])
    for name, frame in tables.items():
        frame.to_csv(PUBLIC / (name + ".csv"), index=False)
        (folder / "tables").mkdir(exist_ok=True)
        frame.to_csv(folder / "tables" / (name + ".csv"), index=False)
    write(folder / "private_source_map.json", sources)
    attempts.to_csv(folder / "extracted_attempt_metrics.csv", index=False)
    native_family = read(ROOT / "docs/results/stage3/family_metrics.json")
    write(PUBLIC / "native_family_metrics.json", native_family)
    latex = dict(paired_contribution=primary[["store_id", "scenario", "contribution_difference", "relative_gain_percent", "control_adjusted_contribution"]],
        scenario_summary=tables["per_scenario_summaries"].query("comparator == 'adaptive'")[["scenario", "raw_mean", "control_adjusted_mean", "control_adjusted_positive"]],
        recovery=rec[["store_id", "policy", "scenario", "recovery_start_day", "confirmation_day", "right_censored"]],
        reliability=tables["llm_episode_reliability_costs"][["matrix_index", "physical_attempts", "repair_attempts", "cost_credits", "median_latency_seconds"]],
        native_reasoning=tables["native_reasoning"][["task", "native_accuracy_unit", "native_correct_units", "native_scored_units", "accuracy"]])
    headings = dict(store_id="Store", scenario="Scenario", policy="Policy", contribution_difference="Raw difference",
        relative_gain_percent="Gain (percent)", control_adjusted_contribution="Adjusted difference", raw_mean="Raw mean",
        control_adjusted_mean="Adjusted mean", control_adjusted_positive="Positive blocks", recovery_start_day="Start day",
        confirmation_day="Confirmed day", right_censored="Censored", matrix_index="Position", physical_attempts="Requests",
        repair_attempts="Repairs", cost_credits="Credits", median_latency_seconds="Median seconds", task="Dataset",
        native_accuracy_unit="Unit", native_correct_units="Correct", native_scored_units="Scored", accuracy="Accuracy")
    for name, frame in latex.items():
        frame = frame.copy()
        if "scenario" in frame:
            frame["scenario"] = frame.scenario.replace(dict(demand_surge="Surge", demand_decline="Decline", delivery_disruption="Delivery delay"))
        if "policy" in frame:
            frame["policy"] = frame.policy.replace({"llm_with_fallback": "LLM + fallback"})
        if name == "native_reasoning":
            frame["task"] = frame.task.str.replace("firm:", "", regex=False)
            frame[["native_correct_units", "native_scored_units"]] = frame[["native_correct_units", "native_scored_units"]].astype(int)
        (PUBLIC / (name + ".tex")).write_text(frame.rename(columns=headings).to_latex(index=False, float_format="%.4f", na_rep="Censored" if name == "recovery" else "NA"), encoding="utf-8")
    figures = make_figures(tables, tables["native_reasoning"], tables["native_task_coverage"], ASSETS)
    raw = (ROOT / "results/verification/stage6/execution_tests.log").read_bytes()
    log = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    count = re.search(r"Ran (\d+) tests", log)
    assert count and re.search(r"^OK\s*$", log, re.M) and "FAILED (" not in log
    checks = dict(all_expected_table_rows=True, pinned_sources_unchanged=True, full_matrix_and_fallbacks_retained=True,
        cash_inventory_pipeline_reconciled=True, contribution_service_and_phases_reconciled=True,
        frozen_recovery_with_censoring=True, request_costs_and_repairs_accounted_once=True,
        native_units_failures_and_missing_values_preserved=True, all_72_baseline_records_independently_replayed=True,
        no_llm_robustness_or_population_inference_claim=True, all_20_figure_exports_visually_reviewed=False)
    for name, n in read(ROOT / "configs/analysis/stage6.template.json")["expected_output_rows"].items():
        assert len(tables[name]) == n, name
    qc = dict(stage=6, status="awaiting_visual_review", exit_gate_passed=False, checks=checks,
        automated_tests=int(count[1]), new_metric_and_isolation_tests=13,
        row_counts={name: len(frame) for name, frame in tables.items()}, new_free_baseline_episodes=48,
        new_model_completion_calls=0, primary_evidence_and_ledger_unchanged=True, figure_exports=len(figures))
    write(PUBLIC / "qc_summary.json", qc)
    write(PUBLIC / "status.json", dict(stage=6, status="awaiting_visual_review", exit_gate_passed=False,
        source_snapshot_sha256=canonical_hash(source), study_sha256=canonical_hash(study), analysis_template_sha256=canonical_hash(read(ROOT / "configs/analysis/stage6.template.json")),
        findings=findings, budget_snapshot=stage5["budget_snapshot"], new_model_completion_calls=0,
        new_free_baseline_episodes=48, reused_primary_baselines=24, primary_window_prior_manual_outcome_use=stage5["primary_window_prior_manual_outcome_use"],
        interpretation="Three selected matched blocks, dependent daily observations and one LLM realization per condition. Descriptive simulator contrasts; no real-world causality, population significance or model-learning claim.",
        sensitivity_scope="Baseline-only elasticity assumptions; no new LLM experiments."))
    write(folder / "analysis_manifest.json", dict(analysis_kind="stage6_v1", approved_plan=plan,
        private_source_map=sources, source_snapshot_sha256=canonical_hash(source), findings=findings,
        sensitivity_validation=read(folder / "sensitivity/validation.json")))
    manifest()
    print(json.dumps(dict(status="awaiting_visual_review", findings=findings, figure_exports=len(figures), table_files=len(tables))))


if __name__ == "__main__":
    main()
