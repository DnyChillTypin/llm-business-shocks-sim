"""CLI runner to execute Stage 5 empirical analysis for Report 2.

Consumes validated production batches and outputs primary contrast tables and LaTeX assets.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis.report2_analysis import (
    load_cohort_runs,
    load_baseline_runs,
    compute_paired_contrasts,
    summarize_by_block,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/report2/tables")
    args = parser.parse_args()

    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading Stage 4B (Main Production Cohort)...", flush=True)
    prod_dir = ROOT / "results/report2/production"
    models_main = load_cohort_runs(prod_dir, cohort_name="main")
    baselines_main = load_baseline_runs(prod_dir)

    print(f"Loaded {len(models_main)} model branches and {len(baselines_main)} baseline branches.")

    contrasts_main = compute_paired_contrasts(models_main, baselines_main)
    summary_main = summarize_by_block(contrasts_main)

    # Save to CSV
    models_main.to_csv(out_dir / "main_cohort_episodes.csv", index=False)
    contrasts_main.to_csv(out_dir / "main_paired_contrasts.csv", index=False)
    summary_main.to_csv(out_dir / "main_block_summary.csv", index=False)

    print("\n=== Main Production Cohort Summary (Across 36 Evaluation Blocks) ===")
    cols_to_show = [
        "scenario", "n_blocks", "mean_llm_contribution", "mean_adaptive_contribution",
        "mean_raw_contrast_adaptive", "positive_raw_contrast_blocks",
        "mean_control_adjusted_interaction", "positive_interaction_blocks",
        "mean_fill_rate", "mean_first_pass_valid", "mean_fallbacks_used"
    ]
    print(summary_main[[c for c in cols_to_show if c in summary_main.columns]].to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

