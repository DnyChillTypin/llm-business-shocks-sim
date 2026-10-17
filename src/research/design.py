"""Reconstruct the frozen design without running policies or constructing API clients."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import math
import random
from pathlib import Path

import pandas as pd

from src.benchmarks.common import TASKS


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def text_hash(path: Path) -> str:
    """Hash tracked text consistently across LF and CRLF checkouts."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def training_selection(frame: pd.DataFrame, train_fraction: float,
                       quantiles: list[float]) -> tuple[dict, list[dict]]:
    dates = pd.DatetimeIndex(frame["Date"].unique()).sort_values()
    count = int(len(dates) * train_fraction)
    if not 1 < count < len(dates):
        raise ValueError("Training split must contain at least two dates and leave held-out dates.")
    train_end = dates[count - 1]
    train = frame.loc[frame["Date"] <= train_end]
    stats = train.groupby(["Store ID", "Product ID"])["Demand"].agg(["mean", "std"])
    stats = stats.loc[stats["mean"] > 0].copy()
    stats["cv"] = stats["std"] / stats["mean"]
    if not stats["cv"].map(math.isfinite).all():
        raise ValueError("Training variability must be finite.")
    ranked = stats.reset_index().sort_values(["cv", "Store ID", "Product ID"]).reset_index(drop=True)
    selected = []
    for q in quantiles:
        if not 0 <= q < 1:
            raise ValueError("Selection quantiles must lie in [0, 1).")
        index = math.floor(len(ranked) * q)
        row = ranked.iloc[index]
        selected.append({"store_id": row["Store ID"], "product_id": row["Product ID"],
                         "quantile": q, "rank_zero_based": index,
                         "training_mean_demand": round(float(row["mean"]), 12),
                         "training_cv": round(float(row["cv"]), 12)})
    if len({(s["store_id"], s["product_id"]) for s in selected}) != len(selected):
        raise ValueError("Selection produced duplicate series.")
    return {"train_end": train_end.date().isoformat(), "training_dates": count,
            "eligible_series": len(ranked)}, selected


