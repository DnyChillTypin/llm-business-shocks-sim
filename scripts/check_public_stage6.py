"""Recompute saved Stage 6 metrics from public action evidence and enforce publication/claim bounds."""
import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check_public_stage2 import check
from src.analysis.metrics import analyze
from src.experiments.kaggle_protocol import read

PUBLIC = ROOT / "docs/results/stage6"
CSV_NAMES = ("episode_metrics", "paired_shock_contrasts", "control_comparisons", "policy_shock_minus_control",
    "per_scenario_summaries", "phase_summaries", "action_traces", "behavioral_response", "recovery",
    "llm_episode_reliability_costs", "baseline_elasticity_summary", "native_task_coverage", "native_reasoning",
    "native_evaluation_usage", "diagnostic_traces", "claim_map")
TEX_NAMES = ("paired_contribution", "scenario_summary", "recovery", "reliability", "native_reasoning")
FIGURES = ("contribution_contrasts", "phase_outcomes", "inventory_traces", "order_traces", "price_traces", "recovery",
    "reliability_costs", "baseline_sensitivity", "diagnostic_examples", "native_coverage_reasoning")
FILES = {"preparation.json", "source_snapshot.json", "native_family_metrics.json", "status.json", "qc_summary.json", "artifact_manifest.json"}
FILES |= {name + ".csv" for name in CSV_NAMES} | {name + ".tex" for name in TEX_NAMES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-pending-visual", action="store_true")
    args = parser.parse_args()
    assert {p.name for p in PUBLIC.iterdir() if p.is_file()} == FILES
    assets = ROOT / "docs/assets/stage6"
    assert {p.name for p in assets.iterdir()} == {name + ext for name in FIGURES for ext in (".png", ".pdf")}
    for p in PUBLIC.iterdir():
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"\b[0-9a-f]{32}\b|\b20\d{6}T\d{12,}Z\b", text), p.name
        if p.suffix == ".json":
            check(json.loads(text))
        elif p.suffix == ".csv":
            for row in csv.DictReader(text.splitlines()):
                check(row)
    manifest = read(PUBLIC / "artifact_manifest.json")
    expected = {p.relative_to(ROOT).as_posix() for p in [*PUBLIC.iterdir(), *assets.iterdir()] if p.name != "artifact_manifest.json"}
    assert set(manifest["files"]) == expected
    for name, value in manifest["files"].items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(PUBLIC) or path.is_relative_to(assets)
        data = path.read_bytes()
        if path.suffix in (".csv", ".json", ".tex"):
            data = data.replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == value, name
    tables = {name: pd.read_csv(PUBLIC / (name + ".csv")) for name in CSV_NAMES}
    plan = read(ROOT / "configs/analysis/stage6.template.json")
    for name, count in plan["expected_output_rows"].items():
        assert len(tables[name]) == count
    rebuilt = analyze(pd.read_csv(ROOT / "docs/results/stage5/daily_results.csv"), tables["action_traces"], pd.read_csv(ROOT / "docs/results/stage5/coverage.csv"))
    for name, expected_frame in rebuilt.items():
        pd.testing.assert_frame_equal(expected_frame, tables[name], check_dtype=False, atol=1e-6, rtol=0)
    native = pd.read_csv(ROOT / "docs/results/stage3/native_coverage.csv")
    usage = pd.read_csv(ROOT / "docs/results/stage3/evaluation_usage.csv")
    pd.testing.assert_frame_equal(native, tables["native_task_coverage"], check_dtype=False)
    pd.testing.assert_frame_equal(usage, tables["native_evaluation_usage"], check_dtype=False)
    reasoning = usage.loc[usage.native_accuracy_unit.notna(), tables["native_reasoning"].columns].reset_index(drop=True)
    pd.testing.assert_frame_equal(reasoning, tables["native_reasoning"], check_dtype=False)
    assert read(PUBLIC / "native_family_metrics.json") == read(ROOT / "docs/results/stage3/family_metrics.json")
    s = tables["baseline_elasticity_summary"]
    assert len(s) == 72 and not s.duplicated(["store_id", "product_id", "scenario", "policy", "elasticity"]).any()
    assert set(s.elasticity) == {.75, 1.5, 2.25} and set(s.policy) == {"fixed", "adaptive"}
    assert (s.status == "validated_complete").all() and (s.model_calls == 0).all() and (s.days == 21).all()
    assert (s.provenance == "new_baseline_sensitivity").sum() == 48
    assert (s.provenance == "reused_primary").sum() == 24
    coverage = pd.read_csv(ROOT / "docs/results/stage5/coverage.csv")
    for _, f in s.groupby(["store_id", "product_id"]):
        assert f.base_demand_sha256.nunique() == 1
    for row in s.loc[s.elasticity == 1.5].itertuples():
        original = coverage.query("store_id == @row.store_id and product_id == @row.product_id and scenario == @row.scenario and policy == @row.policy").iloc[0]
        for column in ("contribution", "fill_rate", "stockout_sku_days", "mean_closing_inventory"):
            assert math.isclose(getattr(row, column), original[column], abs_tol=1e-6, rel_tol=0)
    for _, f in s.loc[s.policy == "fixed"].groupby(["store_id", "product_id", "scenario"]):
        assert f.contribution.max() - f.contribution.min() < 1e-6, "Reference-price fixed demand must be elasticity-invariant."
    costs = tables["llm_episode_reliability_costs"]
    assert (costs.primary_attempts == 21).all() and costs.physical_attempts.sum() == 396
    assert costs.repair_attempts.sum() == 144
    assert math.isclose(costs.cost_credits.sum(), .252123564, abs_tol=1e-9)
    for row in costs.itertuples():
        c = coverage.loc[coverage.matrix_index == row.matrix_index].iloc[0]
        assert row.repair_attempts == c.repair_days and row.physical_attempts == c.successful_cohort_attempts
        assert math.isclose(row.cost_credits, c.successful_cohort_cost_credits, abs_tol=1e-9)
        assert math.isclose(row.primary_cost_credits + row.repair_cost_credits, row.cost_credits, abs_tol=1e-9)
        assert 0 <= row.median_latency_seconds <= row.p95_latency_seconds and row.input_tokens >= 0 and row.output_tokens >= 0
    status, qc = read(PUBLIC / "status.json"), read(PUBLIC / "qc_summary.json")
    assert status["budget_snapshot"] == read(ROOT / "docs/results/stage5/status.json")["budget_snapshot"]
    assert status["new_model_completion_calls"] == qc["new_model_completion_calls"] == 0
    assert status["new_free_baseline_episodes"] == qc["new_free_baseline_episodes"] == 48
    assert qc["automated_tests"] >= 98 and qc["new_metric_and_isolation_tests"] == 13
    assert qc["figure_exports"] == 20 and qc["row_counts"] == {k: len(v) for k, v in tables.items()}
    primary = tables["paired_shock_contrasts"].query("comparator == 'adaptive'")
    findings = status["findings"]
    assert findings["raw_shock_positive"] == int((primary.contribution_difference > 0).sum())
    assert findings["control_adjusted_shock_positive"] == int((primary.control_adjusted_contribution > 0).sum())
    assert findings["recovery_observed_by_policy"] == {p: int(f.recovered.sum()) for p, f in tables["recovery"].groupby("policy")}
    assert findings["recovery_censored"] == int(tables["recovery"].right_censored.sum())
    assert len(tables["claim_map"]) == 9 and set(tables["claim_map"].source_table) <= {k + ".csv" for k in tables}
    if not args.allow_pending_visual:
        assert status["status"] == "complete" and status["exit_gate_passed"] and qc["exit_gate_passed"] and all(qc["checks"].values())
    print("Stage 6 public evidence passed: recomputed matched/phase/recovery/action metrics, 72 sensitivity records, native units, costs, claims and 20 figure hashes.")


if __name__ == "__main__":
    main()
