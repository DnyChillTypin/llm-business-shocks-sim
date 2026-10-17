"""Verify the frozen research design offline; never run policies or API calls."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.research.design import validate_design


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional new verification JSON; frozen files are never rewritten.")
    args = parser.parse_args()
    if args.output:
        args.output = args.output.resolve()
        if not args.output.is_relative_to(ROOT / "results/verification"):
            parser.error("Verification output must stay under results/verification; frozen artifacts are read-only.")
    try:
        report = validate_design(ROOT)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        report = {"stage": 1, "status": "failed", "paid_api_calls": 0, "error": str(exc)}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
