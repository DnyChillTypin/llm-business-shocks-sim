"""Offline recovery preparation/checks; explicit USER MANUAL execution restarts models."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from src.experiments.kaggle_protocol import execution_lock, write
    from src.research.report2 import read_json
    from src.research.report2_recovery import prepare, check_before, activate, active_state, run_pending, audit
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ("prepare", "check", "activate-and-run", "run-models", "audit"):
        mode.add_argument("--" + name, action="store_true")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--continuation", type=Path, default=ROOT / "results/report2/milestone3/remaining_development_ready")
    parser.add_argument("--review", type=Path, default=ROOT / "results/report2/milestone3/interruption_review_ready/interruption_review.json")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--approve-held-credits", type=str)
    args = parser.parse_args()
    folder = args.directory.resolve()
    batch = ROOT / "results/report2/manual_development"
    if not folder.is_relative_to(ROOT / "results/report2") or folder.is_relative_to(batch) or folder == ROOT / "results/report2":
        parser.error("Use a local results/report2 handoff directory outside the canonical batch.")
    if args.prepare:
        if not args.snapshot or args.approve_held_credits is not None:
            parser.error("Offline preparation requires --snapshot and accepts no spending approval.")
        proposal = prepare(args.continuation, args.review, read_json(args.snapshot))
        folder.mkdir(parents=True, exist_ok=False)
        write(folder / "proposal.json", proposal)
        result = {k: proposal[k] for k in ("status", "model_calls_made", "restart_index", "recovery_branch_indices",
                  "held_credits", "additional_credit_limit", "remaining_existing_retail_allocation")}
    else:
        if args.snapshot or (args.approve_held_credits is not None and not args.activate_and_run):
            parser.error("Only preparation accepts --snapshot; only manual activation accepts --approve-held-credits.")
        proposal = read_json(folder / "proposal.json")
        if args.check:
            if (folder / "activation_receipt.json").exists():
                completed, _, _ = active_state(proposal, folder)
                result = {"status": "active", "completed_branches": len(completed), "model_calls_made": 0}
            else:
                check_before(proposal, fresh=True)
                result = {"status": "ready_for_user_manual_recovery", "model_calls_made": 0, "ledger_modified": False}
        elif args.audit:
            result = audit(proposal, folder)
        else:
            if args.activate_and_run and args.approve_held_credits is None:
                parser.error("Manual activation requires --approve-held-credits matching the reviewed full reservation.")
            with execution_lock(folder):
                if not (folder / "activation_receipt.json").exists():
                    if not args.activate_and_run:
                        parser.error("Run manual activation before --run-models.")
                    with execution_lock(batch):
                        receipt = activate(proposal, folder, approve_held_credits=args.approve_held_credits)
                    print(json.dumps({k: v for k, v in receipt.items() if k not in
                                      {"archived_artifact_sha256", "retained_hold"}}, indent=2), flush=True)
                elif args.activate_and_run and args.approve_held_credits != str(proposal["held_credits"]):
                    parser.error("Manual retained-reservation amount differs from the reviewed proposal.")

                def run(index, authorization, budget):
                    return subprocess.run([sys.executable, str(ROOT / "scripts/run_report2_pilot.py"), "--execute-model",
                                           "--branch-index", str(index), "--authorization", str(authorization),
                                           "--budget", str(budget)], cwd=ROOT).returncode

                result, code = run_pending(proposal, folder, run, manual=True)
                print(json.dumps(result, indent=2), flush=True)
                if code:
                    return code
                result = audit(proposal, folder)
    print(json.dumps({k: v for k, v in result.items() if k != "branches"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
