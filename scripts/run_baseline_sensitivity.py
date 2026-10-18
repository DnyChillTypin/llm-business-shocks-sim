"""Run only the 48 declared free baseline episodes in isolated inputs; reuse 24 primary baselines."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis.robustness import isolated_inputs, validate_baseline
from src.data.kaggle import prepare_dataset
from src.experiments.kaggle import run_episode
from src.experiments.kaggle_protocol import read, write, primary_matrix, episode_evidence_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", type=Path, required=True)
    args = parser.parse_args()
    analysis = args.analysis_dir.resolve()
    assert analysis.is_relative_to(ROOT / "results/analysis")
    study, source = read(ROOT / "configs/study.json"), read(ROOT / "docs/results/stage6/source_snapshot.json")
    assert read(analysis / "approved_plan.json")["approved"] is True
    for name, digest in source["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest
    matrix = primary_matrix(study)
    found = {}
    for p in (ROOT / "results/runs/kaggle_retailbench").glob("*/run_manifest.json"):
        m = read(p)
        if m.get("episode_id") in {e["episode_id"] for e in matrix["episodes"]}:
            assert m["status"] == "validated_complete" and m["episode_id"] not in found
            found[m["episode_id"]] = p.parent
    primary_before = {k: episode_evidence_digest(v) for k, v in found.items()}
    allowance_path = ROOT / ".cache/approvals/stage5_allowance.approved.json"
    allowance = read(allowance_path)
    ledger = ROOT / "results/budgets" / (allowance["budget_id"] + ".sqlite")
    budget_before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (allowance_path, ledger)]
    folder = analysis / "sensitivity"
    folder.mkdir(exist_ok=False)
    summaries, validations = [], []
    # These guards fail if a future accidental code path attempts credentials/client construction.
    with patch("src.benchmarks.common.credentials", side_effect=RuntimeError("Sensitivity forbids gateway access")), \
         patch("openai.OpenAI", side_effect=RuntimeError("Sensitivity forbids API clients")):
        for series in study["kaggle"]["selection"]["selected_series"]:
            label = series["store_id"] + "_" + series["product_id"]
            base = folder / "base_inputs" / label
            prepare_dataset(ROOT / study["dataset"]["path"], base, store_id=series["store_id"],
                product_ids=[series["product_id"]], episode_start=study["kaggle"]["windows"]["primary_evaluation"]["start"])
            assert read(base / "manifest.json")["raw_sha256"] == study["dataset"]["sha256"]
            for elasticity in (1.5, .75, 2.25):
                prepared = base if elasticity == 1.5 else isolated_inputs(base, folder / "inputs" / f"e{elasticity}" / label, elasticity)
                for scenario in study["kaggle"]["scenarios"]:
                    for policy in ("fixed", "adaptive"):
                        e = next(e for e in matrix["episodes"] if e["series"] == series and e["scenario"] == scenario and e["policy"] == policy)
                        reused = elasticity == 1.5
                        if reused:
                            run = found[e["episode_id"]]
                            summary = read(run / "summary.json")
                        else:
                            run = folder / "runs" / f"e{elasticity}" / label / f"{scenario}_{policy}"
                            run.mkdir(parents=True, exist_ok=False)
                            manifest = dict(analysis_kind="baseline_elasticity_sensitivity", primary_evaluation=False,
                                elasticity=elasticity, series=series, scenario=scenario, policy=policy, status="running", model_calls=0)
                            write(run / "run_manifest.json", manifest)
                            try:
                                _, summary = run_episode(prepared, run, scenario=scenario, policy=policy)
                            except BaseException:
                                manifest["status"] = "incomplete"
                                write(run / "run_manifest.json", manifest)
                                raise
                        report = validate_baseline(run, prepared, elasticity=elasticity, scenario=scenario, policy=policy, cache=ROOT / ".cache")
                        if not reused:
                            write(run / "validation.json", report)
                            manifest["status"] = "validated_complete"
                            write(run / "run_manifest.json", manifest)
                        validations.append(report)
                        summaries.append(dict(store_id=series["store_id"], product_id=series["product_id"], scenario=scenario,
                            policy=policy, elasticity=elasticity, provenance="reused_primary" if reused else "new_baseline_sensitivity",
                            **{k: summary[k] for k in ("days", "contribution", "fill_rate", "stockout_sku_days", "mean_closing_inventory")},
                            base_demand_sha256=report["base_demand_sha256"], status=report["status"], model_calls=0))
                print(f"Validated {label}, elasticity {elasticity}: 8 free baseline records.", flush=True)
    assert primary_before == {k: episode_evidence_digest(v) for k, v in found.items()}
    assert budget_before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in (allowance_path, ledger)]
    frame = pd.DataFrame(summaries)
    assert len(frame) == 72 and (frame.provenance == "new_baseline_sensitivity").sum() == 48
    for _, f in frame.groupby(["store_id", "product_id"]):
        assert f.base_demand_sha256.nunique() == 1
    frame.to_csv(folder / "summary.csv", index=False)
    write(folder / "validation.json", dict(status="passed", validated_records=72, new_free_episodes=48,
        reused_primary_baselines=24, new_policy_days=1008, all_72_independent_replays=True,
        primary_evidence_unchanged=True, ledger_and_allowance_unchanged=True, model_calls=0))
    print("All 48 new baseline episodes and 24 reused primary baselines validated; ledger and primary evidence unchanged.")


if __name__ == "__main__":
    main()
