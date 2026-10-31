"""Prepare or audit offline; only the user's explicit --activate-and-run launches a model."""
import argparse
import json
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from src.research.report2 import read_json
    from src.research.report2_pilot import (build_proposal, verify_proposal, legacy_usage,
                                           activate_proposal, audit_first_branch)
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--activate", action="store_true", help="User manually approves the exact stated ceiling; no model requests.")
    mode.add_argument("--activate-and-run", action="store_true", help="USER MANUAL COMMAND: approve the reviewed ceiling, then execute branch 0.")
    mode.add_argument("--audit", action="store_true", help="Inspect saved model outcomes without requesting new decisions.")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--ledger", type=Path, default=ROOT / "results/budgets/stage2_pilot_v1.sqlite")
    parser.add_argument("--legacy-usage", type=Path, default=ROOT / "docs/results/stage6/llm_episode_reliability_costs.csv")
    parser.add_argument("--observations", type=Path,
                        default=ROOT / "results/report2/milestone2/offline_bound/dev_1_elasticity_1.5/branches/control_scripted_fixture_full/observations.jsonl")
    parser.add_argument("--approve-credit-limit", type=float)
    args = parser.parse_args()
    folder = args.directory.resolve()
    if not folder.is_relative_to(ROOT / "results/report2"):
        parser.error("Pilot handoff artifacts must remain inside ignored results/report2.")
    if args.prepare:
        if not args.snapshot or args.approve_credit_limit is not None:
            parser.error("Preparation needs a read-only gateway snapshot, not activation approval.")
        snapshot = read_json(args.snapshot)
        observations = [json.loads(s) for s in args.observations.read_text().splitlines()]
        proposal = build_proposal(snapshot, args.ledger, legacy_usage(args.legacy_usage), observations)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "gateway_snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        (folder / "proposal.json").write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")
        (folder / "cost_worksheet.json").write_text(json.dumps(proposal["cost_worksheet"], indent=2) + "\n", encoding="utf-8")
        quote = proposal["cost_worksheet"]
        result = {"stage": "3_preparation", "status": proposal["status"], "model_calls_made": 0,
                  "expected_credits_from_legacy_usage": quote["base_credits"],
                  "high_reserved_payload_scenario_credits": quote["high_reserved_payload_scenario_credits"],
                  "manual_credit_limit_to_review": proposal["incremental_credit_limit"],
                  "max_decisions": 14, "max_attempts": 28, "pilot_measured": False,
                  "ledger_modified": False}
    else:
        proposal, snapshot = read_json(folder / "proposal.json"), read_json(folder / "gateway_snapshot.json")
        if args.snapshot or (args.approve_credit_limit is not None and not (args.activate or args.activate_and_run)):
            parser.error("Only preparation accepts --snapshot; only activation accepts credit approval.")
        if args.activate or args.activate_and_run:
            if args.approve_credit_limit is None:
                parser.error("Manual activation requires --approve-credit-limit matching the reviewed proposal.")
            result = activate_proposal(proposal, snapshot, folder, approve_credit_limit=args.approve_credit_limit)
            if args.activate_and_run:
                print(json.dumps(result, indent=2), flush=True)
                return subprocess.run([sys.executable, str(ROOT / "scripts/run_report2_pilot.py"),
                                       "--execute-model", "--branch-index", "0",
                                       "--authorization", str(folder / "approved_authorization.json"),
                                       "--budget", str(folder / "approved_budget.json")], cwd=ROOT).returncode
        elif args.audit:
            result = audit_first_branch(proposal, snapshot, folder)
        else:
            verify_proposal(proposal, snapshot)
            result = {"stage": "3_preparation", "status": "ready_for_user_manual_activation", "model_calls_made": 0,
                      "pilot_measured": False, "ledger_modified": False}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
