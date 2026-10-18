"""Independently replay saved Kaggle episodes without paid calls."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.experiments.kaggle_validation import validate_run
from src.experiments.kaggle_protocol import write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    report = validate_run(args.run)
    write(args.run / "validation.json", report)
    result = report if not args.summary else {"status": report["status"], "agent_kind": report.get("agent_kind"),
        "checks": len(report["checks"]), "failed_checks": [k for k, v in report["checks"].items() if not v],
        "api_attempts": report.get("api_attempts", 0)}
    print(json.dumps(result, indent=2))
    return int(report["status"] != "validated_complete")


if __name__ == "__main__":
    raise SystemExit(main())
