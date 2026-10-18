"""Frozen descriptive metrics for matched simulator episodes; never invokes a policy."""
import math

import numpy as np
import pandas as pd

KEY = ["store_id", "product_id"]
PHASES = {"pre_shock": (1, 7), "shock": (8, 14), "post_shock": (15, 21)}


def relative_gain(candidate, baseline):
    return None if abs(baseline) <= 1e-9 else 100 * (candidate - baseline) / abs(baseline)


def interaction(candidate_shock, candidate_control, baseline_shock, baseline_control):
    return (candidate_shock - candidate_control) - (baseline_shock - baseline_control)


def service(frame):
    demand = float(frame["demand"].sum())
    return dict(fill_rate=float(frame["sales"].sum()) / demand if demand else 1.,
                zero_demand=demand == 0, lost_units=float(frame["lost_sales"].sum()),
                stockout_sku_days=int((frame["lost_sales"] > 0).sum()))


def checked_days(frame):
    frame = frame.sort_values("episode_day").reset_index(drop=True)
    if frame["episode_day"].tolist() != list(range(1, 22)):
        raise ValueError("An episode must have exactly the 21 distinct ordered days; never impute gaps.")
    return frame


def recovery(shock, control):
    shock, control = checked_days(shock), checked_days(control)
    for first in range(15, 20):
        s, c = shock.iloc[first - 1:first + 2], control.iloc[first - 1:first + 2]
        tolerance = .2 * np.maximum(c["closing_inventory"].to_numpy(), 1)
        if ((s["lost_sales"].to_numpy() == 0).all()
                and (abs(s["closing_inventory"].to_numpy() - c["closing_inventory"].to_numpy()) <= tolerance).all()):
            return dict(recovered=True, recovery_start_day=first, confirmation_day=first + 2,
                        recovery_delay_days=first - 14, right_censored=False,
                        last_observed_day=21, postshock_followup_days=7)
    return dict(recovered=False, recovery_start_day=None, confirmation_day=None,
                recovery_delay_days=None, right_censored=True, last_observed_day=21, postshock_followup_days=7)


def behavioral_response(shock, control):
    shock, control = checked_days(shock), checked_days(control)
    changed = ((abs(shock["order_quantity"].to_numpy() - control["order_quantity"].to_numpy()) >= 1)
               | (shock["price_multiplier"].to_numpy() != control["price_multiplier"].to_numpy()))
    days = shock.loc[changed & (shock["episode_day"].to_numpy() >= 8), "episode_day"].tolist()
    return dict(first_divergence_day=days[0] if days else None,
                pre_shock_different_action_days=int(changed[:7].sum()),
                shock_different_action_days=int(changed[7:14].sum()),
                post_shock_different_action_days=int(changed[14:].sum()))


def episode_financials(frame, final_funds):
    f = checked_days(frame)
    first, last = f.iloc[0], f.iloc[-1]
    unit_cost = float(first["unit_cost"])
    if not np.allclose(f["unit_cost"], unit_cost, atol=1e-12, rtol=0):
        raise ValueError("Changing purchase costs require a separately specified valuation method.")
    orders, arrivals = float(f["order_quantity"].sum()), float(f["arrivals_next_day"].sum())
    onhand = float(last["closing_inventory"] + last["arrivals_next_day"])
    pipeline = float(first["observed_on_order"] + orders - arrivals)
    if pipeline < 0 or not math.isclose(float(first["observed_inventory"]) + arrivals - float(f["sales"].sum()), onhand, abs_tol=1e-6):
        raise ValueError("On-hand/pipeline conservation failed.")
    cash = float(first["observed_funds"]) - orders * unit_cost + float(f["revenue"].sum()) - float(f["holding_cost"].sum())
    initial_assets = float(first["observed_funds"]) + unit_cost * float(first["observed_inventory"] + first["observed_on_order"])
    contribution = float(f["contribution"].sum())
    if not (math.isclose(cash, final_funds, abs_tol=1e-6, rel_tol=0)
            and math.isclose(cash + unit_cost * (onhand + pipeline) - initial_assets, contribution, abs_tol=1e-6, rel_tol=0)):
        raise ValueError("Cash and terminal assets must independently reconcile to contribution.")
    return dict(contribution=contribution, revenue=float(f["revenue"].sum()), **service(f),
        mean_closing_inventory=float(f["closing_inventory"].mean()), terminal_on_hand_units=onhand,
        terminal_pipeline_units=pipeline, terminal_on_hand_value=onhand * unit_cost,
        terminal_pipeline_value=pipeline * unit_cost, final_funds=cash,
        order_quantity_total=orders, mean_order_quantity=float(f["order_quantity"].mean()),
        mean_price_multiplier=float(f["price_multiplier"].mean()),
        fallback_days=int(f["fallback_used"].sum()), repair_days=int(f["repair_attempted"].sum()),
        invalid_responses=int(f["invalid_responses"].sum()), accounting_reconciled=True)


