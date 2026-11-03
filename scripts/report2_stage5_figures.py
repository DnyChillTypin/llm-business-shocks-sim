"""Static print figures (PDF + PNG) for Report 2 Stage 5. Called by scripts/run_report2_stage5.py.

Palette: validated reference slots 1-3 (all-pairs PASS, light surface); elasticity uses a one-hue ordinal
blue ramp (ordinal PASS). Every multi-series figure has a legend; the CSV tables are the table view.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
ORDINAL = {0.75: "#86b6ef", 1.5: "#2a78d6", 2.25: "#104281"}
SCENARIOS = ["control", "demand_surge", "demand_decline", "delivery_disruption"]
LABEL = {"control": "Control", "demand_surge": "Demand\nsurge", "demand_decline": "Demand\ndecline",
         "delivery_disruption": "Delivery\ndisruption"}
SETTING_LABEL = {"main": "Main (full history, e=1.5)", "history_frozen": "Frozen history",
                 "history_none": "No history", "elasticity_0.75": "Elasticity 0.75",
                 "elasticity_2.25": "Elasticity 2.25"}
WIDTH = 6.5  # inches, LaTeX text width

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
    "font.size": 8.5, "axes.titlesize": 9, "axes.titleweight": "bold", "axes.labelsize": 8.5,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.labelcolor": INK2, "axes.facecolor": SURFACE,
    "figure.facecolor": SURFACE, "savefig.facecolor": SURFACE, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "grid.linestyle": "-",
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
    "legend.fontsize": 8, "lines.linewidth": 2, "lines.solid_capstyle": "round",
    "pdf.fonttype": 42,
})


def money(ax, axis="y"):
    fmt = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}".replace("-", "\u2212"))
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def zero(ax, axis="y"):
    (ax.axhline if axis == "y" else ax.axvline)(0, color=AXIS, linewidth=1, zorder=1)


def header(ax, title, ncol=3):
    """Title on top, legend on its own row directly beneath it (never overlapping)."""
    ax.set_title(title, loc="left", pad=20)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=ncol, borderaxespad=0.2, handlelength=1.2)


def strip(ax, positions, values_list, color, offset=0.0, width=0.22, label=None):
    """Block-level dots (jittered, ringed) with an ink median tick."""
    rng = np.random.default_rng(7)
    for i, (x, values) in enumerate(zip(positions, values_list)):
        v = np.asarray(values, dtype=float)
        jitter = rng.uniform(-width / 2, width / 2, len(v))
        ax.scatter(x + offset + jitter, v, s=22, color=color, edgecolor=SURFACE, linewidth=0.8, zorder=3,
                   label=label if i == 0 else None, alpha=0.9)
        ax.plot([x + offset - width * 0.75, x + offset + width * 0.75], [np.median(v)] * 2,
                color=INK, linewidth=2, zorder=4)


def save(fig, out: Path, name: str) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for ext in ("pdf", "png"):
        path = out / f"{name}.{ext}"
        fig.savefig(path, dpi=200, bbox_inches="tight")
        files.append(f"figures/{path.name}")
    plt.close(fig)
    return files


# ---------------------------------------------------------------- figures

def fig_main_contrasts(t, out):
    m = t["main_block_contrasts"]
    fig, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.8), gridspec_kw={"width_ratios": [4, 3]})
    ax = axes[0]
    strip(ax, range(4), [m.loc[m.scenario == s, "raw_vs_adaptive"] for s in SCENARIOS], BLUE)
    ax.set_xticks(range(4), [LABEL[s] for s in SCENARIOS])
    ax.set_title("LLM minus adaptive contribution", loc="left")
    ax.set_ylabel("Days 8\u201321 contribution difference")
    ax = axes[1]
    strip(ax, range(3), [m.loc[m.scenario == s, "adjusted_vs_adaptive"] for s in SCENARIOS[1:]], BLUE)
    ax.set_xticks(range(3), [LABEL[s] for s in SCENARIOS[1:]])
    ax.set_title("Control-adjusted interaction", loc="left")
    for ax in axes:
        zero(ax); money(ax); ax.grid(axis="x", visible=False)
    fig.text(0.0, -0.04, "Each dot is one of 36 blocks (three LLM realizations averaged); black tick = median. "
             "Above zero favours the LLM policy.", color=INK2, fontsize=7.5)
    fig.tight_layout()
    return save(fig, out, "fig_main_contrasts")


def fig_gap_decomposition(t, out):
    g = t["gap_decomposition"]
    g = g[g.setting == "main"].set_index("scenario").loc[SCENARIOS]
    margin, holding = g["diff_gross_margin"].to_numpy(), -g["diff_holding_cost"].to_numpy()
    fig, ax = plt.subplots(figsize=(WIDTH, 2.3))
    y = np.arange(4)[::-1]
    ax.barh(y, margin, height=0.42, color=BLUE, edgecolor=SURFACE, linewidth=1.5, label="Gross margin (pricing and volume)", zorder=3)
    ax.barh(y, holding, left=margin, height=0.42, color=ORANGE, edgecolor=SURFACE, linewidth=1.5,
            label="Extra holding cost", zorder=3)
    for yi, total, disc_l, disc_a, inv_l, inv_a in zip(y, margin + holding, g["llm_discount_days"],
                                                      g["adaptive_discount_days"], g["llm_mean_inventory"],
                                                      g["adaptive_mean_inventory"]):
        ax.text(total - 60, yi, f"{total:,.0f}".replace("-", "\u2212"), va="center", ha="right", color=INK, fontsize=8)
        ax.text(60, yi, f"discount days {disc_l:.1f} vs {disc_a:.1f} \u00b7 mean stock {inv_l:,.0f} vs {inv_a:,.0f}",
                va="center", ha="left", color=INK2, fontsize=7.5)
    ax.set_yticks(y, [LABEL[s].replace("\n", " ") for s in SCENARIOS])
    ax.set_xlim(min(margin + holding) * 1.25, 3600)
    zero(ax, "x"); money(ax, "x"); ax.grid(axis="y", visible=False)
    ax.set_xlabel("LLM minus adaptive, days 8\u201321 (mean of 36 blocks)")
    ax.set_xticks([-3000, -2000, -1000, 0])
    header(ax, "Where the contribution gap comes from (main cohort)", ncol=2)
    fig.tight_layout()
    return save(fig, out, "fig_gap_decomposition")


def fig_history(t, out):
    h = t["history_block_contrasts"]
    fig, ax = plt.subplots(figsize=(WIDTH, 2.8))
    for ab, color, off in (("frozen", BLUE, -0.18), ("none", ORANGE, 0.18)):
        part = h[h.ablation == ab]
        strip(ax, range(4), [part.loc[part.scenario == s, "full_minus_ablation"] for s in SCENARIOS], color,
              offset=off, width=0.26, label="Full minus frozen history" if ab == "frozen" else "Full minus no history")
    ax.set_xticks(range(4), [LABEL[s] for s in SCENARIOS])
    zero(ax); money(ax); ax.grid(axis="x", visible=False)
    ax.set_ylabel("Contribution difference")
    header(ax, "Does full rolling history help? (18 diagnostic blocks)", ncol=2)
    fig.text(0.0, -0.04, "Below zero: the reduced-history policy earned more. Black tick = median.", color=INK2, fontsize=7.5)
    fig.tight_layout()
    return save(fig, out, "fig_history_contrasts")


def fig_elasticity(t, out):
    rows = t["elasticity_blocks"]
    fig, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.8), gridspec_kw={"width_ratios": [4, 3]})
    for e, off in ((0.75, -0.24), (1.5, 0.0), (2.25, 0.24)):
        part = rows[rows.elasticity == e]
        strip(axes[0], range(4), [part.loc[part.scenario == s, "raw_vs_adaptive"] for s in SCENARIOS],
              ORDINAL[e], offset=off, width=0.2, label=f"Elasticity {e}")
        strip(axes[1], range(3), [part.loc[part.scenario == s, "adjusted_vs_adaptive"] for s in SCENARIOS[1:]],
              ORDINAL[e], offset=off, width=0.2)
    axes[0].set_xticks(range(4), [LABEL[s] for s in SCENARIOS])
    axes[1].set_xticks(range(3), [LABEL[s] for s in SCENARIOS[1:]])
    header(axes[0], "LLM minus adaptive")
    axes[1].set_title("Control-adjusted interaction", loc="left", pad=20)
    axes[0].set_ylabel("Contribution difference")
    for ax in axes:
        zero(ax); money(ax); ax.grid(axis="x", visible=False)
    fig.text(0.0, -0.04, "18 diagnostic blocks per elasticity; fresh LLM and baseline runs in each setting. "
             "Black tick = median.", color=INK2, fontsize=7.5)
    fig.tight_layout()
    return save(fig, out, "fig_elasticity_contrasts")


def fig_reliability(t, out):
    r = t["reliability"].set_index("setting")
    order = ["main", "history_frozen", "history_none", "elasticity_0.75", "elasticity_2.25"]
    r = r.loc[order]
    parts = [("First response valid", r["first_pass_valid"] / r["completed_decisions"], BLUE, "#ffffff"),
             ("Valid after one repair", r["successful_repairs"] / r["completed_decisions"], ORANGE, "#ffffff"),
             ("Adaptive fallback", r["fallback_days"] / r["completed_decisions"], AQUA, INK)]
    fig, ax = plt.subplots(figsize=(WIDTH, 2.3))
    y = np.arange(len(order))[::-1]
    left = np.zeros(len(order))
    for name, share, color, text in parts:
        ax.barh(y, share, left=left, height=0.5, color=color, edgecolor=SURFACE, linewidth=1.5, label=name, zorder=3)
        for yi, l, s in zip(y, left, share):
            if s >= 0.12:
                ax.text(l + s / 2, yi, f"{s:.0%}", ha="center", va="center", color=text, fontsize=7.5)
        left += share.to_numpy()
    for yi, f in zip(y, r["fallback_days"] / r["completed_decisions"]):
        ax.text(1.01, yi, f"fallback {f:.1%}", va="center", ha="left", color=INK2, fontsize=7.5)
    ax.set_yticks(y, [SETTING_LABEL[s] for s in order])
    ax.set_xlim(0, 1); ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Share of executed decisions (main 6,048; each other row 3,024)")
    header(ax, "How each executed decision was produced")
    fig.tight_layout()
    return save(fig, out, "fig_reliability")


def fig_event_daily(t, out):
    e = t["main_event_daily"]
    fig, axes = plt.subplots(2, 4, figsize=(WIDTH, 3.9), sharex=True, sharey="row")
    for j, s in enumerate(SCENARIOS):
        for i, (col, ylabel) in enumerate((("contribution", "Daily contribution"), ("closing_inventory", "Closing inventory"))):
            ax = axes[i, j]
            if s != "control":
                ax.axvspan(7.5, 14.5, color=GRID, alpha=0.5, linewidth=0, zorder=0)
            for policy, color, name in (("llm", BLUE, "LLM policy"), ("adaptive", ORANGE, "Adaptive rule")):
                d = e[(e.policy == policy) & (e.scenario == s)]
                ax.plot(d["day"], d[col], color=color, label=name, zorder=3)
            if i == 0:
                ax.set_title(LABEL[s].replace("\n", " "), loc="left", fontsize=8.5)
            if j == 0:
                ax.set_ylabel(ylabel)
            money(ax)
            ax.set_xticks([8, 11, 14, 17, 21])
    for ax in axes[1]:
        ax.set_xlabel("Day")
    fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="upper left", bbox_to_anchor=(0.0, 1.06), ncol=2)
    fig.text(0.0, -0.02, "Mean over 36 blocks (LLM realizations averaged first). Shaded: shock window, days 8\u201314.",
             color=INK2, fontsize=7.5)
    fig.tight_layout()
    return save(fig, out, "fig_event_daily")


def fig_recovery(t, out):
    r = t["recovery"]
    sel = {"llm_main": ("LLM policy", BLUE), "adaptive": ("Adaptive rule", ORANGE), "fixed": ("Fixed rule", AQUA)}
    r = r[(r.elasticity == 1.5) & (r.scope == "all_blocks") & r.group.isin(sel)]
    fig, ax = plt.subplots(figsize=(WIDTH, 2.4))
    shocks = SCENARIOS[1:]
    y = np.arange(3)[::-1]
    h = 0.24
    for k, (group, (name, color)) in enumerate(sel.items()):
        part = r[r.group == group].set_index("scenario").loc[shocks]
        pos = y + (1 - k) * (h + 0.03)
        ax.barh(pos, part["recovered_share"], height=h, color=color, label=name, zorder=3)
        for p, share, n, tot in zip(pos, part["recovered_share"], part["recovered"], part["trajectories"]):
            ax.text(share + 0.01, p, f"{share:.0%} ({n}/{tot})", va="center", ha="left", color=INK2, fontsize=7)
    ax.set_yticks(y, [LABEL[s].replace("\n", " ") for s in shocks])
    ax.set_xlim(0, 1.18); ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Trajectories meeting the frozen recovery rule by day 21")
    header(ax, "Recovery after the shock window (main blocks)")
    fig.tight_layout()
    return save(fig, out, "fig_recovery")


def make_figures(tables: dict, out: Path) -> list[str]:
    t = dict(tables)
    c = tables["all_block_contrasts"]
    t["elasticity_blocks"] = c[c["diagnostic"] & (c["history"] == "full")]
    files = []
    for fn in (fig_main_contrasts, fig_gap_decomposition, fig_history, fig_elasticity, fig_reliability,
               fig_event_daily, fig_recovery):
        files += fn(t, out)
    return files