def csv_text(rows: list[dict]) -> str:
    if not rows:
        raise ValueError("Coverage cannot be empty.")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def load_native_file(root: Path, relative: str, name: str):
    # These data loaders use standard-library imports only. Do not import agents
    # or ICBE's module-level API client during design checks.
    spec = importlib.util.spec_from_file_location(name, root / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def native_case_manifest(root: Path, benchmark: dict) -> list[dict]:
    firm = root / "vendor/FirmBench"
    config_path = firm / "StructuredReasoning/data/aoa_sampled_test/task_config_aoa_sampled_test_50.json"
    task_config = json.loads(config_path.read_text(encoding="utf-8"))
    result = []
    for task in TASKS:
        name = task.split(":")[-1]
        if not task.startswith("firm:") or name in ("consulting", "beergame", "edt"):
            continue
        source = firm / task_config[name]["test_data"]
        source_hash = text_hash(source)
        rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
        for index, row in enumerate(rows):
            result.append({"task": task, "case_id": f"{name}:row_{index:04d}",
                           "source_path": source.relative_to(root).as_posix(),
                           "source_text_sha256": source_hash, "source_index_zero_based": index,
                           "case_content_sha256": canonical_hash(row), "selection_order": index})
    source = firm / "Consulting/agsm_cases_all.json"
    loader = load_native_file(root, "vendor/FirmBench/Consulting/run.py", "design_consulting_loader")
    cases = loader.load_consulting_cases(str(source))
    selected = random.Random(benchmark["seed"]).sample(cases, benchmark["consulting_cases"])
    for order, case in enumerate(selected):
        result.append({"task": "firm:consulting", "case_id": case["case_id"],
                       "source_path": source.relative_to(root).as_posix(),
                       "source_text_sha256": text_hash(source),
                       "source_index_zero_based": cases.index(case),
                       "case_content_sha256": canonical_hash(case), "selection_order": order})
    return result


def native_episode_manifest(root: Path, benchmark: dict) -> dict:
    beer = load_native_file(root, "vendor/FirmBench/SeriousGame/beergame_data_processor.py", "design_beer_loader")
    edt = load_native_file(root, "vendor/FirmBench/SeriousGame/edt_data_processor.py", "design_edt_loader")
    return {
        "retail": [{"configuration": task.split(":")[1], "days": benchmark["retail_days"]}
                   for task in TASKS if task.startswith("retail:")],
        "beergame": beer.BeerGameDataProcessor.load_scenarios(None),
        "edt": edt.EDTDataProcessor.load_scenarios(None),
        "icbe": [{"match_id": f"ordered_pair_{i:02d}", "model_a": a, "model_b": b,
                  "rounds": benchmark["icbe_rounds"], "primary_decisions": 2 * benchmark["icbe_rounds"]}
                 for i, (a, b) in enumerate((a, b) for a in benchmark["icbe_models"]
                                           for b in benchmark["icbe_models"] if a != b)],
    }


def kaggle_episode_plan(study: dict) -> list[dict]:
    kaggle = study["kaggle"]
    window = kaggle["windows"]["primary_evaluation"]
    result = []
    for series in kaggle["selection"]["selected_series"]:
        block = f"{study['study_id']}:{series['store_id']}:{series['product_id']}:primary"
        for scenario in kaggle["scenarios"]:
            for policy in kaggle["policy_ids"]:
                result.append({"episode_id": f"{block}:{scenario}:{policy}", "block_id": block,
                               "store_id": series["store_id"], "product_id": series["product_id"],
                               "window": "primary_evaluation", "start_date": window["start"],
                               "end_date": window["end"], "scenario": scenario, "policy": policy,
                               "horizon_days": kaggle["horizon_days"], "replicate": 0,
                               "planned_status": "planned", "result_available": False})
    return result


def coverage_plan(study: dict, cases: list[dict], episodes: dict) -> list[dict]:
    result = []
    for task in TASKS:
        count = sum(row["task"] == task for row in cases)
        horizon, unit, method, classification = "", "case", "native_cot", "native_logic_model_substitution"
        if task.startswith("retail:"):
            count, horizon, unit, method = 1, study["native"]["settings"]["retail_days"], "episode_days", "native_react"
            classification = "native_logic_compatibility_model_substitution"
        elif task == "firm:beergame":
            count, horizon, unit = len(episodes["beergame"]), 25, "episode_weeks"
        elif task == "firm:edt":
            count, horizon, unit = len(episodes["edt"]), 96, "scenario_abm_steps"
            classification = "scenario_level_abm_compatibility_model_substitution"
        elif task == "icbe":
            count, horizon, unit, method = len(episodes["icbe"]), 100, "ordered_match_rounds", "native_game_prompts"
            classification = "native_logic_failure_handling_model_substitution"
        elif task == "firm:factset":
            classification = "local_factset_extension_model_substitution"
        elif task == "firm:FormulaEval":
            classification = "native_scorer_windows_execution_compatibility_model_substitution"
        result.append({"track": "native", "unit_id": task, "planned_units": count,
                       "horizon": horizon, "unit_type": unit, "method": method,
                       "classification": classification, "status": "planned", "completed_units": 0})
    for row in kaggle_episode_plan(study):
        result.append({"track": "kaggle", "unit_id": row["episode_id"], "planned_units": 1,
                       "horizon": row["horizon_days"], "unit_type": "single_sku_episode_days",
                       "method": row["policy"], "classification": "kaggle_retailbench_adaptation",
                       "status": "planned", "completed_units": 0})
    return result


def validate_design(root: Path) -> dict:
    """Check frozen artifacts against the actual data and pinned native inputs."""
    from datetime import datetime, timezone
    from src.benchmarks.common import verify_sources
    from src.data.kaggle import load_sales

    checks = []

    def expect(name, condition):
        if not condition:
            raise ValueError(f"Research design check failed: {name}")
        checks.append({"check": name, "status": "passed"})

    study = json.loads((root / "configs/study.json").read_text(encoding="utf-8"))
    frozen = json.loads((root / "docs/results/study_design_manifest.json").read_text(encoding="utf-8"))
    expect("frozen_text_artifacts", all(text_hash(root / path) == digest
                                         for path, digest in frozen["artifact_text_sha256"].items()))
    expect("frozen_native_loader_text", all(text_hash(root / path) == digest
                                           for path, digest in frozen["native_loader_text_sha256"].items()))
    verify_sources()
    expect("pinned_native_sources", True)
    raw = root / study["dataset"]["path"]
    expect("raw_dataset_checksum", hashlib.sha256(raw.read_bytes()).hexdigest() == study["dataset"]["sha256"])
    frame = load_sales(raw)
    expect("dataset_dimensions", len(frame) == 76000 and frame.groupby(["Store ID", "Product ID"]).ngroups == 100)
    kaggle = study["kaggle"]
    split = kaggle["splits"]
    info, selected = training_selection(frame, split["train_fraction"], kaggle["selection"]["quantiles"])
    expect("training_boundary", info["train_end"] == split["train_end"] and info["training_dates"] == 456)
    keys = ("store_id", "product_id", "rank_zero_based", "quantile")
    expected_selection = kaggle["selection"]["selected_series"]
    expect("training_only_series_ids", len(selected) == len(expected_selection) == 3 and all(
        all(a[k] == b[k] for k in keys) for a, b in zip(selected, expected_selection)))
    expect("training_calibration_values", all(
        math.isclose(a[k], b[k], rel_tol=0, abs_tol=1e-9)
        for a, b in zip(selected, expected_selection) for k in ("training_mean_demand", "training_cv")))
    changed = frame.copy()
    future = changed["Date"] > pd.Timestamp(split["train_end"])
    changed.loc[future, ["Demand", "Price", "Inventory Level", "Units Sold", "Units Ordered"]] = 999999
    _, perturbed = training_selection(changed, split["train_fraction"], kaggle["selection"]["quantiles"])
    expect("future_values_do_not_change_selection", perturbed == selected)
    dates = pd.DatetimeIndex(frame["Date"].unique()).sort_values()
    test_index = info["training_dates"] + int(len(dates) * split["validation_fraction"])
    expect("chronological_split_dates", [dates[0].date().isoformat(), dates[456].date().isoformat(),
        dates[test_index - 1].date().isoformat(), dates[test_index].date().isoformat(), dates[-1].date().isoformat()]
        == [split["train_start"], split["validation_start"], split["validation_end"], split["test_start"], split["test_end"]])
    for name, window in kaggle["windows"].items():
        start, end = pd.Timestamp(window["start"]), pd.Timestamp(window["end"])
        expect(f"window_{name}_duration", (end - start).days + 1 == kaggle["horizon_days"])
        lower, upper = ((split["validation_start"], split["validation_end"]) if name == "validation_pilot"
                        else (split["test_start"], split["test_end"]))
        expect(f"window_{name}_split", pd.Timestamp(lower) <= start <= end <= pd.Timestamp(upper))
    windows = kaggle["windows"]
    expect("evaluation_after_exploratory_window", windows["primary_evaluation"]["start"] > windows["exploratory_existing"]["end"])
    expect("prior_use_uncertainty_disclosed", windows["primary_evaluation"]["prior_manual_outcome_use"].startswith("uncertain")
           and windows["primary_evaluation"]["pristine_unseen_claim_allowed"] is False)
    actual = json.loads((root / kaggle["settings_path"]).read_text(encoding="utf-8"))
    expect("environment_assumptions_match", all(actual[k] == v for k, v in kaggle["assumptions"].items())
           and actual["horizon"] == kaggle["horizon_days"] and actual["train_fraction"] == split["train_fraction"]
           and actual["validation_fraction"] == split["validation_fraction"])
    benchmark = json.loads((root / study["native"]["settings_path"]).read_text(encoding="utf-8"))
    expect("native_settings_match", all(benchmark[k] == v for k, v in study["native"]["settings"].items()))
    cases = native_case_manifest(root, benchmark)
    expect("native_case_ids_and_hashes", csv_text(cases) == (root / "docs/results/native_case_manifest.csv").read_text(encoding="utf-8"))
    reasoning = [c for c in cases if c["task"] != "firm:consulting"]
    expect("reasoning_counts_and_factset_separation", len(reasoning) == 507 and
           sum(c["task"] == "firm:factset" for c in reasoning) == 50)
    expect("consulting_selection_order", [c["case_id"] for c in cases if c["task"] == "firm:consulting"]
           == study["native"]["consulting_case_ids_in_run_order"])
    episodes = native_episode_manifest(root, benchmark)
    expect("native_episode_configs", episodes == json.loads((root / "docs/results/native_episode_manifest.json").read_text(encoding="utf-8")))
    expect("native_full_horizons", len(episodes["retail"]) == 4 and all(e["days"] == 180 for e in episodes["retail"])
           and len(episodes["beergame"]) == 2 and all(e["config"]["horizon_weeks"] == 25 for e in episodes["beergame"])
           and len(episodes["edt"]) == 1 and episodes["edt"][0]["config"]["max_steps"] == 96
           and len(episodes["icbe"]) == 6 and sum(e["primary_decisions"] for e in episodes["icbe"]) == 1200)
    plan = kaggle_episode_plan(study)
    expect("kaggle_episode_plan", csv_text(plan) == (root / "docs/results/kaggle_episode_plan.csv").read_text(encoding="utf-8"))
    llm = [e for e in plan if e["policy"] == "llm_with_fallback"]
    expect("matched_matrix_counts", len(plan) == 36 and len({e["episode_id"] for e in plan}) == 36
           and len({e["block_id"] for e in plan}) == 3 and sum(e["horizon_days"] for e in plan) == 756
           and len(llm) == 12 and sum(e["horizon_days"] for e in llm) == 252)
    expect("coverage_has_no_research_results", csv_text(coverage_plan(study, cases, episodes)) ==
           (root / "docs/results/planned_coverage.csv").read_text(encoding="utf-8"))
    expect("no_paid_authorization_in_design", study["spending"]["paid_calls_authorized"] is False and
           study["spending"]["pilot_cap_usd"] is None and study["spending"]["total_cap_usd"] is None)
    return {"stage": 1, "study_id": study["study_id"], "status": "passed",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(), "paid_api_calls": 0,
            "checks": checks, "selected_series": selected, "native_task_count": len(TASKS),
            "reasoning_case_count": len(reasoning), "consulting_case_count": 10,
            "kaggle_counts": kaggle["expected_counts"],
            "limitations": ["Prior manual outcome use of primary window is uncertain.",
                            "Planned coverage is not completed research.",
                            "Design checker does not implement the LLM policy or authorize spending."]}
