"""Report 2 Stage 5: offline analysis of the validated production evidence (no model calls).

Definitions follow the frozen protocol (`configs/report2/protocol.json`, "analysis"):

- Primary outcome: contribution summed over response days 8-21 (revenue - COGS - holding cost).
- Raw contrast: LLM(shock) - adaptive(shock), per condition.
- Control-adjusted interaction: (LLM_shock - LLM_control) - (adaptive_shock - adaptive_control).
- History contrasts: full - frozen and full - none, plus their shock-minus-control differences.
- Aggregation: LLM realizations are averaged within block x condition first; blocks are weighted equally.
- Inference: descriptive only (mean, median, range, sign counts); no intervals or significance tests.
- Recovery: first candidate day in 15..19 that starts 3 consecutive qualifying days (zero lost sales and
  |inventory - own paired-control inventory| <= 20% of max(control inventory, 1)); delay = day - 14;
  right-censored at day 21.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.report2 import read_json
from src.research.report2_production import baseline_plan, episode_identity, production_plan

ROOT = Path(__file__).resolve().parents[2]
CONDITIONS = ["control", "demand_surge", "demand_decline", "delivery_disruption"]
SHOCKS = CONDITIONS[1:]
FIRST_RESPONSE_DAY = 8
RESPONSE_DAYS = 14
FROZEN_TIMEOUT_SECONDS = 90
COHORT_DIRS = {"main": "production", "history": "history", "elasticity": "elasticity"}
EPISODE_KEYS = ["block_id", "store_id", "product_id", "window_id", "scenario", "history",
                "elasticity", "realization", "policy"]


# ---------------------------------------------------------------- branch-level metrics

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def branch_outcomes(daily: pd.DataFrame, actions: list[dict]) -> dict:
    """Economic and service outcomes over the response period of one trajectory."""
    orders = [sum(a["order_quantity"] for a in act["actions"].values()) for act in actions]
    multipliers = [m for act in actions for m in (a["price_multiplier"] for a in act["actions"].values())]
    demand = daily["demand"].sum()
    return {
        "contribution": daily["contribution"].sum(),
        "revenue": daily["revenue"].sum(),
        "cogs": daily["cost_of_goods_sold"].sum(),
        "gross_margin": daily["revenue"].sum() - daily["cost_of_goods_sold"].sum(),
        "holding_cost": daily["holding_cost"].sum(),
        "demand": demand,
        "sales": daily["sales"].sum(),
        "lost_sales": daily["lost_sales"].sum(),
        "fill_rate": daily["sales"].sum() / demand if demand > 0 else 1.0,
        "stockout_days": int((daily["lost_sales"] > 0).sum()),
        "mean_inventory": daily["closing_inventory"].mean(),
        "terminal_inventory": daily["closing_inventory"].iloc[-1],
        "total_ordered": sum(orders),
        "order_days": sum(q > 0 for q in orders),
        "mean_price_multiplier": float(np.mean(multipliers)) if multipliers else np.nan,
        "discount_days": sum(m < 1 for m in multipliers),
        "premium_days": sum(m > 1 for m in multipliers),
    }


def api_usage(attempts: list[dict]) -> dict:
    """Usage from the final (validated) evidence of one branch; archived failures are counted elsewhere."""
    finished = [e for e in attempts if e.get("event") == "finished"]
    latencies = [e.get("latency_seconds") or 0.0 for e in finished]
    completed = [e for e in finished if e.get("status") == "completed"]
    return {
        "api_attempts": len(finished),
        "api_failed": len(finished) - len(completed),
        "input_tokens": sum((e.get("usage") or {}).get("prompt_tokens", 0) for e in completed),
        "output_tokens": sum((e.get("usage") or {}).get("completion_tokens", 0) for e in completed),
        "known_credits": sum(e.get("cost_usd") or 0.0 for e in completed),
        "latency_total": sum(latencies),
        "latency_max": max(latencies, default=0.0),
        "over_frozen_timeout": sum(1 for e in completed if (e.get("latency_seconds") or 0) > FROZEN_TIMEOUT_SECONDS),
    }


def recovery_delay(shock_inventory, shock_lost_sales, control_inventory, *, candidate_days=(15, 19),
                   consecutive=3, tolerance=0.20, last_day=21):
    """Frozen recovery rule. Inputs are 14-element sequences for days 8..21. Returns delay or None (censored)."""
    def qualifies(day):
        i = day - FIRST_RESPONSE_DAY
        ref = max(control_inventory[i], 1.0)
        return shock_lost_sales[i] == 0 and abs(shock_inventory[i] - control_inventory[i]) <= tolerance * ref

    for day in range(candidate_days[0], candidate_days[1] + 1):
        if day + consecutive - 1 > last_day:
            break
        if all(qualifies(d) for d in range(day, day + consecutive)):
            return day - 14
    return None


# ---------------------------------------------------------------- evidence loading

def load_branch(run_dir: Path, request_dir: Path | None) -> tuple[dict, pd.DataFrame]:
    summary = read_json(run_dir / "summary.json")
    manifest = read_json(run_dir / "run_manifest.json")
    prefix = read_json(run_dir / "prefix_audit.json")
    daily = pd.read_csv(run_dir / "daily_results.csv")
    actions = read_jsonl(run_dir / "actions.jsonl")
    if len(daily) != RESPONSE_DAYS or len(actions) != RESPONSE_DAYS:
        raise ValueError(f"{run_dir.name}: expected {RESPONSE_DAYS} response days")
    if summary.get("status") != "validated_complete" or not summary.get("accounting_reconciled"):
        raise ValueError(f"{run_dir.name}: branch not validated or accounting not reconciled")
    if abs(daily["contribution"].sum() - summary["post_split_contribution"]) > 1e-6:
        raise ValueError(f"{run_dir.name}: daily contribution does not reconcile with summary")
    if prefix.get("status") != "passed":
        raise ValueError(f"{run_dir.name}: prefix audit did not pass")
    record = {
        **branch_outcomes(daily, actions),
        "manifest_scenario": manifest["scenario"],
        "manifest_history": manifest["history"],
        "manifest_policy": manifest["policy"],
        "prefix_sha256": prefix["prefix_sha256"],
        "restored_state_sha256": prefix["restored_state_sha256"],
        "initial_assets": summary["initial_assets_at_split"],
        "terminal_assets": summary["terminal_assets"],
        "completed_decisions": summary["completed_decisions"],
        "first_pass_valid": summary["first_pass_valid"],
        "repair_attempts": summary["repair_attempts"],
        "successful_repairs": summary["successful_repairs"],
        "fallback_days": summary["fallback_days"],
    }
    if request_dir is not None:
        record.update(api_usage(read_jsonl(request_dir / "api_attempts.jsonl")))
    daily = daily.assign(day=range(FIRST_RESPONSE_DAY, FIRST_RESPONSE_DAY + RESPONSE_DAYS))
    return record, daily


def load_evidence(root: Path = ROOT) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Load every planned LLM and baseline branch; fail if any planned branch is missing or inconsistent."""
    results = root / "results/report2"
    records, dailies = [], []

    def add(plan, batch_dir, label, with_requests):
        for episode in plan["episodes"]:
            identity = episode_identity(plan, episode)
            claim_path = batch_dir / "claims" / f"{identity}.json"
            if not claim_path.exists() or read_json(claim_path).get("status") != "validated_complete":
                raise ValueError(f"Missing validated branch {identity} in {batch_dir}")
            if read_json(claim_path)["episode"] != episode:
                raise ValueError(f"Claim episode differs from frozen plan for {identity}")
            record, daily = load_branch(batch_dir / "branches" / identity,
                                        batch_dir / "requests" / identity if with_requests else None)
            if (record["manifest_scenario"], record["manifest_history"]) != (episode["scenario"], episode["history"]):
                raise ValueError(f"Run manifest differs from plan for {identity}")
            meta = {"identity": identity, "source": label, **{k: episode[k] for k in EPISODE_KEYS}}
            records.append({**meta, **record})
            dailies.append(daily.assign(**{k: meta[k] for k in ("identity", "source", "block_id", "scenario",
                                                                "history", "elasticity", "realization", "policy")}))

    for cohort, folder in COHORT_DIRS.items():
        add(production_plan(cohort, root), results / folder, cohort, True)
    add(baseline_plan("all", root), results / "production/baselines", "baseline", False)

    episodes = pd.DataFrame(records)
    daily = pd.concat(dailies, ignore_index=True)

    # Matched-prefix integrity: one prefix and restored state per block x elasticity across every policy.
    groups = episodes.groupby(["block_id", "elasticity"])
    integrity = {
        "llm_branches": int((episodes["source"] != "baseline").sum()),
        "baseline_branches": int((episodes["source"] == "baseline").sum()),
        "prefix_groups": int(groups.ngroups),
        "prefix_groups_with_single_prefix": int((groups["prefix_sha256"].nunique() == 1).sum()),
        "prefix_groups_with_single_restored_state": int((groups["restored_state_sha256"].nunique() == 1).sum()),
        "daily_rows": int(len(daily)),
    }
    if integrity["prefix_groups_with_single_prefix"] != integrity["prefix_groups"]:
        raise ValueError("Matched-prefix check failed: a block/elasticity group has more than one prefix")
    return episodes, daily, integrity


