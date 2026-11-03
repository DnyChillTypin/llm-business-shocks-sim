"""Run Report 2 Stage 5 analysis offline (no model calls) and write tables, figures and a claim map.

Outputs go to results/report2/analysis/ (ignored by Git). See src/analysis/report2_stage5.py for definitions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis.report2_stage5 import (  # noqa: E402
    CONDITIONS, OUTCOMES, SHOCKS, add_recovery, block_means, evidence_fingerprint, history_contrasts, llm_settings,
    load_evidence, operational_accounting, paired_contrasts, reliability, restart_events, restart_summary, summarize,
)
from src.research.report2 import read_json  # noqa: E402

# main_diagnostic: main full-history branches restricted to the 18 diagnostic blocks (matched history reference).
SETTING_ORDER = ["main", "main_diagnostic", "history_frozen", "history_none", "elasticity_0.75", "elasticity_2.25"]
CONTRAST_MEASURES = ["raw_vs_adaptive", "adjusted_vs_adaptive", "raw_vs_fixed", "adjusted_vs_fixed",
                     "fill_rate_diff_pp", "lost_sales_diff", "mean_inventory_diff"]


def diagnostic_blocks() -> set[str]:
    sampling = read_json(ROOT / "configs/report2/sampling_manifest.json")
    return {b["block_id"] for b in sampling["evaluation_blocks"] if b["diagnostic_subset"]}


def setting_of(history: str, elasticity: float) -> str:
    if history != "full":
        return f"history_{history}"
    return "main" if elasticity == 1.5 else f"elasticity_{elasticity}"


def build_tables(episodes: pd.DataFrame, daily: pd.DataFrame, integrity: dict) -> tuple[dict, dict]:
    diag = diagnostic_blocks()
    llm = llm_settings(episodes, diag)
    baselines = episodes[episodes["source"] == "baseline"]
    blocks = block_means(llm)
    contrasts = paired_contrasts(blocks, baselines)
    contrasts.insert(0, "setting", [setting_of(h, e) for h, e in zip(contrasts["history"], contrasts["elasticity"])])
    contrasts["diagnostic"] = contrasts["block_id"].isin(diag)
    t = {"all_block_contrasts": contrasts}

    # Integrity: every decision is first-pass valid, a successful repair, or fallback.
    identity_ok = (llm["first_pass_valid"] + llm["successful_repairs"] + llm["fallback_days"]
                   == llm["completed_decisions"]).all()
    if not identity_ok:
        raise ValueError("Decision provenance does not partition completed decisions")

    # RQ1 main cohort (36 blocks).
    main = contrasts[contrasts["setting"] == "main"]
    t["main_block_contrasts"] = main
    t["main_summary"] = summarize(main, ["scenario"], CONTRAST_MEASURES)
    levels = []
    for scenario in CONDITIONS:
        m = main[main["scenario"] == scenario]
        for outcome in OUTCOMES:
            levels.append({"scenario": scenario, "outcome": outcome, "llm": m[outcome].mean(),
                           "adaptive": m[f"{outcome}_adaptive"].mean(), "fixed": m[f"{outcome}_fixed"].mean()})
    t["main_outcome_levels"] = pd.DataFrame(levels)

    # Where the contribution gap comes from: contribution = gross margin - holding cost (exact identity).
    # main_diagnostic restricts the main cohort to the diagnostic blocks, matching the history cohort.
    rows = []
    main_diag = contrasts[(contrasts["setting"] == "main") & contrasts["diagnostic"]]
    groups = list(contrasts.groupby(["setting", "scenario"], sort=False)) + [
        (("main_diagnostic", s), g) for s, g in main_diag.groupby("scenario", sort=False)]
    for (setting, scenario), g in groups:
        diff = {o: (g[o] - g[f"{o}_adaptive"]).mean() for o in
                ("contribution", "revenue", "cogs", "gross_margin", "holding_cost", "sales",
                 "mean_price_multiplier", "discount_days", "premium_days", "mean_inventory", "total_ordered")}
        if abs(diff["contribution"] - (diff["gross_margin"] - diff["holding_cost"])) > 1e-6:
            raise ValueError("Contribution decomposition does not reconcile")
        rows.append({"setting": setting, "scenario": scenario, "n_blocks": len(g),
                     **{f"diff_{k}": v for k, v in diff.items()},
                     "holding_share_of_gap": -diff["holding_cost"] / diff["contribution"],
                     "llm_discount_days": g["discount_days"].mean(), "adaptive_discount_days": g["discount_days_adaptive"].mean(),
                     "llm_mean_inventory": g["mean_inventory"].mean(), "adaptive_mean_inventory": g["mean_inventory_adaptive"].mean()})
    t["gap_decomposition"] = pd.DataFrame(rows)

    # Within-block variability of the three realizations (main).
    real = llm[llm["setting"] == "main"].merge(
        baselines[baselines["policy"] == "adaptive"][["block_id", "scenario", "elasticity", "contribution"]],
        on=["block_id", "scenario", "elasticity"], suffixes=("", "_adaptive"))
    real["raw_vs_adaptive"] = real["contribution"] - real["contribution_adaptive"]
    signs = real.groupby(["scenario", "block_id"])["raw_vs_adaptive"].agg(lambda s: len(set(np.sign(s))) > 1)
    spread = main.assign(range_=main["contribution_max"] - main["contribution_min"])
    t["main_realization_variability"] = pd.DataFrame([{
        "scenario": s,
        "median_realization_range": spread.loc[spread["scenario"] == s, "range_"].median(),
        "max_realization_range": spread.loc[spread["scenario"] == s, "range_"].max(),
        "median_abs_raw_contrast": spread.loc[spread["scenario"] == s, "raw_vs_adaptive"].abs().median(),
        "realization_level_positive": int((real.loc[real["scenario"] == s, "raw_vs_adaptive"] > 0).sum()),
        "realizations": int((real["scenario"] == s).sum()),
        "blocks_with_sign_disagreement": int(signs.loc[s].sum()),
    } for s in CONDITIONS])

    # RQ2 history (18 diagnostic blocks).
    hist = history_contrasts(blocks, diag)
    t["history_block_contrasts"] = hist
    t["history_summary"] = summarize(hist, ["ablation", "scenario"], ["full_minus_ablation", "shock_minus_control",
                                                                      "fill_rate_diff_pp"])
    diag_hist = contrasts[contrasts["diagnostic"] & (contrasts["elasticity"] == 1.5)]
    t["history_vs_adaptive_summary"] = summarize(diag_hist, ["history", "scenario"],
                                                 ["raw_vs_adaptive", "adjusted_vs_adaptive"])

    # RQ4 elasticity (18 diagnostic blocks, fresh LLM and baselines per setting).
    diag_el = contrasts[contrasts["diagnostic"] & (contrasts["history"] == "full")]
    t["elasticity_summary"] = summarize(diag_el, ["elasticity", "scenario"],
                                        ["raw_vs_adaptive", "adjusted_vs_adaptive", "raw_vs_fixed", "fill_rate_diff_pp"])

    # Timeout deviation sensitivity: drop elasticity realizations with a request completed after 90 s.
    flagged = llm[(llm["over_frozen_timeout"] > 0)]
    t["timeout_deviation_branches"] = flagged[["identity", "source", "block_id", "scenario", "elasticity",
                                               "realization", "over_frozen_timeout", "latency_max"]]
    kept = llm[~llm["identity"].isin(flagged["identity"])]
    sens = paired_contrasts(block_means(kept), baselines)
    sens = sens[sens["block_id"].isin(diag) & (sens["history"] == "full") & (sens["elasticity"] != 1.5)]
    t["elasticity_summary_excluding_timeout_deviation"] = summarize(
        sens, ["elasticity", "scenario"], ["raw_vs_adaptive", "adjusted_vs_adaptive"])

    # RQ3 reliability and operations.
    t["reliability"] = reliability(llm, diag).set_index("setting").loc[SETTING_ORDER].reset_index()
    t["operational_accounting"] = operational_accounting(episodes, ROOT)
    t["restart_events"] = restart_events(ROOT)
    t["restart_summary"] = restart_summary(t["restart_events"])
    rs = t["restart_summary"].set_index("cohort")
    ops_restarts = t["operational_accounting"].set_index("cohort")["recoveries"]
    if not (rs.loc[ops_restarts.index, "restart_events"] == ops_restarts).all():
        raise ValueError("Restart events differ from the recovery directories counted in operational accounting")
    unknown = t["operational_accounting"].set_index("cohort")["unknown_charge_attempts"]
    if not (rs.loc[unknown.index, "restarts_with_reserve"] == unknown).all():
        raise ValueError("Restarts holding a reserve differ from unsettled ledger attempts")

    # Recovery (trajectory level, explicit denominators).
    rec = episodes[episodes["scenario"] != "control"].copy()
    rec["group"] = np.where(rec["source"] == "baseline", rec["policy"],
                            [f"llm_{setting_of(h, e)}" for h, e in zip(rec["history"], rec["elasticity"])])
    rows = []
    for (group, elasticity, scenario), g in rec.groupby(["group", "elasticity", "scenario"]):
        for scope, part in (("all_blocks", g), ("diagnostic_blocks", g[g["block_id"].isin(diag)])):
            if part.empty:
                continue
            delays = part["recovery_delay"].dropna()
            rows.append({"group": group, "elasticity": elasticity, "scenario": scenario, "scope": scope,
                         "trajectories": len(part), "recovered": len(delays), "censored": len(part) - len(delays),
                         "recovered_share": len(delays) / len(part),
                         "median_delay_if_recovered": delays.median() if len(delays) else np.nan})
    t["recovery"] = pd.DataFrame(rows)

    # Event-aligned daily trajectories (main): equal-weight blocks, realizations averaged first.
    d = daily[(daily["history"] == "full") & (daily["elasticity"] == 1.5)]
    cols = ["contribution", "closing_inventory", "lost_sales", "demand", "sales"]
    llm_daily = d[d["source"] == "main"].groupby(["block_id", "scenario", "day"])[cols].mean()
    base_daily = d[d["source"] == "baseline"].groupby(["policy", "block_id", "scenario", "day"])[cols].mean()
    event = []
    for name, frame in (("llm", llm_daily), ("adaptive", base_daily.loc["adaptive"]), ("fixed", base_daily.loc["fixed"])):
        e = frame.groupby(["scenario", "day"]).mean().reset_index()
        e.insert(0, "policy", name)
        event.append(e)
    t["main_event_daily"] = pd.concat(event, ignore_index=True)

    t["coverage"] = pd.DataFrame([
        {"cohort": "main (LLM)", "planned": 432, "validated": int((llm["source"] == "main").sum())},
        {"cohort": "history (LLM)", "planned": 432, "validated": int((llm["source"] == "history").sum())},
        {"cohort": "elasticity (LLM)", "planned": 432, "validated": int((llm["source"] == "elasticity").sum())},
        {"cohort": "baselines (adaptive, fixed)", "planned": 576, "validated": len(baselines)},
    ])
    t["episodes"] = episodes.drop(columns=["manifest_scenario", "manifest_history", "manifest_policy"])

    ops = t["operational_accounting"]
    meta = {
        **integrity,
        "decision_provenance_partition_ok": bool(identity_ok),
        "project_exposure_credits": ops.attrs["project_exposure"],
        "timeout_deviation_branches": int(len(flagged)),
        "diagnostic_blocks": sorted(diag),
    }
    return t, meta


# ---------------------------------------------------------------- key findings and claim map

def pick(table, **filters):
    df = table
    for k, v in filters.items():
        df = df[df[k] == v]
    if len(df) != 1:
        raise ValueError(f"Claim lookup is not unique: {filters}")
    return df.iloc[0]


def key_findings(t: dict, meta: dict) -> list[dict]:
    claims = []

    def add(cid, text, table, value, **filters):
        claims.append({"id": cid, "claim": text, "value": value, "table": f"tables/{table}.csv",
                       "filter": json.dumps(filters)})

    for s in CONDITIONS:
        r = pick(t["main_summary"], scenario=s, measure="raw_vs_adaptive")
        add(f"rq1_raw_{s}", f"Main, {s}: LLM minus adaptive contribution, mean over 36 blocks",
            "main_summary", round(r["mean"], 1), scenario=s, measure="raw_vs_adaptive")
        add(f"rq1_raw_pos_{s}", f"Main, {s}: blocks where LLM contribution exceeds adaptive",
            "main_summary", f"{r['n_positive']}/{r['n_blocks']}", scenario=s, measure="raw_vs_adaptive")
    for s in SHOCKS:
        r = pick(t["main_summary"], scenario=s, measure="adjusted_vs_adaptive")
        add(f"rq1_adj_{s}", f"Main, {s}: control-adjusted interaction vs adaptive, mean (positive blocks)",
            "main_summary", f"{r['mean']:.1f} ({r['n_positive']}/{r['n_blocks']})", scenario=s, measure="adjusted_vs_adaptive")
    for s in CONDITIONS:
        r = pick(t["gap_decomposition"], setting="main", scenario=s)
        add(f"mech_{s}", f"Main, {s}: gap = gross-margin diff minus holding diff; holding share; "
            "LLM vs adaptive discount days; LLM vs adaptive mean inventory",
            "gap_decomposition",
            f"{r['diff_contribution']:.0f} = {r['diff_gross_margin']:.0f} - {r['diff_holding_cost']:.0f}; "
            f"{r['holding_share_of_gap']:.0%}; {r['llm_discount_days']:.1f} vs {r['adaptive_discount_days']:.1f} days; "
            f"{r['llm_mean_inventory']:.0f} vs {r['adaptive_mean_inventory']:.0f} units", setting="main", scenario=s)
    for ab in ("frozen", "none"):
        for s in CONDITIONS:
            r = pick(t["history_summary"], ablation=ab, scenario=s, measure="full_minus_ablation")
            add(f"rq2_{ab}_{s}", f"History, {s}: full minus {ab} contribution, mean (blocks where full is higher)",
                "history_summary", f"{r['mean']:.1f} ({r['n_positive']}/{r['n_blocks']})",
                ablation=ab, scenario=s, measure="full_minus_ablation")
    for e in (0.75, 1.5, 2.25):
        for s in CONDITIONS:
            r = pick(t["elasticity_summary"], elasticity=e, scenario=s, measure="raw_vs_adaptive")
            add(f"rq4_raw_{e}_{s}", f"Elasticity {e}, {s}: LLM minus adaptive, mean (positive blocks), 18 blocks",
                "elasticity_summary", f"{r['mean']:.1f} ({r['n_positive']}/{r['n_blocks']})",
                elasticity=e, scenario=s, measure="raw_vs_adaptive")
    for s in CONDITIONS:
        r = pick(t["gap_decomposition"], setting="main_diagnostic", scenario=s)
        add(f"rq2_full_discount_days_{s}", f"Full history on the 18 diagnostic blocks, {s}: LLM mean discount days",
            "gap_decomposition", round(r["llm_discount_days"], 1), setting="main_diagnostic", scenario=s)
    for setting in SETTING_ORDER:
        r = pick(t["reliability"], setting=setting)
        add(f"rq3_{setting}", f"{setting}: first-pass valid / repair attempted / repaired (of decisions) / "
            "repair success (of attempts) / fallback", "reliability",
            f"{r['first_pass_valid_share']:.1%} / {r['repair_attempt_share']:.1%} / "
            f"{r['successful_repair_share']:.1%} / {r['repair_success_rate']:.1%} / {r['fallback_share']:.1%}",
            setting=setting)
    r = pick(t["restart_summary"], cohort="total")
    add("ops_restarts", "Supervised restarts: events / distinct branches / with an unknown-charge reserve",
        "restart_summary", f"{r['restart_events']} / {r['distinct_branches']} / {r['restarts_with_reserve']}",
        cohort="total")
    add("ops_exposure", "Project credit exposure including all reserves (cap 20)", "operational_accounting",
        round(meta["project_exposure_credits"], 6))
    add("timeout_deviation", "Elasticity branches containing a request that completed after the frozen 90 s timeout",
        "timeout_deviation_branches", meta["timeout_deviation_branches"])
    return claims


# ---------------------------------------------------------------- evidence cache

CACHE_PARTS = (".episodes.pkl", ".daily.pkl", ".integrity.json")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_cache(cache: Path, fingerprint: dict, episodes, daily, integrity) -> None:
    """Write the loaded evidence with the fingerprint it was built from and the hash of each cache file."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    episodes.to_pickle(cache.with_suffix(".episodes.pkl"))
    daily.to_pickle(cache.with_suffix(".daily.pkl"))
    cache.with_suffix(".integrity.json").write_text(json.dumps(integrity), encoding="utf-8")
    record = {**fingerprint, "files": {s: _file_sha(cache.with_suffix(s)) for s in CACHE_PARTS}}
    cache.with_suffix(".fingerprint.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


def load_cache(cache: Path, fingerprint: dict):
    """Return cached (episodes, daily, integrity) only if it matches the current evidence and code, else None."""
    record_path = cache.with_suffix(".fingerprint.json")
    if not all(cache.with_suffix(s).exists() for s in CACHE_PARTS):
        return None
    if not record_path.exists():
        print(f"Cache {cache} has no fingerprint; rebuilding from evidence.")
        return None
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("fingerprint") != fingerprint["fingerprint"]:
        print(f"Cache {cache} is stale (evidence or analysis code changed); rebuilding from evidence.")
        return None
    if any(record.get("files", {}).get(s) != _file_sha(cache.with_suffix(s)) for s in CACHE_PARTS):
        print(f"Cache {cache} files do not match their recorded hashes; rebuilding from evidence.")
        return None
    return (pd.read_pickle(cache.with_suffix(".episodes.pkl")), pd.read_pickle(cache.with_suffix(".daily.pkl")),
            json.loads(cache.with_suffix(".integrity.json").read_text(encoding="utf-8")))


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/report2/analysis")
    parser.add_argument("--cache", type=Path, help="Optional pickle cache of loaded evidence (speeds reruns)")
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args(argv)

    fingerprint = evidence_fingerprint(ROOT)
    cached = load_cache(args.cache, fingerprint) if args.cache else None
    if cached is not None:
        episodes, daily, integrity = cached
        cache_state = "used"
    else:
        episodes, daily, integrity = load_evidence(ROOT)
        episodes = add_recovery(episodes, daily)
        cache_state = "not_requested"
        if args.cache:
            save_cache(args.cache, fingerprint, episodes, daily, integrity)
            cache_state = "rebuilt"
    evidence_source = {
        "cache_state": cache_state, "cache_used": cache_state == "used",
        "cache_path": str(args.cache) if args.cache else None,
        "evidence_fingerprint": fingerprint["fingerprint"], "claim_files": fingerprint["claim_files"],
        "analysis_source_sha256": fingerprint["analysis_source_sha256"],
        "evidence_hashes_verified_this_run": cache_state != "used",
    }

    tables, meta = build_tables(episodes, daily, integrity)
    meta["evidence_source"] = evidence_source
    out = args.output
    (out / "tables").mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(out / "tables" / f"{name}.csv", index=False)

    claims = key_findings(tables, meta)
    pd.DataFrame(claims).to_csv(out / "claim_map.csv", index=False)

    figures = []
    if not args.no_figures:
        from scripts.report2_stage5_figures import make_figures
        figures = make_figures(tables, out / "figures")

    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    sources = {p: hashlib.sha256((ROOT / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
               for p in ("src/analysis/report2_stage5.py", "scripts/run_report2_stage5.py",
                         "scripts/report2_stage5_figures.py", "configs/report2/protocol.json")
               if (ROOT / p).exists()}
    manifest = {
        "stage": 5, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "git_commit": commit,
        "model_calls_made": 0, "source_sha256": sources, **meta,
        "tables": sorted(f"tables/{n}.csv" for n in tables), "figures": figures,
        "table_sha256": {f"tables/{n}.csv": hashlib.sha256((out / "tables" / f"{n}.csv").read_bytes()).hexdigest()
                         for n in tables},
    }
    (out / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("llm_branches", "baseline_branches", "prefix_groups",
                                                 "prefix_groups_with_single_prefix", "evidence_hash_verified_llm_branches",
                                                 "evidence_hash_verified_baseline_branches", "timeout_deviation_branches",
                                                 "project_exposure_credits", "evidence_source")}, indent=2, default=str))
    for c in claims:
        print(f"{c['id']:<40} {c['value']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
