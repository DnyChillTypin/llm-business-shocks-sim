"""Build the Report 2 PDF from report2/ sources and Stage 5 analysis outputs (no model calls).

1. Generate LaTeX number macros and tables from results/report2/analysis/tables (no hand-typed results).
2. Assemble a build directory with sources, figures, the local LNCS class/style and generated files.
3. Compile (pdflatex, bibtex, pdflatex x2; no shell escape, no package installation) and check the log.
4. Write the PDF, page renders, a source bundle and a verification record to docs/report2/final/.
5. Optionally rebuild from the source bundle in isolation and compare page counts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "report2"
ANALYSIS = ROOT / "results/report2/analysis"
BUILD = ROOT / "results/report2/report/build"
FINAL = ROOT / "docs/report2/final"
TEMPLATE = ROOT / "docs/assets/LaTeX2e+Proceedings+Template+ZIP"
MIKTEX = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/MiKTeX/miktex/bin/x64"
SCENARIOS = ["control", "demand_surge", "demand_decline", "delivery_disruption"]
SHOCKS = SCENARIOS[1:]
SCENARIO_TEX = {"control": "Control", "demand_surge": "Demand surge", "demand_decline": "Demand decline",
                "delivery_disruption": "Delivery disruption"}


# ---------------------------------------------------------------- formatting

def num(x, digits=0, sign=False):
    """LaTeX number: thousands separators, true minus sign, optional explicit plus."""
    if pd.isna(x):
        return "--"
    text = f"{abs(x):,.{digits}f}".replace(",", "{,}")
    if round(x, digits) < 0:
        return f"$-${text}"
    return f"$+${text}" if sign and round(x, digits) > 0 else text


def pct(x, digits=1):
    return "--" if pd.isna(x) else f"{100 * x:.{digits}f}\\%"


def frac(a, b):
    return f"{int(a)}/{int(b)}"


# ---------------------------------------------------------------- macros

class Values(dict):
    """Typeset macro values (key -> LaTeX) with provenance: `source[key] = (source file, derivation)`."""

    def __init__(self):
        super().__init__()
        self.source: dict[str, tuple[str, str]] = {}

    def add(self, key: str, value: str, source: str, derivation: str) -> None:
        self[key] = value
        self.source[key] = (source, derivation)


def filters_text(row, keys) -> str:
    return ", ".join(f"{k}={row[k]}" for k in keys)


LEGACY_STATUS = "docs/results/stage6/status.json"
LEGACY_CONTRASTS = "docs/results/stage6/paired_shock_contrasts.csv"
PROTOCOL_FILE = "configs/report2/protocol.json"
MANIFEST_FILE = "results/report2/analysis/analysis_manifest.json"


def tables_file(name: str) -> str:
    return f"results/report2/analysis/tables/{name}.csv"


def build_macros(t: dict, manifest: dict, legacy: dict) -> Values:
    v = Values()

    def stats(prefix, table, keys):
        src = tables_file(table)
        for _, r in t[table].iterrows():
            base = ".".join([prefix] + [str(r[k]) for k in keys] + [r["measure"], r["scenario"]])
            where = "row " + filters_text(r, keys + ["scenario", "measure"])
            d = 1 if r["measure"] == "fill_rate_diff_pp" else 0
            for s in ("mean", "median", "min", "max"):
                v.add(f"{base}.{s}", num(r[s], d), src, f"{where}; column {s} ({d} dp)")
                v.add(f"{base}.{s}s", num(r[s], d, sign=True), src, f"{where}; column {s} ({d} dp, signed)")
            v.add(f"{base}.pos", str(int(r["n_positive"])), src, f"{where}; column n_positive")
            v.add(f"{base}.neg", str(int(r["n_negative"])), src, f"{where}; column n_negative")
            v.add(f"{base}.n", str(int(r["n_blocks"])), src, f"{where}; column n_blocks")
            v.add(f"{base}.posfrac", frac(r["n_positive"], r["n_blocks"]), src, f"{where}; n_positive/n_blocks")

    stats("main", "main_summary", [])
    stats("hist", "history_summary", ["ablation"])
    stats("histad", "history_vs_adaptive_summary", ["history"])
    stats("el", "elasticity_summary", ["elasticity"])
    stats("elx", "elasticity_summary_excluding_timeout_deviation", ["elasticity"])

    src = tables_file("gap_decomposition")
    for _, r in t["gap_decomposition"].iterrows():
        b = f"gap.{r['setting']}.{r['scenario']}"
        where = "row " + filters_text(r, ["setting", "scenario"])
        for c in ("diff_contribution", "diff_revenue", "diff_cogs", "diff_gross_margin", "diff_holding_cost",
                  "diff_sales", "diff_total_ordered", "diff_mean_inventory"):
            v.add(f"{b}.{c}", num(r[c]), src, f"{where}; column {c} (LLM minus adaptive, block mean)")
        v.add(f"{b}.holding_share", pct(r["holding_share_of_gap"], 0), src, f"{where}; column holding_share_of_gap")
        for c in ("llm_discount_days", "adaptive_discount_days", "diff_premium_days"):
            v.add(f"{b}.{c}", num(r[c], 1), src, f"{where}; column {c} (1 dp)")
        v.add(f"{b}.diff_price", num(r["diff_mean_price_multiplier"], 3), src,
              f"{where}; column diff_mean_price_multiplier")
        for c in ("llm_mean_inventory", "adaptive_mean_inventory"):
            v.add(f"{b}.{c}", num(r[c]), src, f"{where}; column {c}")
        v.add(f"{b}.inventory_ratio", num(r["llm_mean_inventory"] / r["adaptive_mean_inventory"], 1), src,
              f"{where}; llm_mean_inventory / adaptive_mean_inventory")

    src = tables_file("main_outcome_levels")
    for _, r in t["main_outcome_levels"].iterrows():
        for p in ("llm", "adaptive", "fixed"):
            d = {"fill_rate": None, "mean_price_multiplier": 3, "stockout_days": 2, "lost_sales": 1,
                 "discount_days": 1, "premium_days": 1}.get(r["outcome"], 0)
            v.add(f"lvl.{r['scenario']}.{r['outcome']}.{p}", pct(r[p]) if d is None else num(r[p], d), src,
                  f"row {filters_text(r, ['scenario', 'outcome'])}; column {p} (mean over 36 blocks)")

    src = tables_file("reliability")
    for _, r in t["reliability"].iterrows():
        b = f"rel.{r['setting']}"
        where = f"row setting={r['setting']}"
        for c in ("branches", "scheduled_decisions", "completed_decisions", "first_pass_valid", "repair_attempts",
                  "successful_repairs", "fallback_days", "api_attempts", "input_tokens", "output_tokens",
                  "branches_with_fallback"):
            v.add(f"{b}.{c}", num(r[c]), src, f"{where}; column {c}")
        for c in ("first_pass_valid_share", "repair_attempt_share", "successful_repair_share",
                  "repair_success_rate", "fallback_share"):
            v.add(f"{b}.{c}", pct(r[c]), src, f"{where}; column {c}")
        v.add(f"{b}.attempts_per_decision", num(r["attempts_per_decision"], 2), src, f"{where}; column attempts_per_decision")
        v.add(f"{b}.known_credits", num(r["known_credits"], 3), src, f"{where}; column known_credits")
        v.add(f"{b}.credits_per_branch", num(r["credits_per_branch"], 4), src, f"{where}; column credits_per_branch")
        v.add(f"{b}.api_seconds_per_decision", num(r["api_seconds_per_decision"], 1), src,
              f"{where}; column api_seconds_per_decision")
    distinct = t["reliability"][t["reliability"]["setting"] != "main_diagnostic"]  # main_diagnostic is a subset of main
    v.add("rel.total.completed_decisions", num(distinct["completed_decisions"].sum()), src,
          "sum of completed_decisions over settings except main_diagnostic (a subset of main)")

    ops = t["operational_accounting"]
    src = tables_file("operational_accounting")
    for _, r in ops.iterrows():
        b = f"ops.{r['cohort']}"
        for c in ("ledger_attempts", "final_evidence_attempts", "attempts_in_interrupted_runs",
                  "unknown_charge_attempts", "recoveries"):
            v.add(f"{b}.{c}", num(r[c]), src, f"row cohort={r['cohort']}; column {c}")
        for c in ("known_credits", "unknown_charge_reserves", "total_exposure"):
            v.add(f"{b}.{c}", num(r[c], 3), src, f"row cohort={r['cohort']}; column {c}")
    for c, d in (("ledger_attempts", 0), ("known_credits", 3), ("unknown_charge_reserves", 3), ("total_exposure", 3),
                 ("recoveries", 0), ("attempts_in_interrupted_runs", 0)):
        v.add(f"ops.total.{c}", num(ops[c].sum(), d), src, f"sum of column {c} over the three cohorts")
    v.add("ops.project_exposure", num(manifest["project_exposure_credits"], 3), MANIFEST_FILE,
          "project_exposure_credits: ledger sum of settled charges plus max(reserve, charge) for unsettled attempts")
    v.add("ops.project_remaining", num(20 - manifest["project_exposure_credits"], 3), MANIFEST_FILE,
          "20-credit cap minus project_exposure_credits")

    rs = t["restart_summary"]
    src = tables_file("restart_summary")
    for _, r in rs.iterrows():
        for c in rs.columns:
            if c == "cohort":
                continue
            v.add(f"rst.{r['cohort']}.{c}", num(r[c], 3 if c == "held_credits" else 0), src,
                  f"row cohort={r['cohort']}; column {c} (from recovery*/recovery_proposal.json)")
    ev = t["restart_events"]
    codes = sorted(int(x) for x in ev.loc[ev["cause_group"] == "server_error", "http_status"].dropna())
    v.add("rst.total.server_error_http", " and ".join(str(x) for x in codes), tables_file("restart_events"),
          "http_status of events with cause_group=server_error, sorted")
    total = rs.set_index("cohort").loc["total"]
    if total["cause_other"] or total["restart_events"] - total["restarts_with_reserve"] != total["cause_no_failed_request"]:
        raise ValueError("Report text assumes every restart without a failed request is the only kind without a reserve")

    rec = t["recovery"]
    src = tables_file("recovery")
    for _, r in rec[(rec.scope == "all_blocks")].iterrows():
        b = f"rec.{r['group']}.{r['elasticity']}.{r['scenario']}"
        where = "row " + filters_text(r, ["group", "elasticity", "scenario", "scope"])
        v.add(f"{b}.share", pct(r["recovered_share"], 0), src, f"{where}; column recovered_share")
        v.add(f"{b}.frac", frac(r["recovered"], r["trajectories"]), src, f"{where}; recovered/trajectories")
        v.add(f"{b}.delay", num(r["median_delay_if_recovered"], 1), src, f"{where}; column median_delay_if_recovered")

    var = t["main_realization_variability"]
    src = tables_file("main_realization_variability")
    for _, r in var.iterrows():
        b = f"var.{r['scenario']}"
        where = f"row scenario={r['scenario']}"
        v.add(f"{b}.median_range", num(r["median_realization_range"]), src, f"{where}; column median_realization_range")
        v.add(f"{b}.max_range", num(r["max_realization_range"]), src, f"{where}; column max_realization_range")
        v.add(f"{b}.median_abs_contrast", num(r["median_abs_raw_contrast"]), src, f"{where}; column median_abs_raw_contrast")
        v.add(f"{b}.real_pos", str(int(r["realization_level_positive"])), src, f"{where}; column realization_level_positive")
        v.add(f"{b}.sign_disagree", str(int(r["blocks_with_sign_disagreement"])), src,
              f"{where}; column blocks_with_sign_disagreement")
    v.add("var.real_pos_total", str(int(var["realization_level_positive"].sum())), src,
          "sum of column realization_level_positive over the four conditions")
    v.add("var.realizations_total", str(int(var["realizations"].sum())), src,
          "sum of column realizations over the four conditions")

    main = t["main_block_contrasts"]
    src = tables_file("main_block_contrasts")
    v.add("main.cells_llm_ahead", str(int((main["raw_vs_adaptive"] > 0).sum())), src, "count of rows with raw_vs_adaptive > 0")
    v.add("main.cells_total", str(len(main)), src, "number of block-condition rows")

    el = t["elasticity_summary"]
    raw = el[el.measure == "raw_vs_adaptive"]
    v.add("el.max_pos", str(int(raw["n_positive"].max())), tables_file("elasticity_summary"),
          "max of n_positive over rows with measure=raw_vs_adaptive")
    if int(raw.loc[raw.scenario == "control", "n_positive"].max()) != 0:
        raise ValueError("Report text states the LLM policy is never ahead under control in the elasticity cohort")

    dev = t["timeout_deviation_branches"]
    keys = ["elasticity", "scenario", "measure"]
    both = el.merge(t["elasticity_summary_excluding_timeout_deviation"], on=keys, suffixes=("", "_x"))
    src = (f"{tables_file('elasticity_summary')} vs "
           f"{tables_file('elasticity_summary_excluding_timeout_deviation')}")
    max_shift = (both["mean"] - both["mean_x"]).abs().max()
    v.add("dev.max_mean_shift", num(max_shift), src,
          "max over matching rows of |mean - mean excluding deviation branches|")
    v.add("dev.max_mean_shift_bound", num(math.ceil(max_shift / 10) * 10), src,
          "max_mean_shift rounded up to the next multiple of 10, so the text can say 'less than'")
    v.add("dev.sign_count_changes", "no" if ((both["n_positive"] == both["n_positive_x"]).all()
                                             and (both["n_negative"] == both["n_negative_x"]).all()) else "some",
          src, "'no' if n_positive and n_negative agree in every matching row")
    src = tables_file("timeout_deviation_branches")
    v.add("dev.branches", str(len(dev)), src, "number of rows (branches with a request completed after 90 s)")
    v.add("dev.max_latency", num(dev["latency_max"].max(), 1), src, "max of column latency_max")
    v.add("dev.min_latency", num(dev["latency_max"].min(), 1), src, "min of column latency_max")

    for k in ("llm_branches", "baseline_branches", "prefix_groups", "prefix_groups_with_single_prefix",
              "prefix_groups_with_single_restored_state", "daily_rows"):
        v.add(f"int.{k}", num(manifest[k]), MANIFEST_FILE, f"field {k} (load_evidence integrity checks)")
    v.add("int.diagnostic_blocks", str(len(manifest["diagnostic_blocks"])), MANIFEST_FILE,
          "length of field diagnostic_blocks")

    # Analytic margin effect of a price multiplier m at elasticity e, from the frozen simulator settings:
    # contribution per unit of reference demand is (m - c) * m^-e with c the purchase-cost ratio.
    protocol = json.loads((ROOT / PROTOCOL_FILE).read_text(encoding="utf-8"))
    c = protocol["simulator"]["purchase_cost_ratio"]
    for e in (0.75, 1.5, 2.25):
        for m, name in ((0.9, "discount"), (1.1, "premium")):
            v.add(f"econ.{e}.{name}", pct((m - c) * m ** -e / (1 - c) - 1, 1).replace("-", "$-$", 1), PROTOCOL_FILE,
                  f"analytic: (m - c) * m^-e / (1 - c) - 1 with m={m}, e={e}, c=simulator.purchase_cost_ratio={c}")
            v.add(f"econ.{e}.{name}_volume", pct(m ** -e - 1, 1).replace("-", "$-$", 1), PROTOCOL_FILE,
                  f"analytic: m^-e - 1 with m={m}, e={e}")
    v.add("econ.cost_ratio", pct(c, 0), PROTOCOL_FILE, "simulator.purchase_cost_ratio")

    f = legacy["findings"]
    for key, field in (("raw_pos", "raw_shock_positive"), ("adj_pos", "control_adjusted_shock_positive"),
                       ("first_pass", "first_pass_valid"), ("repairs", "successful_repairs"),
                       ("fallback", "fallback_days"), ("diverged", "pre_shock_llm_divergent_conditions")):
        v.add(f"legacy.{key}", str(f[field]), LEGACY_STATUS, f"findings.{field}")
    v.add("legacy.first_pass_share", pct(f["first_pass_valid"] / 252), LEGACY_STATUS,
          "findings.first_pass_valid / 252 legacy decisions")
    lc = pd.read_csv(ROOT / LEGACY_CONTRASTS)
    lc = lc[(lc["comparator"] == "adaptive") & (lc["comparison_role"] == "primary")]
    for key, fn in (("inv_min", "min"), ("inv_max", "max")):
        v.add(f"legacy.{key}", num(getattr(lc["closing_inventory_difference"], fn)()), LEGACY_CONTRASTS,
              f"{fn} of closing_inventory_difference over rows comparator=adaptive, comparison_role=primary")
    return v


def macros_tex(values: dict[str, str]) -> str:
    lines = ["% Generated by scripts/build_report2.py from results/report2/analysis. Do not edit.",
             "\\makeatletter",
             "\\newcommand{\\val}[1]{\\ifcsname r2@#1\\endcsname\\csname r2@#1\\endcsname"
             "\\else\\PackageError{report2}{Unknown value #1}{}\\textbf{??}\\fi}"]
    for key in sorted(values):
        if not re.fullmatch(r"[A-Za-z0-9_.]+", key):
            raise ValueError(f"Unsafe macro key {key}")
        lines.append(f"\\expandafter\\def\\csname r2@{key}\\endcsname{{{values[key]}}}")
    lines.append("\\makeatother")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- tables

def table_main(t) -> str:
    s = t["main_summary"].set_index(["measure", "scenario"])
    rows = []
    for sc in SCENARIOS:
        raw = s.loc[("raw_vs_adaptive", sc)]
        fill = s.loc[("fill_rate_diff_pp", sc)]
        if sc == "control":
            adj = "-- & --"
        else:
            a = s.loc[("adjusted_vs_adaptive", sc)]
            adj = f"{num(a['mean'], sign=True)} & {frac(a['n_positive'], a['n_blocks'])}"
        rows.append(f"{SCENARIO_TEX[sc]} & {num(raw['mean'])} & {num(raw['median'])} & "
                    f"{num(raw['min'])} to {num(raw['max'])} & {frac(raw['n_positive'], raw['n_blocks'])} & "
                    f"{adj} & {num(fill['mean'], 1, sign=True)} \\\\")
    return "\n".join(rows) + "\n"


def table_mechanism(t) -> str:
    g = t["gap_decomposition"]
    g = g[g.setting == "main"].set_index("scenario")
    rows = []
    for sc in SCENARIOS:
        r = g.loc[sc]
        rows.append(f"{SCENARIO_TEX[sc]} & {num(r['diff_contribution'])} & {num(r['diff_revenue'], sign=True)} & "
                    f"{num(r['diff_cogs'], sign=True)} & {num(r['diff_holding_cost'], sign=True)} & "
                    f"{pct(r['holding_share_of_gap'], 0)} & {num(r['llm_discount_days'], 1)} / "
                    f"{num(r['adaptive_discount_days'], 1)} & {num(r['llm_mean_inventory'])} / "
                    f"{num(r['adaptive_mean_inventory'])} \\\\")
    return "\n".join(rows) + "\n"


def table_history(t) -> str:
    s = t["history_summary"].set_index(["ablation", "measure", "scenario"])
    g = t["gap_decomposition"].set_index(["setting", "scenario"])
    rows = []
    for sc in SCENARIOS:
        cells = []
        for ab in ("frozen", "none"):
            r = s.loc[(ab, "full_minus_ablation", sc)]
            cells.append(f"{num(r['mean'])} & {num(r['median'])} & {frac(r['n_positive'], r['n_blocks'])}")
        # Full history restricted to the same 18 diagnostic blocks as the frozen and no-history variants.
        disc = " / ".join(num(g.loc[(st, sc), "llm_discount_days"], 1)
                          for st in ("main_diagnostic", "history_frozen", "history_none"))
        rows.append(f"{SCENARIO_TEX[sc]} & {cells[0]} & {cells[1]} & {disc} \\\\")
    return "\n".join(rows) + "\n"


def table_elasticity(t) -> str:
    s = t["elasticity_summary"].set_index(["elasticity", "measure", "scenario"])
    rows = []
    for e in (0.75, 1.5, 2.25):
        raw = " & ".join(f"{num(s.loc[(e, 'raw_vs_adaptive', sc), 'mean'])} "
                         f"({int(s.loc[(e, 'raw_vs_adaptive', sc), 'n_positive'])})" for sc in SCENARIOS)
        adj = " & ".join(f"{num(s.loc[(e, 'adjusted_vs_adaptive', sc), 'mean'], sign=True)} "
                         f"({int(s.loc[(e, 'adjusted_vs_adaptive', sc), 'n_positive'])})" for sc in SHOCKS)
        rows.append(f"{e} & {raw} & {adj} \\\\")
    return "\n".join(rows) + "\n"


RELIABILITY_NAMES = {"main": "Full history", "main_diagnostic": "Full history", "history_frozen": "Frozen history",
                     "history_none": "No history", "elasticity_0.75": "Elasticity 0.75",
                     "elasticity_2.25": "Elasticity 2.25"}


def table_reliability(t) -> str:
    rows = []
    for _, r in t["reliability"].iterrows():
        rows.append(f"{RELIABILITY_NAMES[r['setting']]} ({int(r['blocks'])}) & {num(r['completed_decisions'])} & "
                    f"{pct(r['first_pass_valid_share'])} & {pct(r['repair_attempt_share'])} & "
                    f"{pct(r['successful_repair_share'])} & {pct(r['repair_success_rate'])} & "
                    f"{pct(r['fallback_share'])} & {num(r['attempts_per_decision'], 2)} & "
                    f"{num(r['credits_per_branch'], 4)} \\\\")
        if r["setting"] == "main":
            rows.append("\\addlinespace")
    return "\n".join(rows) + "\n"


def table_operations(t) -> str:
    rows = []
    names = {"main": "Main", "history": "History", "elasticity": "Elasticity"}
    rs = t["restart_summary"].set_index("cohort")
    ops = t["operational_accounting"]
    for _, r in ops.iterrows():
        x = rs.loc[r["cohort"]]
        rows.append(f"{names[r['cohort']]} & {num(r['ledger_attempts'])} & {num(r['attempts_in_interrupted_runs'])} & "
                    f"{num(x['restart_events'])} & {num(x['distinct_branches'])} & {num(r['known_credits'], 3)} & "
                    f"{num(r['unknown_charge_reserves'], 3)} & {num(r['total_exposure'], 3)} \\\\")
    x = rs.loc["total"]
    rows.append("\\midrule")
    rows.append(f"Total & {num(ops['ledger_attempts'].sum())} & {num(ops['attempts_in_interrupted_runs'].sum())} & "
                f"{num(x['restart_events'])} & {num(x['distinct_branches'])} & {num(ops['known_credits'].sum(), 3)} & "
                f"{num(ops['unknown_charge_reserves'].sum(), 3)} & {num(ops['total_exposure'].sum(), 3)} \\\\")
    return "\n".join(rows) + "\n"


def table_recovery(t) -> str:
    r = t["recovery"]
    r = r[(r.scope == "all_blocks") & (r.elasticity == 1.5)].set_index(["group", "scenario"])
    rows = []
    for group, name in (("llm_main", "LLM policy"), ("adaptive", "Adaptive rule"), ("fixed", "Fixed rule")):
        cells = []
        for sc in SHOCKS:
            x = r.loc[(group, sc)]
            cells.append(f"{pct(x['recovered_share'], 0)} ({frac(x['recovered'], x['trajectories'])}) & "
                         f"{num(x['median_delay_if_recovered'], 1)}")
        rows.append(f"{name} & " + " & ".join(cells) + " \\\\")
    return "\n".join(rows) + "\n"


TABLES = {"tab_main": table_main, "tab_mechanism": table_mechanism, "tab_history": table_history,
          "tab_elasticity": table_elasticity, "tab_reliability": table_reliability,
          "tab_operations": table_operations, "tab_recovery": table_recovery}

# Source and derivation of every generated table, for the manuscript claim map.
TABLE_SOURCES = {
    "tab_main": (tables_file("main_summary"),
                 "rows scenario; raw_vs_adaptive mean, median, min to max, n_positive/n_blocks; adjusted_vs_adaptive "
                 "mean and n_positive/n_blocks (shocks only); fill_rate_diff_pp mean"),
    "tab_mechanism": (tables_file("gap_decomposition"),
                      "rows setting=main by scenario; diff_contribution, diff_revenue, diff_cogs, diff_holding_cost, "
                      "holding_share_of_gap, llm/adaptive_discount_days, llm/adaptive_mean_inventory"),
    "tab_history": (f"{tables_file('history_summary')}; {tables_file('gap_decomposition')}",
                    "history_summary rows ablation in (frozen, none), measure=full_minus_ablation: mean, median, "
                    "n_positive/n_blocks; discount days = gap_decomposition llm_discount_days for settings "
                    "main_diagnostic / history_frozen / history_none (all 18 diagnostic blocks)"),
    "tab_elasticity": (tables_file("elasticity_summary"),
                       "rows elasticity x scenario; raw_vs_adaptive mean (n_positive); adjusted_vs_adaptive mean "
                       "(n_positive) for shocks"),
    "tab_reliability": (tables_file("reliability"),
                        "rows setting; blocks, completed_decisions, first_pass_valid_share, repair_attempt_share, "
                        "successful_repair_share, repair_success_rate, fallback_share, attempts_per_decision, "
                        "credits_per_branch"),
    "tab_operations": (f"{tables_file('operational_accounting')}; {tables_file('restart_summary')}",
                       "operational_accounting ledger_attempts, attempts_in_interrupted_runs, known_credits, "
                       "unknown_charge_reserves, total_exposure; restart_summary restart_events, distinct_branches; "
                       "Total row sums the cohorts"),
    "tab_recovery": (tables_file("recovery"),
                     "rows scope=all_blocks, elasticity=1.5, group in (llm_main, adaptive, fixed) x shock; "
                     "recovered_share (recovered/trajectories), median_delay_if_recovered"),
}


# ---------------------------------------------------------------- manuscript claim map

def strip_comments(tex: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*$", "", line) for line in tex.splitlines())


def used_value_keys(tex: str) -> list[str]:
    return sorted(set(re.findall(r"\\val\{([^}]*)\}", strip_comments(tex))))


def used_tables(tex: str) -> list[str]:
    return sorted(set(re.findall(r"\\input\{generated/(tab_\w+)(?:\.tex)?\}", strip_comments(tex))))


def plain(latex: str) -> str:
    """Readable rendering of a typeset value or table row."""
    text = latex.replace("$-$", "-").replace("$+$", "+").replace("{,}", ",").replace("\\%", "%")
    return re.sub(r"\s*\\\\\s*$", "", text).replace(" & ", " | ").strip()


def manuscript_claim_map(values: Values, tex: str, table_text: dict[str, str]) -> pd.DataFrame:
    """One row per \\val key used in the manuscript and per generated table row; fail on any unmapped item."""
    keys = used_value_keys(tex)
    undefined = [k for k in keys if k not in values]
    unmapped = [k for k in keys if k in values and not all(values.source.get(k, ("", "")))]
    tables = used_tables(tex)
    untraced = [n for n in tables if n not in table_text or n not in TABLE_SOURCES]
    if undefined or unmapped or untraced:
        raise ValueError(f"Manuscript items without a source mapping: undefined={undefined}, "
                         f"unmapped={unmapped}, tables={untraced}")
    rows = [{"key": k, "kind": "value", "value": plain(values[k]), "latex": values[k],
             "source": values.source[k][0], "derivation": values.source[k][1]} for k in keys]
    for name in tables:
        lines = [l for l in table_text[name].splitlines() if l.strip().endswith("\\\\")]
        for i, line in enumerate(lines, 1):
            rows.append({"key": f"{name}.row{i}", "kind": "table_row", "value": plain(line), "latex": line.strip(),
                         "source": TABLE_SOURCES[name][0], "derivation": TABLE_SOURCES[name][1]})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- build

def tex(tool: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    exe = MIKTEX / f"{tool}.exe"
    cmd = [str(exe if exe.exists() else tool)]
    if tool == "pdflatex":
        cmd += ["-interaction=nonstopmode", "-halt-on-error", "-disable-installer", "-no-shell-escape"]
    return subprocess.run(cmd + args, cwd=cwd, capture_output=True, text=True, errors="replace")


def compile_pdf(build: Path) -> dict:
    steps = [("pdflatex", ["main.tex"]), ("bibtex", ["main"]), ("pdflatex", ["main.tex"]), ("pdflatex", ["main.tex"])]
    for tool, args in steps:
        result = tex(tool, args, build)
        if result.returncode != 0:
            log = (build / "main.log").read_text(errors="replace") if (build / "main.log").exists() else result.stdout
            errors = [l for l in log.splitlines() if l.startswith("!")][:10]
            raise RuntimeError(f"{tool} failed: {errors or result.stdout[-2000:]}")
    log = (build / "main.log").read_text(errors="replace")
    blg = (build / "main.blg").read_text(errors="replace") if (build / "main.blg").exists() else ""
    overfull = re.findall(r"Overfull \\hbox \((\d+\.?\d*)pt too wide\)", log)
    pages = re.search(r"Output written on main\.pdf \((\d+) pages?", log)
    return {
        "pages": int(pages.group(1)) if pages else None,
        "undefined_references": len(re.findall(r"Reference `[^']+' on page \d+ undefined", log)),
        "undefined_citations": len(re.findall(r"Citation `[^']+' on page \d+ undefined", log)),
        "rerun_needed": "Rerun to get" in log,
        "missing_characters": len(re.findall(r"Missing character", log)),
        "overfull_hbox_over_1pt": sum(float(x) > 1.0 for x in overfull),
        "overfull_hbox_max_pt": max((float(x) for x in overfull), default=0.0),
        "bibtex_warnings": len(re.findall(r"^Warning--", blg, re.M)),
        "font": "Times (newtx)" if "newtxtext.sty" in log else "Computer Modern (newtx incomplete or absent)",
    }


NEWTX = "\\usepackage{newtxtext}\\usepackage[varvw]{newtxmath}\n"


def assemble(build: Path, values: dict, t: dict) -> dict[str, str]:
    if build.exists():
        shutil.rmtree(build)
    (build / "generated").mkdir(parents=True)
    (build / "figures").mkdir()
    for p in SOURCE.iterdir():
        if p.is_file():
            shutil.copy2(p, build / p.name)
    for name in ("llncs.cls", "splncs04.bst"):
        src = TEMPLATE / name
        if not src.exists():
            raise FileNotFoundError(f"LNCS template file missing: {src} (download the Springer LNCS template)")
        shutil.copy2(src, build / name)
    for p in (ANALYSIS / "figures").glob("*.pdf"):
        shutil.copy2(p, build / "figures" / p.name)
    (build / "generated/values.tex").write_text(macros_tex(values), encoding="utf-8")
    (build / "generated/fonts.tex").write_text(NEWTX, encoding="utf-8")
    text = {}
    for name, fn in TABLES.items():
        # The closing rule lives in the generated file: \bottomrule directly after \input fails in tabulars.
        text[name] = fn(t)
        (build / "generated" / f"{name}.tex").write_text(text[name] + "\\bottomrule\n", encoding="utf-8")
    return text


def compile_with_font_fallback(build: Path) -> dict:
    """Prefer Times (newtx); fall back to the default font when the local newtx installation is incomplete."""
    try:
        return compile_pdf(build)
    except RuntimeError as error:
        message = str(error)
        # Only font-installation failures qualify: missing font metrics or a missing package/support file.
        if not re.search(r"not loadable: Metric|File `[^']+\.(sty|tex|fd|cfg|enc|map)' not found", message) \
                or "generated/" in message:
            raise
        (build / "generated/fonts.tex").write_text(
            "% newtx is incomplete in this TeX installation; using the default font.\n", encoding="utf-8")
        checks = compile_pdf(build)
        checks["font_fallback_reason"] = message[:300]
        return checks


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-bundle-check", action="store_true")
    args = parser.parse_args(argv)

    manifest = json.loads((ANALYSIS / "analysis_manifest.json").read_text(encoding="utf-8"))
    t = {p.stem: pd.read_csv(p) for p in (ANALYSIS / "tables").glob("*.csv") if p.stem != "episodes"}
    legacy = json.loads((ROOT / "docs/results/stage6/status.json").read_text(encoding="utf-8"))
    values = build_macros(t, manifest, legacy)

    table_text = assemble(BUILD, values, t)
    # Fails before compiling if the manuscript uses a value or table without a source mapping.
    claims = manuscript_claim_map(values, (SOURCE / "main.tex").read_text(encoding="utf-8"), table_text)
    checks = compile_with_font_fallback(BUILD)

    FINAL.mkdir(parents=True, exist_ok=True)
    pdf = FINAL / "report2.pdf"
    shutil.copy2(BUILD / "main.pdf", pdf)
    claims.to_csv(FINAL / "claim_map.csv", index=False)
    pages_dir = FINAL / "pages"
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir()
    subprocess.run([str(MIKTEX / "pdftoppm.exe"), "-png", "-r", "70", str(pdf), str(pages_dir / "page")], check=True)

    bundle = FINAL / "report2_source_bundle.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(BUILD.rglob("*")):
            if p.is_file() and p.suffix in {".tex", ".bib", ".cls", ".bst", ".pdf"} and p.name != "main.pdf":
                z.write(p, p.relative_to(BUILD).as_posix())

    isolated = None
    if not args.skip_bundle_check:
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(bundle) as z:
                z.extractall(tmp)
            isolated = compile_pdf(Path(tmp))
            isolated["same_page_count"] = isolated["pages"] == checks["pages"]

    record = {
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "pdf_sha256": sha256(pdf), "bundle_sha256": sha256(bundle),
        "analysis_manifest_sha256": sha256(ANALYSIS / "analysis_manifest.json"),
        "analysis_git_commit": manifest.get("git_commit"),
        "values_generated": len(values),
        "claim_map": {"path": "docs/report2/final/claim_map.csv", "sha256": sha256(FINAL / "claim_map.csv"),
                      "values_used_in_manuscript": int((claims["kind"] == "value").sum()),
                      "generated_table_rows": int((claims["kind"] == "table_row").sum()),
                      "unmapped_items": 0},
        "analysis_evidence_source": manifest.get("evidence_source"),
        "checks": checks, "isolated_rebuild": isolated,
        "model_calls_made": 0,
    }
    (FINAL / "build_verification.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))
    problems = (checks["undefined_references"] or checks["undefined_citations"] or checks["missing_characters"]
                or checks["overfull_hbox_over_1pt"] or checks["rerun_needed"]
                or (isolated is not None and not isolated["same_page_count"]))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
