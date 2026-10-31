"""Offline sampling and workload for report 2; no policy, gateway or SDK imports."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = "configs/report2/protocol.json"
MANIFEST = "configs/report2/sampling_manifest.json"
INPUTS = (
    PROTOCOL, "configs/sources.json", "configs/study.json",
    "configs/kaggle_retailbench.json", "configs/kaggle_action.schema.json",
    "prompts/kaggle_policy_v1.txt", "prompts/kaggle_repair_v1.txt",
    "src/agents/llm.py", "src/agents/baselines.py",
    "src/envs/kaggle_retailbench.py", "src/data/kaggle.py",
)
KEY = ["Store ID", "Product ID"]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def canonical_hash(value: dict) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def validate_protocol(protocol: dict) -> None:
    """Reject unsafe scope changes and date overlap before sampling any data."""
    execution = protocol["execution"]
    if (execution["model_runs"] != "user_manually_only"
            or execution["model_calls_authorized"] is not False
            or execution["budget_cap_credits"] is not None):
        raise ValueError("Milestone 1 authorizes no model calls; model execution is manual only.")
    sampling, branch = protocol["sampling"], protocol["branching"]
    if (branch["horizon_days"], branch["warmup_days"], branch["response_start_day"],
            branch["response_end_day"], branch["shock_start_day"], branch["shock_end_day"]) != (21, 7, 8, 21, 8, 14):
        raise ValueError("Expected seven common warm-up days and response on days 8-21.")
    if branch["conditions"] != ["control", "demand_surge", "demand_decline", "delivery_disruption"]:
        raise ValueError("Expected control and all three shock conditions.")
    if (sampling["evaluation_series"] != 12 or sampling["repeated_llm_realizations"] != 3
            or sampling["development_llm_realizations"] != 1):
        raise ValueError("Sampling targets changed; create a new version of the protocol.")
    indices = sampling["diagnostic_selected_indices_zero_based"]
    if (len(indices) != 6 or len(set(indices)) != 6
            or any(type(i) is not int or not 0 <= i < 12 for i in indices)):
        raise ValueError("Need six distinct diagnostic indices in the evaluation sample.")
    if (sampling["selection_uses_evaluation_outcomes"] is not False
            or sampling["complete_daily_coverage_required"] is not True
            or branch["future_rows_and_shock_labels_visible"] is not False):
        raise ValueError("Selection and observations must exclude future outcomes.")
    if set(protocol["policies"]["history_variants"]) != {"full", "frozen", "none"}:
        raise ValueError("All three history variants are required.")
    if protocol["failure_policy"]["maximum_repairs_per_decision"] != 1:
        raise ValueError("The frozen composite policy allows exactly one repair.")
    if (protocol["simulator"]["reference_elasticity"] != 1.5
            or protocol["simulator"]["additional_elasticities"] != [0.75, 2.25]):
        raise ValueError("All matched elasticity settings must remain declared.")
    if protocol["analysis"]["bootstrap_daily_rows"] is not False:
        raise ValueError("Dependent daily rows must not be bootstrapped as independent observations.")
    data = protocol["dataset"]
    source_start, train_end, validation_end, source_end = (
        pd.Timestamp(data[k]) for k in ("source_start", "training_end", "validation_end", "source_end"))
    if not source_start < train_end < validation_end < source_end:
        raise ValueError("Invalid chronological split boundaries.")
    windows, development = sampling["evaluation_windows"], sampling["development_cases"]
    if len(windows) != 3 or len(development) != 2:
        raise ValueError("Expected three evaluation windows and two development cases.")
    identifiers = [w["id"] for w in windows + development]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Window identifiers must be unique.")
    prior_end = validation_end
    for window in windows:
        start, end = pd.Timestamp(window["start"]), pd.Timestamp(window["end"])
        if start <= prior_end or end > source_end or (end - start).days != 20:
            raise ValueError("Evaluation windows must be chronological, non-overlapping test periods of 21 days.")
        prior_end = end
    for case in development:
        start, end = pd.Timestamp(case["start"]), pd.Timestamp(case["end"])
        if start <= train_end or end > validation_end or (end - start).days != 20:
            raise ValueError("Development cases must remain in validation dates, separate from evaluation.")


def sample_series(frame: pd.DataFrame, protocol: dict) -> dict:
    """Use only date coverage and training demand; do not aggregate held-out demand."""
    validate_protocol(protocol)
    frame = frame.copy()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="raise")
    if frame[["Date", *KEY]].isna().any().any() or frame.duplicated(["Date", *KEY]).any():
        raise ValueError("Series/date keys must be complete and unique.")
    data, sampling = protocol["dataset"], protocol["sampling"]
    expected = pd.date_range(data["source_start"], data["source_end"], freq="D")
    if not pd.DatetimeIndex(frame["Date"].unique()).sort_values().equals(expected):
        raise ValueError("Source calendar differs from the declared full daily coverage.")
    complete = {
        key for key, group in frame.groupby(KEY)
        if pd.DatetimeIndex(group["Date"].sort_values()).equals(expected)
    }
    development = sampling["development_cases"]
    excluded = {(r["store_id"], r["product_id"]) for r in sampling["legacy_series_excluded"]}
    development_keys = {(r["store_id"], r["product_id"]) for r in development}
    if not development_keys.issubset(complete & excluded):
        raise ValueError("Development series must be fully covered legacy series, excluded from evaluation.")
    train = frame.loc[frame["Date"] <= pd.Timestamp(data["training_end"])].copy()
    train["Demand"] = pd.to_numeric(train["Demand"], errors="raise")
    if not train["Demand"].map(lambda x: math.isfinite(x) and x >= 0).all():
        raise ValueError("Training demand must be finite and nonnegative.")
    stats = train.groupby(KEY)["Demand"].agg(["mean", "std"])
    stats["cv"] = stats["std"] / stats["mean"]
    stats = stats.loc[[key in complete - excluded for key in stats.index]]
    stats = stats.loc[(stats["mean"] > 0) & stats["cv"].map(math.isfinite)]
    ranked = stats.reset_index().sort_values(["cv", *KEY]).reset_index(drop=True)
    count = sampling["evaluation_series"]
    if len(ranked) < count:
        raise ValueError("Insufficient eligible series; amend the protocol rather than silently shrink the cohort.")
    selected = []
    for index in range(count):
        rank = math.floor(len(ranked) * (index + 0.5) / count)
        row = ranked.iloc[rank]
        selected.append({
            "selected_index_zero_based": index, "eligible_rank_zero_based": rank,
            "store_id": str(row["Store ID"]), "product_id": str(row["Product ID"]),
            "training_mean_demand": round(float(row["mean"]), 12),
            "training_cv": round(float(row["cv"]), 12),
            "diagnostic_subset": index in sampling["diagnostic_selected_indices_zero_based"],
        })
    return {"source_rows": len(frame), "source_series": frame.groupby(KEY).ngroups,
            "complete_series": len(complete), "eligible_nonlegacy_series": len(ranked),
            "selected_series": selected}


def workload(protocol: dict) -> dict:
    """Counts include shared-control reuse; repeated LLM realizations are not baseline repeats."""
    sampling, branch = protocol["sampling"], protocol["branching"]
    days = branch["response_end_day"] - branch["response_start_day"] + 1
    conditions = len(branch["conditions"])
    repeats = sampling["repeated_llm_realizations"]
    blocks = sampling["evaluation_series"] * len(sampling["evaluation_windows"])
    diagnostic = len(sampling["diagnostic_selected_indices_zero_based"]) * len(sampling["evaluation_windows"])
    history_count = len(protocol["policies"]["history_variants"])
    elasticity_count = len(protocol["simulator"]["additional_elasticities"])
    main = blocks * conditions * repeats * days
    history = diagnostic * conditions * repeats * days * (history_count - 1)
    sensitivity = diagnostic * conditions * repeats * days * elasticity_count
    development = len(sampling["development_cases"]) * conditions * history_count * sampling["development_llm_realizations"] * days
    factor = 1 + protocol["failure_policy"]["maximum_repairs_per_decision"]
    return {
        "main_series_window_blocks": blocks, "diagnostic_series_window_blocks": diagnostic,
        "response_days_per_branch": days,
        "main_llm_decisions": main, "additional_history_llm_decisions": history,
        "additional_elasticity_llm_decisions": sensitivity,
        "production_llm_decisions": main + history + sensitivity,
        "production_max_completions_before_transport_retries": (main + history + sensitivity) * factor,
        "development_llm_decisions": development,
        "development_max_completions_before_transport_retries": development * factor,
        "production_baseline_branches": (blocks + diagnostic * elasticity_count) * conditions * 2,
        "development_baseline_branches": len(sampling["development_cases"]) * conditions * 2,
        "monetary_estimate": None, "reason": "Current tariffs, measured pilot usage and manual budget handoff required",
    }


def build_manifest(root: Path = ROOT) -> dict:
    protocol = read_json(root / PROTOCOL)
    validate_protocol(protocol)
    raw = root / protocol["dataset"]["path"]
    raw_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
    if raw_hash != protocol["dataset"]["sha256"]:
        raise ValueError("Raw dataset does not match the frozen checksum.")
    source_pins = read_json(root / "configs/sources.json")
    if source_pins["dataset"]["csv_sha256"] != raw_hash:
        raise ValueError("Source pins and protocol disagree on the dataset.")
    reference = read_json(root / protocol["simulator"]["reference_settings"])
    for name in ("purchase_cost_ratio", "holding_cost_ratio", "price_multipliers", "lead_days",
                 "disrupted_lead_days", "surge_multiplier", "decline_multiplier",
                 "max_order_days", "initial_cash_days"):
        if reference[name] != protocol["simulator"][name]:
            raise ValueError(f"Reference simulator differs from protocol: {name}")
    if reference["elasticity"] != protocol["simulator"]["reference_elasticity"]:
        raise ValueError("Reference elasticity differs from protocol.")
    frame = pd.read_csv(raw, usecols=["Date", *KEY, "Demand"], dtype={k: str for k in KEY})
    selection = sample_series(frame, protocol)
    selected = selection["selected_series"]
    windows = protocol["sampling"]["evaluation_windows"]
    blocks = [{"block_id": f"{r['store_id']}_{r['product_id']}_{w['id']}",
               "store_id": r["store_id"], "product_id": r["product_id"],
               "window_id": w["id"], "start": w["start"], "end": w["end"],
               "diagnostic_subset": r["diagnostic_subset"]} for r in selected for w in windows]
    manifest = {
        "schema_version": 1, "study_id": protocol["study_id"],
        "status": "sampling_frozen_experiments_not_run", "protocol_sha256": canonical_hash(protocol),
        "input_text_sha256": {name: hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                              for name in INPUTS},
        "raw_dataset_sha256": raw_hash, **selection,
        "evaluation_blocks": blocks, "development_cases": protocol["sampling"]["development_cases"],
        "dependence_audit": {
            "selected_stores": len({r["store_id"] for r in selected}),
            "selected_products": len({r["product_id"] for r in selected}),
            "series_per_store": dict(sorted(Counter(r["store_id"] for r in selected).items())),
            "shared_calendar_windows": len(windows), "independence_claim_allowed": False,
            "inference": protocol["analysis"]["inference"],
        },
        "workload": workload(protocol), "model_calls_made": 0,
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    return manifest
