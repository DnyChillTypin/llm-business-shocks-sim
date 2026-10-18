"""Publication exports from saved analysis tables, with explicit units and censoring."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

POLICIES = ("fixed", "adaptive", "llm_with_fallback")
LABELS = {"fixed": "Fixed", "adaptive": "Adaptive", "llm_with_fallback": "LLM + fallback"}
COLORS = {"fixed": "#7b8794", "adaptive": "#007e87", "llm_with_fallback": "#c35a31"}
SCENARIOS = ("control", "demand_surge", "demand_decline", "delivery_disruption")
SHORT = {"control": "Control", "demand_surge": "Surge", "demand_decline": "Decline", "delivery_disruption": "Delivery delay"}


def make_figures(tables, native_reasoning, native_coverage, target):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 11,
                         "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
    outputs = []
    def save(fig, name, title):
        fig.suptitle(title, fontsize=14, y=.995)
        fig.tight_layout(rect=(0, .04, 1, .95))
        for extension in ("png", "pdf"):
            path = target / f"{name}.{extension}"
            fig.savefig(path, dpi=160, bbox_inches="tight", metadata={"Creator": "Stage 6 reproducible analysis"})
            outputs.append(path)
        plt.close(fig)

    paired = tables["paired_shock_contrasts"].query("comparator == 'adaptive'").reset_index(drop=True)
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), sharey=True)
    names = [r.store_id + "/" + r.product_id + " · " + SHORT[r.scenario] for r in paired.itertuples()]
    for ax, column, title in zip(axes, ("contribution_difference", "control_adjusted_contribution"), ("Raw LLM minus adaptive", "Shock-minus-control interaction")):
        ax.axvline(0, color="#555", lw=1)
        ax.scatter(paired[column], np.arange(9), c=[{"S001": "#286b9b", "S004": "#7a5195", "S003": "#4c8c55"}[s] for s in paired.store_id], s=48, zorder=3)
        ax.set_yticks(np.arange(9), names, fontsize=9)
        ax.set_xlabel("Contribution difference (dataset monetary units)")
        ax.set_title(title)
        ax.grid(axis="x", alpha=.2)
    axes[0].invert_yaxis()
    save(fig, "contribution_contrasts", "Nine matched shock comparisons · three selected blocks, no population inference")

    traces, phases = tables["action_traces"], tables["phase_summaries"]
    series = list(traces[["store_id", "product_id"]].drop_duplicates().itertuples(index=False, name=None))
    fig, axes = plt.subplots(2, 3, figsize=(14, 7), squeeze=False)
    for col, (store, product) in enumerate(series):
        f = phases.query("store_id == @store and product_id == @product")
        for policy in POLICIES:
            p = f.query("policy == @policy").set_index(["scenario", "phase"])
            keys = [(s, phase) for s in SCENARIOS for phase in ("pre_shock", "shock", "post_shock")]
            axes[0, col].plot(range(12), [p.loc[k, "contribution"] for k in keys], marker="o", ms=3, label=LABELS[policy], color=COLORS[policy])
            axes[1, col].plot(range(12), [100 * p.loc[k, "fill_rate"] for k in keys], marker="o", ms=3, color=COLORS[policy])
        axes[0, col].set_title(store + "/" + product)
        for ax in axes[:, col]:
            ax.set_xticks(range(12), [SHORT[s] + "\n" + p for s in SCENARIOS for p in ("Pre", "Shock", "Post")], rotation=55, ha="right", fontsize=7)
            ax.grid(alpha=.2)
        axes[0, col].set_ylabel("Phase contribution (dataset units)")
        axes[1, col].set_ylabel("Demand-weighted fill rate (%)")
        axes[1, col].set_ylim(0, 105)
    fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="lower center", ncol=3, frameon=False)
    save(fig, "phase_outcomes", "Contribution and service · seven days per phase, every selected block shown")

    for column, name, ylabel in (("closing_inventory", "inventory_traces", "Closing inventory (units, before arrivals)"),
                                  ("order_quantity", "order_traces", "Executed order (units)"),
                                  ("price_multiplier", "price_traces", "Executed price / reference price")):
        fig, axes = plt.subplots(3, 4, figsize=(15, 8), sharex=True, squeeze=False)
        for row, (store, product) in enumerate(series):
            for col, scenario in enumerate(SCENARIOS):
                ax = axes[row, col]
                f = traces.query("store_id == @store and product_id == @product and scenario == @scenario")
                for policy in POLICIES:
                    p = f.query("policy == @policy").sort_values("episode_day")
                    ax.plot(p.episode_day, p[column], lw=1.35, color=COLORS[policy], label=LABELS[policy])
                    if policy == "llm_with_fallback":
                        fallback = p.loc[p.fallback_used]
                        ax.scatter(fallback.episode_day, fallback[column], marker="x", c="black", s=32, zorder=5)
                ax.axvspan(7.5, 14.5, color="#e3bd72", alpha=.22)
                ax.set_title(store + "/" + product + " · " + SHORT[scenario], fontsize=9)
                ax.grid(alpha=.15)
                ax.set_xticks((1, 7, 14, 21))
                if row == 2:
                    ax.set_xlabel("Episode day")
                if col == 0:
                    ax.set_ylabel({"closing_inventory": "Closing stock (units)", "order_quantity": "Order (units)",
                                   "price_multiplier": "Price / reference price"}[column], fontsize=9)
                if column == "price_multiplier":
                    ax.set_ylim(.87, 1.13)
                    ax.set_yticks((.9, 1., 1.1))
        fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="lower center", ncol=3, frameon=False)
        save(fig, name, ylabel + " · shading: shock days 8–14; ×: adaptive fallback")

    rec = tables["recovery"]
    labels = [(store, product, p) for store, product in series for p in POLICIES]
    values = np.full((9, 3), np.nan)
    for i, (store, product, policy) in enumerate(labels):
        for j, scenario in enumerate(SCENARIOS[1:]):
            r = rec.query("store_id == @store and product_id == @product and policy == @policy and scenario == @scenario").iloc[0]
            if r.recovered:
                values[i, j] = r.recovery_delay_days
    fig, ax = plt.subplots(figsize=(9, 6))
    cmap = plt.get_cmap("YlGnBu").copy()
    cmap.set_bad("#ededed")
    im = ax.imshow(np.ma.masked_invalid(values), cmap=cmap, vmin=1, vmax=5, aspect="auto")
    for (i, j), value in np.ndenumerate(values):
        ax.text(j, i, "C" if np.isnan(value) else str(int(value)), ha="center", va="center", color="white" if value >= 4 else "black")
    ax.set_xticks(range(3), [SHORT[s] for s in SCENARIOS[1:]])
    ax.set_yticks(range(9), [s + "/" + p + " · " + LABELS[k] for s, p, k in labels], fontsize=9)
    fig.colorbar(im, ax=ax, label="Observed recovery delay (start day − 14)", ticks=range(1, 6))
    save(fig, "recovery", "Recovery relative to same-policy control · C: not confirmed by day 21 (censored)")

    costs = tables["llm_episode_reliability_costs"]
    llm = traces.loc[traces.policy == "llm_with_fallback"]
    counts = (int((~llm.repair_attempted).sum()), int((llm.repair_attempted & ~llm.fallback_used).sum()), int(llm.fallback_used.sum()))
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    left = 0
    for value, label, color in zip(counts, ("First-pass valid", "Valid repair", "Adaptive fallback"), ("#007e87", "#e3bd72", "#c35a31")):
        axes[0].barh([0], [value], left=left, color=color, label=label)
        axes[0].text(left + value / 2, 0, str(value), ha="center", va="center", fontsize=9)
        left += value
    axes[0].set_yticks([])
    axes[0].set_xlabel("252 decision opportunities")
    axes[0].legend(loc="upper center", bbox_to_anchor=(.5, -.2), fontsize=8)
    x = np.arange(len(costs))
    axes[1].plot(x, costs.median_latency_seconds, "o-", label="Request median")
    axes[1].plot(x, costs.p95_latency_seconds, "s--", label="Request p95")
    axes[1].set_ylabel("Seconds per request (descriptive)")
    axes[1].legend(fontsize=8)
    axes[2].bar(x, costs.primary_cost_credits, label="Primary")
    axes[2].bar(x, costs.repair_cost_credits, bottom=costs.primary_cost_credits, label="Repair")
    axes[2].set_ylabel("Estimated gateway credits")
    axes[2].legend(fontsize=8)
    for ax in axes[1:]:
        ax.set_xticks(x, costs.matrix_index.astype(str), fontsize=8)
        ax.set_xlabel("Frozen LLM matrix position")
    save(fig, "reliability_costs", "Operating reliability and request expense · fallback remains in primary outcomes")

    sensitivity = tables["baseline_elasticity_summary"]
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    for col, (store, product) in enumerate(series):
        f = sensitivity.query("store_id == @store and product_id == @product")
        for scenario in SCENARIOS:
            p = f.query("scenario == @scenario").pivot(index="elasticity", columns="policy", values=["contribution", "fill_rate"])
            axes[0, col].plot(p.index, p["contribution"]["adaptive"] - p["contribution"]["fixed"], "o-", label=SHORT[scenario])
            axes[1, col].plot(p.index, 100 * (p["fill_rate"]["adaptive"] - p["fill_rate"]["fixed"]), "o-")
        axes[0, col].set_title(store + "/" + product)
        axes[0, col].set_ylabel("Adaptive − fixed contribution (dataset units)")
        axes[1, col].set_ylabel("Adaptive − fixed fill rate (pp)")
        for ax in axes[:, col]:
            ax.axhline(0, color="#666", lw=.7)
            ax.axvline(1.5, color="#666", lw=.7, ls=":")
            ax.set_xticks((.75, 1.5, 2.25))
            ax.set_xlabel("Assumed elasticity (1.5 is primary)")
            ax.grid(alpha=.2)
    fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="lower center", ncol=4, frameon=False)
    save(fig, "baseline_sensitivity", "Baseline-only assumption sensitivity · no claim about LLM robustness")

    fig, axes = plt.subplots(2, 3, figsize=(13, 6), sharex=True)
    cases = (("S001", "P0001", "delivery_disruption"), ("S004", "P0006", "demand_surge"))
    for row, (store, product, scenario) in enumerate(cases):
        f = traces.query("store_id == @store and product_id == @product")
        for col, field in enumerate(("closing_inventory", "order_quantity", "price_multiplier")):
            ax = axes[row, col]
            for policy, condition, label, color, ls in (("llm_with_fallback", scenario, "LLM shock + fallback", COLORS["llm_with_fallback"], "-"),
                    ("adaptive", scenario, "Adaptive shock", COLORS["adaptive"], "-"),
                    ("llm_with_fallback", "control", "LLM control", "#777", "--")):
                p = f.query("policy == @policy and scenario == @condition").sort_values("episode_day")
                ax.plot(p.episode_day, p[field], color=color, ls=ls, lw=1.3, label=label)
                if policy == "llm_with_fallback" and condition == scenario:
                    fall = p.loc[p.fallback_used]
                    ax.scatter(fall.episode_day, fall[field], c="black", marker="x", s=35, zorder=5)
            ax.axvspan(7.5, 14.5, alpha=.18, color="#e3bd72")
            ax.set_title(store + "/" + product + " · " + SHORT[scenario] + "\n" + field.replace("_", " "), fontsize=9)
            ax.set_ylabel("Units" if field != "price_multiplier" else "Price / reference price", fontsize=9)
            ax.grid(alpha=.15)
            ax.set_xticks((1, 7, 14, 21))
            ax.set_xlabel("Episode day")
    fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="lower center", ncol=3, frameon=False)
    save(fig, "diagnostic_examples", "Post-outcome diagnostic illustrations · all conditions remain visible in full tables/traces")

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), gridspec_kw={"width_ratios": [1, 2]})
    status_counts = native_coverage.status.value_counts()
    axes[0].bar(["Validated", "Failed", "Deferred"], [status_counts.get("validated_complete", 0), status_counts.get("failed", 0), status_counts.get("deferred", 0)], color=["#007e87", "#c35a31", "#aaa"])
    axes[0].set_ylabel("Native tasks (coverage, not a pooled score)")
    axes[1].barh(np.arange(len(native_reasoning)), native_reasoning.accuracy * 100, color="#286b9b")
    axes[1].set_yticks(np.arange(len(native_reasoning)), [s.replace("firm:", "") + (" · labels" if s == "firm:finer" else " · extension" if s == "firm:factset" else "") for s in native_reasoning.task], fontsize=9)
    axes[1].set_xlabel("Native accuracy (%) · denominators retained in table")
    axes[1].set_xlim(0, 105)
    axes[1].invert_yaxis()
    save(fig, "native_coverage_reasoning", "Native coverage and dataset-specific accuracy · ICBE failed; four Retail tasks deferred")
    return outputs
