"""Validate saved native coverage, response artifacts and accounting; no paid calls."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.benchmarks.validation import validate_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--summary", action="store_true", help="Print only aggregate review fields; keep the full validation local.")
    args = parser.parse_args()
    report = validate_run(args.run)
    (args.run / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    displayed = report
    if args.summary:
        displayed = {k: report[k] for k in ("task", "status", "attempts", "input_tokens", "output_tokens", "estimated_gateway_credit_usd", "elapsed_seconds")}
        displayed["failed_checks"] = [k for k, value in report["checks"].items() if not value]
        score = report.get("native_score")
        displayed["native_score"] = {k: v for k, v in score.items() if not isinstance(v, (dict, list))} if isinstance(score, dict) else None
    print(json.dumps(displayed, indent=2))
    return 0 if report["status"] == "validated_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
