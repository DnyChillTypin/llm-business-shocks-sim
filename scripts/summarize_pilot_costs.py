"""Export measured native pilot costs; incomplete families remain null."""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis.costs import cost_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/analysis/stage2")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = cost_report()
    (args.output / "pilot_cost_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(report["observations"]).to_csv(args.output / "pilot_usage.csv", index=False)
    pd.DataFrame(report["projections"]).to_csv(args.output / "cost_projections.csv", index=False)
    print(json.dumps(report["totals"], indent=2))


if __name__ == "__main__":
    main()
