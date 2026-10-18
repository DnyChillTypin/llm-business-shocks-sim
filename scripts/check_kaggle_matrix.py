"""Run the Stage 4 validation matrix and independent replay, never primary outcomes or paid calls."""
import argparse
import contextlib
import io
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.agents.baselines import run_baseline
from src.data.kaggle import prepare_dataset
from src.experiments.kaggle_fixtures import run_validation_fixture
from src.experiments.kaggle_protocol import read, write
from src.experiments.kaggle_validation import validate_run
from src.research.design import validate_design


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Fresh directory inside results/verification/stage4")
    args = parser.parse_args()
    study = read(ROOT / "configs/study.json")
    validate_design(ROOT)
    output = args.output or ROOT / "results/verification/stage4" / ("matrix_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output = output.resolve()
    if not output.is_relative_to(ROOT / "results/verification/stage4") or output.exists():
        parser.error("Use a fresh validation-only directory inside results/verification/stage4.")
    output.mkdir(parents=True)
    rows, matching = [], defaultdict(lambda: {"initial": set(), "demand": set()})
    for series in study["kaggle"]["selection"]["selected_series"]:
        block = f"{series['store_id']}_{series['product_id']}"
        prepared = output / "inputs" / block
        prepare_dataset(ROOT / study["dataset"]["path"], prepared, store_id=series["store_id"],
            product_ids=[series["product_id"]], episode_start=study["kaggle"]["windows"]["validation_pilot"]["start"])
        for scenario in study["kaggle"]["scenarios"]:
            for policy in ("fixed", "adaptive", "scripted_fixture"):
                run = output / "episodes" / f"{block}_{scenario}_{policy}"
                with contextlib.redirect_stdout(io.StringIO()):
                    frame, summary = run_validation_fixture(study, prepared, run, series, scenario, policy)
                    legacy_match = None
                    if policy != "scripted_fixture":
                        legacy, legacy_summary = run_baseline(prepared, output / "legacy" / f"{block}_{scenario}_{policy}", scenario=scenario, policy=policy)
                        pd.testing.assert_frame_equal(legacy, frame[legacy.columns])
                        assert all(summary[k] == v for k, v in legacy_summary.items())
                        legacy_match = True
                    validation = validate_run(run)
                write(run / "validation.json", validation)
                if validation["status"] != "validated_complete":
                    write(output / "failed_validation.json", validation)
                    raise RuntimeError("Validation fixture failed; inspect local failed checks before proceeding.")
                manifest = read(run / "run_manifest.json")
                manifest["status"] = "validated_complete"
                write(run / "run_manifest.json", manifest)
                matching[block]["initial"].add(validation["initial_observation_sha256"])
                matching[block]["demand"].add(validation["base_demand_sha256"])
                rows.append({"store_id": series["store_id"], "product_id": series["product_id"], "scenario": scenario,
                    "policy": policy, "agent_kind": manifest["agent_kind"], "days": summary["days"],
                    "status": validation["status"], "checks_passed": len(validation["checks"]),
                    "legacy_baseline_parity": legacy_match, "scripted_repair_days": summary["repair_days"],
                    "scripted_fallback_days": summary["fallback_days"], "model_completion_calls": 0})
            print(f"Validated {block}, {scenario}: baseline parity, fixture flags, independent replay and privacy checks.", flush=True)
    assert len(rows) == 36 and sum(r["days"] for r in rows) == 756
    assert all(len(m["initial"]) == len(m["demand"]) == 1 for m in matching.values())
    scripted = [r for r in rows if r["agent_kind"] == "scripted"]
    assert len(scripted) == 12 and all(r["scripted_repair_days"] == 2 and r["scripted_fallback_days"] == 1 for r in scripted)
    report = {"status": "passed", "validation_window": study["kaggle"]["windows"]["validation_pilot"],
        "episodes": 36, "policy_days": 756, "baseline_episodes": 24, "scripted_episodes": 12,
        "legacy_baseline_parity_episodes": 24, "matched_series_blocks": 3,
        "initial_conditions_matched": True, "exogenous_base_demand_matched": True,
        "independent_replay_episodes": 36, "model_completion_calls": 0, "primary_policy_episodes": 0,
        "scripted_repairs_and_fallbacks_are_fixture_events": True, "coverage": rows,
        "qualification": "Validation-only software evidence; scripted decisions are not genuine LLM performance results."}
    write(output / "matrix_validation.json", report)
    write(ROOT / "results/verification/stage4/latest_matrix.json", {"folder": str(output)})
    print(json.dumps({k: v for k, v in report.items() if k != "coverage"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
