"""Static print figures (PDF + PNG) for Report 2 Stage 5. Called by scripts/run_report2_stage5.py.

Sized for the LNCS text width (122 mm) so they print at 1:1 with ~7 pt text. Titles and explanations live
in the LaTeX captions. Palette: validated reference slots 1-3 (all-pairs PASS); elasticity uses a one-hue
ordinal blue ramp (ordinal PASS). Every multi-series figure has a legend; the CSV tables are the table view.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

SURFACE, INK, INK2, MUTED, GRID, AXIS = "#ffffff", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
ORDINAL = {0.75: "#86b6ef", 1.5: "#2a78d6", 2.25: "#104281"}
SCENARIOS = ["control", "demand_surge", "demand_decline", "delivery_disruption"]
LABEL = {"control": "Control", "demand_surge": "Demand\nsurge", "demand_decline": "Demand\ndecline",
         "delivery_disruption": "Delivery\ndisruption"}
SETTING_LABEL = {"main": "Main, full history (36)", "main_diagnostic": "Full history (18)",
                 "history_frozen": "Frozen history (18)", "history_none": "No history (18)",
                 "elasticity_0.75": "Elasticity 0.75 (18)", "elasticity_2.25": "Elasticity 2.25 (18)"}
WIDTH = 4.8  # inches: LNCS text width (122 mm)

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
    "font.size": 7, "axes.titlesize": 7.5, "axes.titleweight": "bold", "axes.labelsize": 7,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.7, "axes.labelcolor": INK2, "axes.facecolor": SURFACE,
    "figure.facecolor": SURFACE, "savefig.facecolor": SURFACE, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
    "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "xtick.major.size": 2.5, "ytick.major.size": 2.5,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5, "grid.linestyle": "-",
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
    "legend.fontsize": 6.5, "lines.linewidth": 1.5, "lines.solid_capstyle": "round",
    "pdf.fonttype": 42,
})


def money(ax, axis="y"):
    fmt = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}".replace("-", "\u2212"))
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def zero(ax, axis="y"):
    (ax.axhline if axis == "y" else ax.axvline)(0, color=AXIS, linewidth=0.9, zorder=1)


def legend_top(ax, ncol=3, handles=None):
    """Legend on its own row above the plot area (titles are in the LaTeX caption)."""
    kwargs = {"handles": handles} if handles else {}
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), ncol=ncol, borderaxespad=0.2,
              handlelength=1.1, columnspacing=1.2, **kwargs)


def strip(ax, positions, values_list, color, offset=0.0, width=0.22, label=None):
    """Block-level dots (jittered, ringed) with an ink median tick."""
    rng = np.random.default_rng(7)
    for i, (x, values) in enumerate(zip(positions, values_list)):
        v = np.asarray(values, dtype=float)
        jitter = rng.uniform(-width / 2, width / 2, len(v))
        ax.scatter(x + offset + jitter, v, s=9, color=color, edgecolor=SURFACE, linewidth=0.5, zorder=3,
                   label=label if i == 0 else None, alpha=0.9)
        ax.plot([x + offset - width * 0.75, x + offset + width * 0.75], [np.median(v)] * 2,
                color=INK, linewidth=1.6, zorder=4)


def save(fig, out: Path, name: str) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for ext in ("pdf", "png"):
        path = out / f"{name}.{ext}"
        fig.savefig(path, dpi=300, bbox_inches="tight", pad_inches=0.02)
        files.append(f"figures/{path.name}")
    plt.close(fig)
    return files


# ---------------------------------------------------------------- figures

def fig_main_contrasts(t, out):
    m = t["main_block_contrasts"]
    fig, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.2), gridspec_kw={"width_ratios": [4, 3]})
    strip(axes[0], range(4), [m.loc[m.scenario == s, "raw_vs_adaptive"] for s in SCENARIOS], BLUE)
    axes[0].set_xticks(range(4), [LABEL[s] for s in SCENARIOS])
    axes[0].set_title("(a) LLM minus adaptive", loc="left")
    axes[0].set_ylabel("Contribution difference, days 8\u201321")
    strip(axes[1], range(3), [m.loc[m.scenario == s, "adjusted_vs_adaptive"] for s in SCENARIOS[1:]], BLUE)
    axes[1].set_xticks(range(3), [LABEL[s] for s in SCENARIOS[1:]])
    axes[1].set_title("(b) Control-adjusted interaction", loc="left")
    for ax in axes:
        zero(ax); money(ax); ax.grid(axis="x", visible=False)
    fig.tight_layout(w_pad=1.5)
    return save(fig, out, "fig_main_contrasts")


def fig_gap_decomposition(t, out):
    g = t["gap_decomposition"]
    g = g[g.setting == "main"].set_index("scenario").loc[SCENARIOS]
    margin, holding = g["diff_gross_margin"].to_numpy(), -g["diff_holding_cost"].to_numpy()
    fig, ax = plt.subplots(figsize=(WIDTH, 1.55))
    y = np.arange(4)[::-1]
    ax.barh(y, margin, height=0.5, color=BLUE, edgecolor=SURFACE, linewidth=1.2,
            label="Gross margin (pricing and volume)", zorder=3)
    ax.barh(y, holding, left=margin, height=0.5, color=ORANGE, edgecolor=SURFACE, linewidth=1.2,
            label="Extra holding cost", zorder=3)
    for yi, total in zip(y, margin + holding):
        ax.text(total - 50, yi, f"{total:,.0f}".replace("-", "\u2212"), va="center", ha="right", color=INK)
    ax.set_yticks(y, [LABEL[s].replace("\n", " ") for s in SCENARIOS])
    ax.set_xlim(min(margin + holding) * 1.22, 120)
    ax.set_xticks([-3000, -2000, -1000, 0])
    zero(ax, "x"); money(ax, "x"); ax.grid(axis="y", visible=False)
    ax.set_xlabel("LLM minus adaptive (mean of 36 blocks)")
    legend_top(ax, ncol=2)
    fig.tight_layout()
    return save(fig, out, "fig_gap_decomposition")


def fig_history(t, out):
    h = t["history_block_contrasts"]
    fig, ax = plt.subplots(figsize=(WIDTH, 2.1))
    for ab, color, off, name in (("frozen", BLUE, -0.18, "Full minus frozen history"),
                                 ("none", ORANGE, 0.18, "Full minus no history")):
        part = h[h.ablation == ab]
        strip(ax, range(4), [part.loc[part.scenario == s, "full_minus_ablation"] for s in SCENARIOS], color,
              offset=off, width=0.26, label=name)
    ax.set_xticks(range(4), [LABEL[s].replace("\n", " ") for s in SCENARIOS])
    zero(ax); money(ax); ax.grid(axis="x", visible=False)
    ax.set_ylabel("Contribution difference")
    legend_top(ax, ncol=2)
    fig.tight_layout()
    return save(fig, out, "fig_history_contrasts")


def fig_elasticity(t, out):
    rows = t["elasticity_blocks"]
    fig, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.3), gridspec_kw={"width_ratios": [4, 3]})
    for e, off in ((0.75, -0.25), (1.5, 0.0), (2.25, 0.25)):
        part = rows[rows.elasticity == e]
        strip(axes[0], range(4), [part.loc[part.scenario == s, "raw_vs_adaptive"] for s in SCENARIOS],
              ORDINAL[e], offset=off, width=0.2, label=f"Elasticity {e}")
        strip(axes[1], range(3), [part.loc[part.scenario == s, "adjusted_vs_adaptive"] for s in SCENARIOS[1:]],
              ORDINAL[e], offset=off, width=0.2)
    axes[0].set_xticks(range(4), [LABEL[s] for s in SCENARIOS])
    axes[1].set_xticks(range(3), [LABEL[s] for s in SCENARIOS[1:]])
    axes[0].set_ylabel("Contribution difference")
    axes[1].set_title("(b) Control-adjusted", loc="left", pad=3)
    for ax in axes:
        zero(ax); money(ax); ax.grid(axis="x", visible=False)
    axes[0].set_title("(a) LLM minus adaptive", loc="left", pad=3)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.07),
               handlelength=1.1)
    fig.tight_layout(w_pad=1.5)
    return save(fig, out, "fig_elasticity_contrasts")


def fig_reliability(t, out):
    r = t["reliability"].set_index("setting")
    order = ["main", "main_diagnostic", "history_frozen", "history_none", "elasticity_0.75", "elasticity_2.25"]
    r = r.loc[order]
    parts = [("First response valid", r["first_pass_valid"] / r["completed_decisions"], BLUE, "#ffffff"),
             ("Valid after one repair", r["successful_repairs"] / r["completed_decisions"], ORANGE, "#ffffff"),
             ("Adaptive fallback", r["fallback_days"] / r["completed_decisions"], AQUA, INK)]
    fig, ax = plt.subplots(figsize=(WIDTH, 2.0))
    y = np.arange(len(order))[::-1]
    left = np.zeros(len(order))
    for name, share, color, text in parts:
        ax.barh(y, share, left=left, height=0.55, color=color, edgecolor=SURFACE, linewidth=1.2, label=name, zorder=3)
        for yi, l, s in zip(y, left, share):
            if s >= 0.12:
                ax.text(l + s / 2, yi, f"{s:.0%}", ha="center", va="center", color=text, fontsize=6.5)
        left += share.to_numpy()
    for yi, f in zip(y, r["fallback_days"] / r["completed_decisions"]):
        ax.text(1.01, yi, f"{f:.1%}", va="center", ha="left", color=INK2, fontsize=6.5)
    ax.set_yticks(y, [SETTING_LABEL[s] for s in order])
    ax.set_xlim(0, 1); ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Share of executed decisions")
    legend_top(ax)
    fig.tight_layout()
    return save(fig, out, "fig_reliability")


def fig_event_daily(t, out):
    e = t["main_event_daily"]
    fig, axes = plt.subplots(2, 4, figsize=(WIDTH, 2.9), sharex=True, sharey="row")
    for j, s in enumerate(SCENARIOS):
        for i, (col, ylabel) in enumerate((("contribution", "Daily contribution"), ("closing_inventory", "Closing stock"))):
            ax = axes[i, j]
            if s != "control":
                ax.axvspan(7.5, 14.5, color=GRID, alpha=0.55, linewidth=0, zorder=0)
            for policy, color, name in (("llm", BLUE, "LLM policy"), ("adaptive", ORANGE, "Adaptive rule")):
                d = e[(e.policy == policy) & (e.scenario == s)]
                ax.plot(d["day"], d[col], color=color, label=name, zorder=3)
            if i == 0:
                ax.set_title(LABEL[s].replace("\n", " "), loc="left", fontsize=7)
            if j == 0:
                ax.set_ylabel(ylabel)
            money(ax)
            ax.set_xticks([8, 14, 21])
    for ax in axes[1]:
        ax.set_xlabel("Day")
    fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="upper left", bbox_to_anchor=(0.0, 1.05), ncol=2,
               handlelength=1.4)
    fig.tight_layout(h_pad=0.6, w_pad=0.4)
    return save(fig, out, "fig_event_daily")


def fig_recovery(t, out):
    r = t["recovery"]
    sel = {"llm_main": ("LLM policy", BLUE), "adaptive": ("Adaptive rule", ORANGE), "fixed": ("Fixed rule", AQUA)}
    r = r[(r.elasticity == 1.5) & (r.scope == "all_blocks") & r.group.isin(sel)]
    fig, ax = plt.subplots(figsize=(WIDTH, 1.9))
    shocks = SCENARIOS[1:]
    y = np.arange(3)[::-1]
    h = 0.25
    for k, (group, (name, color)) in enumerate(sel.items()):
        part = r[r.group == group].set_index("scenario").loc[shocks]
        pos = y + (1 - k) * (h + 0.03)
        ax.barh(pos, part["recovered_share"], height=h, color=color, label=name, zorder=3)
        for p, share, n, tot in zip(pos, part["recovered_share"], part["recovered"], part["trajectories"]):
            ax.text(share + 0.01, p, f"{share:.0%} ({n}/{tot})", va="center", ha="left", color=INK2, fontsize=6)
    ax.set_yticks(y, [LABEL[s].replace("\n", " ") for s in shocks])
    ax.set_xlim(0, 1.2); ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Trajectories meeting the frozen recovery rule by day 21")
    legend_top(ax)
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
