"""Reproducible empirical analysis engine for Report 2.

Consumes validated production claims, daily results, actions, and baselines.
Computes raw paired contrasts, control-adjusted interactions, 3-day confirmed recovery,
demand-weighted service levels, reliability metrics, and block-level summaries.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def load_cohort_runs(batch_dir: Path, cohort_name: str = "main") -> pd.DataFrame:
    """Load all validated claims and daily response results for a model cohort."""
    claims_dir = batch_dir / "claims"
    branches_dir = batch_dir / "branches"
    if not claims_dir.exists():
        return pd.DataFrame()

    records = []
    for claim_file in sorted(claims_dir.glob("*.json")):
        claim = json.loads(claim_file.read_text(encoding="utf-8"))
        if claim.get("status") != "validated_complete":
            continue
        ep = claim["episode"]
        branch_dir = branches_dir / claim_file.stem
        if not branch_dir.exists():
            continue

        daily_file = branch_dir / "daily_results.csv"
        actions_file = branch_dir / "actions.jsonl"
        summary_file = branch_dir / "summary.json"

        daily_df = pd.read_csv(daily_file) if daily_file.exists() else None
        actions = [json.loads(line) for line in actions_file.read_text(encoding="utf-8").splitlines()] if actions_file.exists() else []
        summary = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.exists() else {}

        demand = float(daily_df["demand"].sum()) if daily_df is not None else 0.0
        sales = float(daily_df["sales"].sum()) if daily_df is not None else 0.0
        lost_sales = float(daily_df["lost_sales"].sum()) if daily_df is not None else 0.0
        fill_rate = sales / demand if demand > 0 else 1.0

        first_pass = sum(not a.get("repair_attempted") and not a.get("fallback_used") for a in actions)
        repairs = sum(bool(a.get("repair_attempted")) for a in actions)
        fallbacks = sum(bool(a.get("fallback_used")) for a in actions)

        records.append({
            "identity": claim_file.stem,
            "cohort": cohort_name,
            "block_id": ep["block_id"],
            "store_id": ep["store_id"],
            "product_id": ep["product_id"],
            "window_id": ep["window_id"],
            "scenario": ep["scenario"],
            "history": ep.get("history", "full"),
            "elasticity": ep.get("elasticity", 1.5),
            "realization": ep.get("realization", 0),
            "policy": ep["policy"],
            "contribution": float(daily_df["contribution"].sum()) if daily_df is not None else 0.0,
            "demand": demand,
            "sales": sales,
            "lost_sales": lost_sales,
            "fill_rate": fill_rate,
            "stockout_days": int((daily_df["lost_sales"] > 0).sum()) if daily_df is not None else 0,
            "mean_closing_inventory": float(daily_df["closing_inventory"].mean()) if daily_df is not None else 0.0,
            "terminal_closing_inventory": float(daily_df.iloc[-1]["closing_inventory"]) if daily_df is not None else 0.0,
            "mean_price_multiplier": float(daily_df["price"].mean() / ep.get("reference_price", daily_df["price"].mean())) if daily_df is not None else 1.0,
            "first_pass_valid": first_pass,
            "repairs_attempted": repairs,
            "fallbacks_used": fallbacks,
            "total_decisions": len(actions),
            "model_calls_made": summary.get("model_calls_made", 0),
            "daily_file": str(daily_file.resolve()),
        })

    return pd.DataFrame(records)


def load_baseline_runs(batch_dir: Path) -> pd.DataFrame:
    """Load all deterministic baseline runs."""
    baselines_dir = batch_dir / "baselines" / "claims"
    branches_dir = batch_dir / "baselines" / "branches"
    if not baselines_dir.exists():
        return pd.DataFrame()

    records = []
    for claim_file in sorted(baselines_dir.glob("*.json")):
        claim = json.loads(claim_file.read_text(encoding="utf-8"))
        if claim.get("status") != "validated_complete":
            continue
        ep = claim["episode"]
        branch_dir = branches_dir / claim_file.stem
        if not branch_dir.exists():
            continue

        daily_file = branch_dir / "daily_results.csv"
        daily_df = pd.read_csv(daily_file) if daily_file.exists() else None

        demand = float(daily_df["demand"].sum()) if daily_df is not None else 0.0
        sales = float(daily_df["sales"].sum()) if daily_df is not None else 0.0
        lost_sales = float(daily_df["lost_sales"].sum()) if daily_df is not None else 0.0
        fill_rate = sales / demand if demand > 0 else 1.0

        records.append({
            "identity": claim_file.stem,
            "block_id": ep["block_id"],
            "store_id": ep["store_id"],
            "product_id": ep["product_id"],
            "window_id": ep["window_id"],
            "scenario": ep["scenario"],
            "elasticity": ep.get("elasticity", 1.5),
            "policy": ep["policy"],
            "contribution": float(daily_df["contribution"].sum()) if daily_df is not None else 0.0,
            "demand": demand,
            "sales": sales,
            "lost_sales": lost_sales,
            "fill_rate": fill_rate,
            "stockout_days": int((daily_df["lost_sales"] > 0).sum()) if daily_df is not None else 0,
            "mean_closing_inventory": float(daily_df["closing_inventory"].mean()) if daily_df is not None else 0.0,
            "terminal_closing_inventory": float(daily_df.iloc[-1]["closing_inventory"]) if daily_df is not None else 0.0,
            "daily_file": str(daily_file.resolve()),
        })

    return pd.DataFrame(records)


def compute_recovery_for_pair(shock_daily: pd.DataFrame, control_daily: pd.DataFrame) -> dict:
    """Compute 3-day confirmed recovery according to frozen protocol.
    
    Candidate onset days 15-19 inclusive, requiring 3 consecutive qualifying days through day 21,
    0 lost sales, and closing inventory within 20% tolerance of control (floor 1 unit).
    Delay is qualifying onset day minus day 14. Unrecovered episodes are right-censored at day 21.
    """
    # Create 21-day timeline by prepending dummy days 1-7 (which are never inspected by recovery)
    warmup_days = pd.DataFrame([{
        "episode_day": d,
        "closing_inventory": 0.0,
        "lost_sales": 0.0,
    } for d in range(1, 8)])

    s = shock_daily.copy()
    c = control_daily.copy()
    s["episode_day"] = range(8, 22)
    c["episode_day"] = range(8, 22)

    s_full = pd.concat([warmup_days, s[["episode_day", "closing_inventory", "lost_sales"]]], ignore_index=True)
    c_full = pd.concat([warmup_days, c[["episode_day", "closing_inventory", "lost_sales"]]], ignore_index=True)

    for first in range(15, 20):
        s_win = s_full.iloc[first - 1:first + 2]
        c_win = c_full.iloc[first - 1:first + 2]
        tolerance = 0.20 * np.maximum(c_win["closing_inventory"].to_numpy(), 1.0)
        inv_diff = np.abs(s_win["closing_inventory"].to_numpy() - c_win["closing_inventory"].to_numpy())
        if (s_win["lost_sales"].to_numpy() == 0).all() and (inv_diff <= tolerance).all():
            return {
                "recovered": True,
                "recovery_start_day": first,
                "confirmation_day": first + 2,
                "recovery_delay_days": first - 14,
                "right_censored": False,
            }

    return {
        "recovered": False,
        "recovery_start_day": None,
        "confirmation_day": None,
        "recovery_delay_days": None,
        "right_censored": True,
    }


def compute_paired_contrasts(models_df: pd.DataFrame, baselines_df: pd.DataFrame) -> pd.DataFrame:
    """Pair each model episode with adaptive and fixed baselines on the same block, scenario, elasticity."""
    if models_df.empty or baselines_df.empty:
        return pd.DataFrame()

    adaptive = baselines_df[baselines_df["policy"] == "adaptive"].drop_duplicates(
        subset=["block_id", "scenario", "elasticity"]
    ).set_index(["block_id", "scenario", "elasticity"])
    fixed = baselines_df[baselines_df["policy"] == "fixed"].drop_duplicates(
        subset=["block_id", "scenario", "elasticity"]
    ).set_index(["block_id", "scenario", "elasticity"])

    contrasts = []
    for _, row in models_df.iterrows():
        key = (row["block_id"], row["scenario"], row["elasticity"])
        c_llm = float(row["contribution"])

        c_adapt = float(adaptive.loc[key]["contribution"]) if key in adaptive.index else None
        c_fixed = float(fixed.loc[key]["contribution"]) if key in fixed.index else None

        contrasts.append({
            **row.to_dict(),
            "adaptive_contribution": c_adapt,
            "fixed_contribution": c_fixed,
            "raw_contrast_adaptive": (c_llm - c_adapt) if c_adapt is not None else None,
            "raw_contrast_fixed": (c_llm - c_fixed) if c_fixed is not None else None,
            "adaptive_fill_rate": float(adaptive.loc[key]["fill_rate"]) if key in adaptive.index else None,
            "fixed_fill_rate": float(fixed.loc[key]["fill_rate"]) if key in fixed.index else None,
        })

    df = pd.DataFrame(contrasts)

    # Compute control-adjusted interaction:
    # Interaction = [C(LLM, shock) - C(LLM, control)] - [C(adaptive, shock) - C(adaptive, control)]
    # First find control contribution for each (block_id, history, elasticity, realization)
    controls = df[df["scenario"] == "control"].set_index(["block_id", "history", "elasticity", "realization"])
    interactions = []
    for _, row in df.iterrows():
        ctrl_key = (row["block_id"], row["history"], row["elasticity"], row["realization"])
        if ctrl_key in controls.index:
            ctrl_row = controls.loc[ctrl_key]
            llm_ctrl = ctrl_row["contribution"]
            adapt_ctrl = ctrl_row["adaptive_contribution"]
            fixed_ctrl = ctrl_row["fixed_contribution"]

            delta_llm = row["contribution"] - llm_ctrl
            delta_adapt = (row["adaptive_contribution"] - adapt_ctrl) if (row["adaptive_contribution"] is not None and adapt_ctrl is not None) else None
            delta_fixed = (row["fixed_contribution"] - fixed_ctrl) if (row["fixed_contribution"] is not None and fixed_ctrl is not None) else None

            inter_adapt = (delta_llm - delta_adapt) if delta_adapt is not None else None
            inter_fixed = (delta_llm - delta_fixed) if delta_fixed is not None else None

            # Compute recovery if shock condition
            if row["scenario"] != "control" and Path(row["daily_file"]).exists() and Path(ctrl_row["daily_file"]).exists():
                rec_llm = compute_recovery_for_pair(pd.read_csv(row["daily_file"]), pd.read_csv(ctrl_row["daily_file"]))
                rec_recovered = rec_llm["recovered"]
                rec_onset = rec_llm["recovery_start_day"]
                rec_delay = rec_llm["recovery_delay_days"]
                rec_censored = rec_llm["right_censored"]
            else:
                rec_recovered = None
                rec_onset = None
                rec_delay = None
                rec_censored = None
        else:
            inter_adapt = None
            inter_fixed = None
            delta_llm = None
            delta_adapt = None
            rec_recovered = None
            rec_onset = None
            rec_delay = None
            rec_censored = None

        interactions.append({
            "control_adjusted_interaction_adaptive": inter_adapt,
            "control_adjusted_interaction_fixed": inter_fixed,
            "shock_minus_control_llm": delta_llm,
            "shock_minus_control_adaptive": delta_adapt,
            "recovery_recovered": rec_recovered,
            "recovery_start_day": rec_onset,
            "recovery_delay_days": rec_delay,
            "recovery_right_censored": rec_censored,
        })

    return pd.concat([df, pd.DataFrame(interactions)], axis=1)


def summarize_by_block(contrasts_df: pd.DataFrame) -> pd.DataFrame:
    """Average 3 realizations within each block first, then summarize across the 36 blocks."""
    if contrasts_df.empty:
        return pd.DataFrame()

    # Step 1: Mean over the 3 realizations per (block_id, cohort, history, elasticity, scenario)
    block_agg = contrasts_df.groupby(["block_id", "cohort", "history", "elasticity", "scenario"]).agg({
        "contribution": "mean",
        "adaptive_contribution": "first",
        "fixed_contribution": "first",
        "raw_contrast_adaptive": "mean",
        "raw_contrast_fixed": "mean",
        "control_adjusted_interaction_adaptive": "mean",
        "control_adjusted_interaction_fixed": "mean",
        "fill_rate": "mean",
        "lost_sales": "mean",
        "stockout_days": "mean",
        "mean_closing_inventory": "mean",
        "first_pass_valid": "mean",
        "repairs_attempted": "mean",
        "fallbacks_used": "mean",
    }).reset_index()

    # Step 2: Distribution across blocks per scenario
    summary_rows = []
    for (cohort, history, elasticity, scenario), group in block_agg.groupby(["cohort", "history", "elasticity", "scenario"]):
        n_blocks = len(group)
        rc_adapt = group["raw_contrast_adaptive"].dropna()
        cai_adapt = group["control_adjusted_interaction_adaptive"].dropna()

        summary_rows.append({
            "cohort": cohort,
            "history": history,
            "elasticity": elasticity,
            "scenario": scenario,
            "n_blocks": n_blocks,
            "mean_llm_contribution": group["contribution"].mean(),
            "mean_adaptive_contribution": group["adaptive_contribution"].mean(),
            "mean_raw_contrast_adaptive": rc_adapt.mean(),
            "median_raw_contrast_adaptive": rc_adapt.median(),
            "std_raw_contrast_adaptive": rc_adapt.std(),
            "min_raw_contrast_adaptive": rc_adapt.min(),
            "max_raw_contrast_adaptive": rc_adapt.max(),
            "positive_raw_contrast_blocks": int((rc_adapt > 0).sum()),
            "negative_raw_contrast_blocks": int((rc_adapt < 0).sum()),
            "mean_control_adjusted_interaction": cai_adapt.mean() if not cai_adapt.empty else None,
            "median_control_adjusted_interaction": cai_adapt.median() if not cai_adapt.empty else None,
            "positive_interaction_blocks": int((cai_adapt > 0).sum()) if not cai_adapt.empty else None,
            "mean_fill_rate": group["fill_rate"].mean(),
            "mean_stockout_days": group["stockout_days"].mean(),
            "mean_first_pass_valid": group["first_pass_valid"].mean(),
            "mean_repairs_attempted": group["repairs_attempted"].mean(),
            "mean_fallbacks_used": group["fallbacks_used"].mean(),
        })

    return pd.DataFrame(summary_rows)

