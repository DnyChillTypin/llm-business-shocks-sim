"""Freeze or verify report 2 sampling offline. Never creates a model client."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.research.report2 import MANIFEST, build_manifest, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true", help="Create the manifest once; refuse existing files.")
    mode.add_argument("--check", action="store_true", help="Rebuild in memory and compare with the frozen manifest.")
    parser.add_argument("--output", type=Path, help="Optional verification receipt under ignored results/report2.")
    args = parser.parse_args()
    if args.output:
        args.output = args.output.resolve()
        if not args.output.is_relative_to(ROOT / "results/report2"):
            parser.error("Verification receipts must stay inside ignored results/report2.")
    try:
        manifest = build_manifest(ROOT)
        destination = ROOT / MANIFEST
        if args.freeze:
            with destination.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
        elif read_json(destination) != manifest:
            raise ValueError("Frozen sampling or input hashes changed; review and version the protocol before new outcomes.")
        report = {"milestone": 1, "status": "passed", "model_calls_made": 0,
                  "runner_implemented": False, "manifest_sha256": manifest["manifest_sha256"],
                  "selected_series": len(manifest["selected_series"]),
                  "evaluation_blocks": len(manifest["evaluation_blocks"]),
                  "dependence_audit": manifest["dependence_audit"], "workload": manifest["workload"],
                  "next_gate": "User reviews Milestone 1 before matched-prefix implementation"}
    except (ValueError, OSError, KeyError) as exc:
        report = {"milestone": 1, "status": "failed", "model_calls_made": 0, "error": str(exc)}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