# ---------------------------------------------------------------- recovery

def add_recovery(episodes: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Attach recovery delay to shock trajectories, pairing each with its own control trajectory."""
    key = ["source", "block_id", "history", "elasticity", "realization", "policy"]
    by_branch = {ident: g.sort_values("day") for ident, g in daily.groupby("identity")}
    controls = episodes[episodes["scenario"] == "control"].set_index(key)["identity"]
    delays = []
    for row in episodes.itertuples(index=False):
        if row.scenario == "control":
            delays.append(np.nan)
            continue
        shock = by_branch[row.identity]
        control = by_branch[controls.loc[tuple(getattr(row, k) for k in key)]]
        delay = recovery_delay(shock["closing_inventory"].to_numpy(), shock["lost_sales"].to_numpy(),
                               control["closing_inventory"].to_numpy())
        delays.append(np.nan if delay is None else delay)
    out = episodes.copy()
    out["recovery_delay"] = delays
    out["recovered"] = np.where(out["scenario"] == "control", np.nan, out["recovery_delay"].notna().astype(float))
    return out


# ---------------------------------------------------------------- contrasts

OUTCOMES = ["contribution", "revenue", "cogs", "gross_margin", "holding_cost", "sales", "fill_rate",
            "lost_sales", "stockout_days", "mean_inventory", "terminal_inventory", "total_ordered",
            "mean_price_multiplier", "discount_days", "premium_days", "terminal_assets"]


def llm_settings(episodes: pd.DataFrame, diagnostic_blocks: set[str]) -> pd.DataFrame:
    """LLM branches labelled by setting. Main full-history branches are reused for history/elasticity."""
    llm = episodes[episodes["source"] != "baseline"].copy()
    llm["setting"] = np.select(
        [llm["history"] != "full", llm["elasticity"] != 1.5],
        ["history_" + llm["history"], "elasticity_" + llm["elasticity"].astype(str)],
        default="main")
    llm["diagnostic"] = llm["block_id"].isin(diagnostic_blocks)
    return llm


def block_means(llm: pd.DataFrame) -> pd.DataFrame:
    """Average realizations within block x condition x history x elasticity; keep the realization range."""
    keys = ["block_id", "scenario", "history", "elasticity"]
    mean = llm.groupby(keys)[OUTCOMES].mean()
    spread = llm.groupby(keys)["contribution"].agg(["min", "max", "count"])
    spread.columns = ["contribution_min", "contribution_max", "realizations"]
    return mean.join(spread).reset_index()


def paired_contrasts(llm_blocks: pd.DataFrame, baselines: pd.DataFrame) -> pd.DataFrame:
    """Block-level LLM vs adaptive/fixed contrasts, plus control-adjusted interactions."""
    base = baselines.pivot_table(index=["block_id", "scenario", "elasticity"], columns="policy",
                                 values=OUTCOMES).reset_index()
    base.columns = ["_".join(c).strip("_") if isinstance(c, tuple) else c for c in base.columns]
    df = llm_blocks.merge(base, on=["block_id", "scenario", "elasticity"], how="left", validate="many_to_one")
    if df["contribution_adaptive"].isna().any():
        raise ValueError("Missing matched baseline for an LLM block")
    for policy in ("adaptive", "fixed"):
        df[f"raw_vs_{policy}"] = df["contribution"] - df[f"contribution_{policy}"]
    df["fill_rate_diff_pp"] = 100 * (df["fill_rate"] - df["fill_rate_adaptive"])
    df["mean_inventory_diff"] = df["mean_inventory"] - df["mean_inventory_adaptive"]
    df["lost_sales_diff"] = df["lost_sales"] - df["lost_sales_adaptive"]
    control = df[df["scenario"] == "control"].set_index(["block_id", "history", "elasticity"])
    for policy in ("adaptive", "fixed"):
        ctrl = control[f"raw_vs_{policy}"]
        df[f"adjusted_vs_{policy}"] = [
            np.nan if s == "control" else r - ctrl.loc[(b, h, e)]
            for s, r, b, h, e in zip(df["scenario"], df[f"raw_vs_{policy}"], df["block_id"], df["history"], df["elasticity"])]
    return df


def describe(values: pd.Series) -> dict:
    v = values.dropna()
    return {"n_blocks": int(len(v)), "mean": v.mean(), "median": v.median(), "min": v.min(), "max": v.max(),
            "n_positive": int((v > 0).sum()), "n_negative": int((v < 0).sum())}


def summarize(df: pd.DataFrame, by: list[str], columns: list[str]) -> pd.DataFrame:
    rows = []
    for keys, group in df.groupby(by, sort=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        for column in columns:
            if group[column].notna().any():
                rows.append({**dict(zip(by, keys)), "measure": column, **describe(group[column])})
    return pd.DataFrame(rows)


def history_contrasts(llm_blocks: pd.DataFrame, diagnostic_blocks: set[str]) -> pd.DataFrame:
    """Full minus frozen / none per block x condition, and the shock-minus-control difference."""
    blocks = llm_blocks[(llm_blocks["elasticity"] == 1.5) & llm_blocks["block_id"].isin(diagnostic_blocks)]
    wide = blocks.pivot_table(index=["block_id", "scenario"], columns="history",
                              values=["contribution", "fill_rate"]).reset_index()
    rows = []
    for ablation in ("frozen", "none"):
        part = pd.DataFrame({
            "block_id": wide["block_id"], "scenario": wide["scenario"], "ablation": ablation,
            "full_contribution": wide[("contribution", "full")],
            "ablation_contribution": wide[("contribution", ablation)],
            "full_minus_ablation": wide[("contribution", "full")] - wide[("contribution", ablation)],
            "fill_rate_diff_pp": 100 * (wide[("fill_rate", "full")] - wide[("fill_rate", ablation)]),
        })
        ctrl = part[part["scenario"] == "control"].set_index("block_id")["full_minus_ablation"]
        part["shock_minus_control"] = [np.nan if s == "control" else d - ctrl.loc[b]
                                       for s, d, b in zip(part["scenario"], part["full_minus_ablation"], part["block_id"])]
        rows.append(part)
    return pd.concat(rows, ignore_index=True)


def reliability(llm: pd.DataFrame) -> pd.DataFrame:
    """Decision provenance with explicit denominators, from final validated evidence."""
    rows = []
    for setting, g in llm.groupby("setting", sort=False):
        decisions = g["completed_decisions"].sum()
        repairs = g["repair_attempts"].sum()
        rows.append({
            "setting": setting, "branches": len(g), "scheduled_decisions": len(g) * RESPONSE_DAYS,
            "completed_decisions": decisions,
            "first_pass_valid": g["first_pass_valid"].sum(),
            "first_pass_valid_share": g["first_pass_valid"].sum() / decisions,
            "repair_attempts": repairs, "repair_attempt_share": repairs / decisions,
            "successful_repairs": g["successful_repairs"].sum(),
            "repair_success_rate": g["successful_repairs"].sum() / repairs if repairs else np.nan,
            "fallback_days": g["fallback_days"].sum(), "fallback_share": g["fallback_days"].sum() / decisions,
            "api_attempts": g["api_attempts"].sum(), "attempts_per_decision": g["api_attempts"].sum() / decisions,
            "input_tokens": g["input_tokens"].sum(), "output_tokens": g["output_tokens"].sum(),
            "known_credits": g["known_credits"].sum(),
            "credits_per_branch": g["known_credits"].sum() / len(g),
            "api_seconds_per_decision": g["latency_total"].sum() / decisions,
            "branches_with_fallback": int((g["fallback_days"] > 0).sum()),
        })
    return pd.DataFrame(rows)


def operational_accounting(episodes: pd.DataFrame, root: Path = ROOT) -> pd.DataFrame:
    """All ledger attempts per cohort, including interrupted runs archived during recovery."""
    ledger = root / "results/budgets/stage2_pilot_v1.sqlite"
    with closing(sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        rows = pd.read_sql_query(
            "SELECT run_id, status, reserved_nanos, actual_nanos, uncertainty_reason, "
            "id IN (SELECT attempt_id FROM bounded_holds) AS held FROM attempts", db)
        total_nanos = db.execute(
            "SELECT SUM(CASE WHEN status='settled' THEN actual_nanos "
            "ELSE MAX(reserved_nanos, COALESCE(actual_nanos,0)) END) FROM attempts").fetchone()[0]
    out = []
    llm = episodes[episodes["source"] != "baseline"]
    for cohort, folder in COHORT_DIRS.items():
        ids = set(llm.loc[llm["source"] == cohort, "identity"])
        part = rows[rows["run_id"].isin(ids)]
        final = llm.loc[llm["source"] == cohort]
        settled = part[part["status"] == "settled"]
        unsettled = part[part["status"] != "settled"]
        out.append({
            "cohort": cohort,
            "ledger_attempts": len(part),
            "final_evidence_attempts": int(final["api_attempts"].sum()),
            "attempts_in_interrupted_runs": len(part) - int(final["api_attempts"].sum()),
            "known_credits": settled["actual_nanos"].sum() / 1e9,
            "unknown_charge_reserves": unsettled["reserved_nanos"].sum() / 1e9,
            "unknown_charge_attempts": len(unsettled),
            "unheld_unsettled_attempts": int((unsettled["held"] == 0).sum()),
            "total_exposure": (settled["actual_nanos"].sum() + unsettled["reserved_nanos"].sum()) / 1e9,
            "recoveries": sum(1 for p in (root / "results/report2" / folder).glob("recovery*")
                              if p.is_dir() and p.name[8:].isdigit()),
        })
    table = pd.DataFrame(out)
    table.attrs["project_exposure"] = total_nanos / 1e9
    return table
