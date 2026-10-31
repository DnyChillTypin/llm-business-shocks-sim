"""Review a stopped report 2 pilot offline; no model calls or recovery activation."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from src.research.report2_interruption import review
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Fresh directory under ignored results/report2.")
    args = parser.parse_args()
    result = review(args.handoff, args.output)
    print(json.dumps({k: v for k, v in result.items() if k not in
                      {"completed", "canonical_artifact_sha256", "budget_state", "recovery_plan"}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