def analyze(daily, actions, coverage):
    if coverage["matrix_index"].tolist() != list(range(36)) or len(daily) != 756:
        raise ValueError("The complete frozen primary matrix is required.")
    if daily.duplicated(["matrix_index", "date"]).any() or actions.duplicated(["matrix_index", "date"]).any():
        raise ValueError("Duplicate episode-day evidence.")
    extra = ["matrix_index", "date", "order_quantity", "price_multiplier", "observed_funds", "observed_inventory",
             "observed_on_order", "unit_cost", "reference_price", "lead_days"]
    frame = daily.merge(actions[extra], on=["matrix_index", "date"], how="outer", validate="one_to_one", indicator=True)
    if not frame["_merge"].eq("both").all() or len(frame) != 756:
        raise ValueError("Every daily result needs exactly one saved executed action/observation.")
    frame = frame.drop(columns="_merge")
    start = pd.Timestamp("2023-09-22")
    frame["episode_day"] = (pd.to_datetime(frame["date"]) - start).dt.days + 1
    frame["phase"] = frame["episode_day"].map(lambda d: "pre_shock" if d <= 7 else "shock" if d <= 14 else "post_shock")
    episodes, phases, rec, behavior = [], [], [], []
    grouped = {}
    for row in coverage.to_dict("records"):
        f = checked_days(frame.loc[frame["matrix_index"] == row["matrix_index"]])
        meta = {k: row[k] for k in ["matrix_index", *KEY, "scenario", "policy"]}
        result = episode_financials(f, row["final_funds"])
        if not math.isclose(result["contribution"], row["contribution"], abs_tol=1e-6, rel_tol=0):
            raise ValueError("Recomputed contribution differs from validated episode summary.")
        episodes.append({**meta, **result, "days": 21})
        grouped[(row["store_id"], row["product_id"], row["policy"], row["scenario"])] = f
        for phase, (a, b) in PHASES.items():
            p = f.loc[f["episode_day"].between(a, b)]
            phases.append({**meta, "phase": phase, "days": len(p), "contribution": float(p["contribution"].sum()),
                **service(p), "mean_closing_inventory": float(p["closing_inventory"].mean()),
                "mean_order_quantity": float(p["order_quantity"].mean()), "mean_price_multiplier": float(p["price_multiplier"].mean()),
                "fallback_days": int(p["fallback_used"].sum()), "repair_days": int(p["repair_attempted"].sum())})
    episode = pd.DataFrame(episodes)
    lookup = {(r["store_id"], r["product_id"], r["policy"], r["scenario"]): r for r in episodes}
    paired, controls, shock_control = [], [], []
    for (store, product, policy, scenario), f in grouped.items():
        if scenario == "control":
            continue
        control = grouped[(store, product, policy, "control")]
        meta = dict(store_id=store, product_id=product, policy=policy, scenario=scenario)
        rec.append({**meta, **recovery(f, control)})
        behavior.append({**meta, **behavioral_response(f, control)})
        s, c = lookup[(store, product, policy, scenario)], lookup[(store, product, policy, "control")]
        shock_control.append({**meta, "contribution_shock_minus_control": s["contribution"] - c["contribution"],
                              "fill_rate_shock_minus_control_pp": 100 * (s["fill_rate"] - c["fill_rate"])})
    for (store, product), _ in episode.groupby(KEY, sort=False):
        l0 = lookup[(store, product, "llm_with_fallback", "control")]
        for baseline in ("adaptive", "fixed"):
            b0 = lookup[(store, product, baseline, "control")]
            controls.append(dict(store_id=store, product_id=product, comparator=baseline,
                contribution_difference=l0["contribution"] - b0["contribution"],
                relative_gain_percent=relative_gain(l0["contribution"], b0["contribution"]),
                fill_rate_difference_pp=100 * (l0["fill_rate"] - b0["fill_rate"])))
            for scenario in ("demand_surge", "demand_decline", "delivery_disruption"):
                l, b = lookup[(store, product, "llm_with_fallback", scenario)], lookup[(store, product, baseline, scenario)]
                paired.append(dict(store_id=store, product_id=product, scenario=scenario, comparator=baseline,
                    comparison_role="primary" if baseline == "adaptive" else "secondary",
                    llm_contribution=l["contribution"], baseline_contribution=b["contribution"],
                    contribution_difference=l["contribution"] - b["contribution"],
                    relative_gain_percent=relative_gain(l["contribution"], b["contribution"]),
                    control_adjusted_contribution=interaction(l["contribution"], l0["contribution"], b["contribution"], b0["contribution"]),
                    fill_rate_difference_pp=100 * (l["fill_rate"] - b["fill_rate"]),
                    control_adjusted_fill_rate_pp=100 * interaction(l["fill_rate"], l0["fill_rate"], b["fill_rate"], b0["fill_rate"]),
                    closing_inventory_difference=l["mean_closing_inventory"] - b["mean_closing_inventory"]))
    paired = pd.DataFrame(paired)
    summaries = []
    for (scenario, comparator), f in paired.groupby(["scenario", "comparator"], sort=False):
        result = dict(scenario=scenario, comparator=comparator, matched_blocks=len(f))
        for column, prefix in (("contribution_difference", "raw"), ("control_adjusted_contribution", "control_adjusted")):
            v = f[column]
            result.update({prefix + "_" + k: val for k, val in dict(mean=float(v.mean()), median=float(v.median()),
                minimum=float(v.min()), maximum=float(v.max()), positive=int((v > 0).sum()), zero=int((v == 0).sum()), negative=int((v < 0).sum())).items()})
        result.update(mean_fill_rate_difference_pp=float(f["fill_rate_difference_pp"].mean()),
                      mean_control_adjusted_fill_rate_pp=float(f["control_adjusted_fill_rate_pp"].mean()))
        summaries.append(result)
    return dict(episode_metrics=episode, paired_shock_contrasts=paired, control_comparisons=pd.DataFrame(controls),
        policy_shock_minus_control=pd.DataFrame(shock_control), per_scenario_summaries=pd.DataFrame(summaries),
        phase_summaries=pd.DataFrame(phases), action_traces=frame, behavioral_response=pd.DataFrame(behavior), recovery=pd.DataFrame(rec))


