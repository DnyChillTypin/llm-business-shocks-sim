"""Repeated reviewed recovery; all AI execution remains a user manual command."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from src.experiments.kaggle_protocol import execution_lock
    from src.research.report2 import read_json
    from src.research.report2_recovery_chain import prepare, check_before, activate, active_state, run_pending, audit
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for flag in ("prepare", "check", "activate-and-run", "run-models", "audit"):
        modes.add_argument("--" + flag, action="store_true")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--approve-held-credits", type=str)
    args = parser.parse_args()
    folder, batch = args.directory.resolve(), ROOT / "results/report2/manual_development"
    if not folder.is_relative_to(ROOT / "results/report2") or folder.is_relative_to(batch) or folder == ROOT / "results/report2":
        parser.error("Use a separate local results/report2 handoff directory.")
    if args.prepare:
        if not args.previous or not args.snapshot or args.approve_held_credits:
            parser.error("Preparation needs --previous and --snapshot; it accepts no spending approval.")
        p = prepare(args.previous, folder, read_json(args.snapshot))
        result = {k: p[k] for k in ("status", "model_calls_made", "restart_index", "recovery_branch_indices",
                                     "held_credits", "additional_credit_limit", "remaining_existing_retail_allocation")}
    else:
        if args.previous or args.snapshot or (args.approve_held_credits and not args.activate_and_run):
            parser.error("Previous/snapshot are preparation inputs; held-credit approval is only for activation.")
        p = read_json(folder / "proposal.json")
        if args.check:
            if (folder / "activation_receipt.json").exists():
                completed, _, _ = active_state(p, folder)
                result = {"status": "active", "completed_branches": len(completed), "model_calls_made": 0}
            else:
                check_before(p, fresh=True)
                result = {"status": "ready_for_user_manual_recovery", "ledger_modified": False, "model_calls_made": 0}
        elif args.audit:
            result = audit(p, folder)
        else:
            if args.activate_and_run and args.approve_held_credits != str(p["held_credits"]):
                parser.error("Manual approval must equal the full reviewed unknown-charge reservation.")
            with execution_lock(folder):
                if not (folder / "activation_receipt.json").exists():
                    if not args.activate_and_run:
                        parser.error("Explicit manual activation is required first.")
                    with execution_lock(batch):
                        receipt = activate(p, folder, approve_held_credits=args.approve_held_credits)
                    print(json.dumps({k: v for k, v in receipt.items() if k not in
                                      {"archived_artifact_sha256", "retained_hold"}}, indent=2), flush=True)

                def run(index, auth, budget):
                    return subprocess.run([sys.executable, str(ROOT / "scripts/run_report2_pilot.py"), "--execute-model",
                                           "--branch-index", str(index), "--authorization", str(auth), "--budget", str(budget)], cwd=ROOT).returncode

                result, code = run_pending(p, folder, run, manual=True)
                print(json.dumps(result, indent=2), flush=True)
                if code:
                    return code
                result = audit(p, folder)
    print(json.dumps({k: v for k, v in result.items() if k != "branches"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
