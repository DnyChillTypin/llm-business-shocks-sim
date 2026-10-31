"""Check report 2 runtime hashes or audit development branches with scripted completions."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def offline_audit(output):
    from src.research.report2_runtime import implementation_manifest
    from src.research.report2 import PROTOCOL, MANIFEST, build_manifest, read_json
    from src.experiments.report2 import create_prefix, run_branch, validate_branch
    from src.experiments.report2_fixtures import prepare_case, scripted_policy
    if build_manifest(ROOT) != read_json(ROOT / MANIFEST):
        raise ValueError("Milestone 1 sampling changed.")
    protocol = read_json(ROOT / PROTOCOL)
    binding = implementation_manifest(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for case_index, case in enumerate(protocol["sampling"]["development_cases"]):
        elasticities = [1.5, 0.75, 2.25] if case_index == 0 else [1.5]
        for elasticity in elasticities:
            group = output / f"{case['id']}_elasticity_{elasticity}"
            prepared = prepare_case(case, group / "prepared", elasticity)
            prefix = create_prefix(prepared, group / "warmup")
            policies = [("fixed", "full"), ("adaptive", "full")]
            if elasticity == 1.5:
                policies += [("scripted_fixture", h) for h in ("full", "frozen", "none")]
            for scenario in protocol["branching"]["conditions"]:
                for policy, history in policies:
                    name = f"{scenario}_{policy}_{history}"
                    run = group / "branches" / name
                    decide, calls = scripted_policy(protocol["model"]) if policy == "scripted_fixture" else (None, [])
                    summary = run_branch(prepared, prefix, run, scenario=scenario, history=history,
                                         policy=policy, decide=decide)
                    validation = validate_branch(prepared, prefix, run, group / "replays" / name)
                    if policy == "scripted_fixture" and (summary["first_pass_valid"], summary["repair_attempts"],
                            summary["successful_repairs"], summary["fallback_days"], len(calls)) != (12, 2, 1, 1, 16):
                        raise ValueError("Scripted repair/fallback denominators did not reconcile.")
                    rows.append({"case_id": case["id"], "elasticity": elasticity,
                                 "scenario": scenario, "policy": policy, "history": history,
                                 "prefix_sha256": prefix["prefix_sha256"], "status": validation["status"],
                                 "response_decisions": summary["completed_decisions"],
                                 "accounting_reconciled": summary["accounting_reconciled"]})
    if binding != implementation_manifest(ROOT):
        raise ValueError("Runner source changed during the offline audit.")
    report = {"milestone": 2, "status": "passed", "model_calls_made": 0,
              "implementation_sha256": binding["implementation_sha256"],
              "genuine_llm_results": False, "audited_branches": len(rows),
              "description": "Development-only baselines and scripted completions, with independent saved-action replay",
              "branches": rows}
    (output / "audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {k: v for k, v in report.items() if k != "branches"}


def main():
    from src.research.report2_runtime import RUNTIME, implementation_manifest, verify_implementation
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--offline-check", action="store_true")
    parser.add_argument("--output", type=Path, help="Fresh directory under ignored results/report2 for offline checks.")
    args = parser.parse_args()
    if args.offline_check:
        if not args.output or not args.output.resolve().is_relative_to(ROOT / "results/report2"):
            parser.error("Offline output must be a fresh directory under ignored results/report2.")
    elif args.output:
        parser.error("Only --offline-check accepts --output.")
    if args.freeze:
        manifest = implementation_manifest(ROOT)
        with (ROOT / RUNTIME).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(manifest, indent=2) + "\n")
        result = {"status": "passed", "milestone": 2, "implementation_sha256": manifest["implementation_sha256"], "model_calls_made": 0}
    elif args.check:
        manifest = verify_implementation(ROOT)
        result = {"status": "passed", "milestone": 2, "implementation_sha256": manifest["implementation_sha256"], "model_calls_made": 0}
    else:
        result = offline_audit(args.output.resolve())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