def request_metrics(attempts):
    if len(attempts) != 396 or attempts.duplicated(["matrix_index", "date", "request_kind"]).any():
        raise ValueError("Expected 396 distinct primary/repair request records.")
    rows = []
    for index, f in attempts.groupby("matrix_index", sort=True):
        if (f["request_kind"] == "primary").sum() != 21:
            raise ValueError("Each complete LLM episode must retain its 21 primary attempts.")
        row = dict(matrix_index=int(index), **{k: f.iloc[0][k] for k in [*KEY, "scenario"]},
            physical_attempts=len(f), input_tokens=int(f["input_tokens"].sum()), output_tokens=int(f["output_tokens"].sum()),
            cost_credits=float(f["cost_credits"].sum()), mean_latency_seconds=float(f["latency_seconds"].mean()),
            median_latency_seconds=float(f["latency_seconds"].median()), p95_latency_seconds=float(f["latency_seconds"].quantile(.95)),
            total_serial_api_seconds=float(f["latency_seconds"].sum()))
        for kind in ("primary", "repair"):
            p = f.loc[f["request_kind"] == kind]
            row[kind + "_attempts"] = len(p)
            row[kind + "_cost_credits"] = float(p["cost_credits"].sum())
        rows.append(row)
    return pd.DataFrame(rows)
