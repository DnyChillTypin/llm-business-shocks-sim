"""Prepare/check/audit offline; model subprocesses run only with explicit user manual flags."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from src.research.report2 import read_json
    from src.research.report2_development import prepare, verify, activate, active_state, run_pending, audit
    from src.experiments.kaggle_protocol import execution_lock
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--activate-and-run", action="store_true", help="USER MANUAL COMMAND: activate reviewed limits and run unfinished development branches.")
    mode.add_argument("--run-models", action="store_true", help="USER MANUAL COMMAND: continue an already activated, intact batch; skip completed branches.")
    mode.add_argument("--audit", action="store_true")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--first-handoff", type=Path, default=ROOT / "results/report2/milestone3/first_branch_budget20")
    parser.add_argument("--ledger", type=Path, default=ROOT / "results/budgets/stage2_pilot_v1.sqlite")
    parser.add_argument("--approve-credit-limit", type=float)
    args = parser.parse_args()
    folder = args.directory.resolve()
    if not folder.is_relative_to(ROOT / "results/report2"):
        parser.error("Continuation artifacts must stay under ignored results/report2.")
    if args.prepare:
        if not args.snapshot or args.approve_credit_limit is not None:
            parser.error("Preparation requires a read-only snapshot and does not accept spending approval.")
        snapshot = read_json(args.snapshot)
        proposal = prepare(snapshot, args.ledger, args.first_handoff, ROOT)
        folder.mkdir(parents=True, exist_ok=False)
        for name, value in (("proposal.json", proposal), ("gateway_snapshot.json", snapshot), ("cost_forecast.json", proposal["forecast"])):
            (folder / name).write_text(json.dumps(value, indent=2) + "\n")
        result = {"status": proposal["status"], "model_calls_made": 0, "forecast": proposal["forecast"]}
    else:
        if args.snapshot or (args.approve_credit_limit is not None and not args.activate_and_run):
            parser.error("Only preparation accepts --snapshot; only activation accepts credit approval.")
        proposal, snapshot = read_json(folder / "proposal.json"), read_json(folder / "gateway_snapshot.json")
        if args.audit:
            result = audit(proposal, snapshot, folder, ROOT)
            result = {k: v for k, v in result.items() if k != "branches"}
        elif args.check:
            if (folder / "activation_receipt.json").exists():
                completed, _ = active_state(proposal, snapshot, folder, ROOT, fresh=False)
                result = {"status": "active", "completed_branches": len(completed), "model_calls_made": 0}
            else:
                verify(proposal, snapshot, ROOT)
                result = {"status": "ready_for_user_manual_continuation", "model_calls_made": 0, "ledger_modified": False}
        else:
            if args.activate_and_run and args.approve_credit_limit != proposal["incremental_credit_limit"]:
                parser.error("Manual approval must match the reviewed incremental credit limit.")
            with execution_lock(folder):
                if args.activate_and_run and not (folder / "activation_receipt.json").exists():
                    print(json.dumps(activate(proposal, snapshot, folder, approve_credit_limit=args.approve_credit_limit, root=ROOT), indent=2), flush=True)
                elif not (folder / "activation_receipt.json").exists():
                    parser.error("The batch must be manually activated before --run-models.")

                def run(index, authorization, budget):
                    return subprocess.run([sys.executable, str(ROOT / "scripts/run_report2_pilot.py"),
                                           "--execute-model", "--branch-index", str(index),
                                           "--authorization", str(authorization), "--budget", str(budget)], cwd=ROOT).returncode

                result, code = run_pending(proposal, snapshot, folder, run, ROOT, manual=True)
                print(json.dumps(result, indent=2))
                return code
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
