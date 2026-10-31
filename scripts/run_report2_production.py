"""User-facing CLI for Report 2 production planning, baselines, manual model execution, auditing, and recovery.

All real model execution requires user manual execution via --activate-and-run.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.research.report2 import canonical_hash, read_json
from src.research.report2_production import (
    TASK, MODEL,
    production_plan, baseline_plan,
    build_production_proposal, verify_production_proposal, activate_production,
    audit_production, prepare_production_recovery, activate_production_recovery,
    current_allowance, read_ledger
)
from src.experiments.report2_production import (
    get_evaluation_block, prepare_production_case, get_or_create_prefix,
    run_all_baselines, run_production_model_branch,
    active_production_state, run_pending_production
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--plan", action="store_true", help="Print production plan")
    modes.add_argument("--baseline-plan", action="store_true", help="Print deterministic baseline plan")
    modes.add_argument("--prepare-cases", action="store_true", help="Prepare case inputs and prefixes offline")
    modes.add_argument("--run-baselines", action="store_true", help="Execute 576 deterministic baselines offline")
    modes.add_argument("--prepare-handoff", type=Path, help="Prepare unactivated production proposal in directory")
    modes.add_argument("--activate-and-run", type=Path, help="Manually activate budget and run production branches")
    modes.add_argument("--execute-model", action="store_true", help="Subprocess entry point for executing one model branch")
    modes.add_argument("--check", action="store_true", help="Offline check of production batch status")
    modes.add_argument("--audit", action="store_true", help="Offline audit of production batch")
    modes.add_argument("--prepare-recovery", type=Path, help="Prepare recovery handoff directory")
    modes.add_argument("--activate-and-resume", type=Path, help="Activate recovery and resume interrupted batch")

    parser.add_argument("--cohort", choices=["main", "history", "elasticity", "all"], default="main")
    parser.add_argument("--directory", type=Path, default=ROOT / "results/report2/production")
    parser.add_argument("--interrupted-batch", type=Path, default=ROOT / "results/report2/production")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--credit-limit", type=float, default=6.0)
    parser.add_argument("--approve-credits", type=float)
    parser.add_argument("--approve-held-credits", type=str)
    parser.add_argument("--branch-index", type=int)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--budget", type=Path)

    args = parser.parse_args()

    if args.plan:
        plan = production_plan(args.cohort, root=ROOT)
        print(json.dumps({
            "cohort": args.cohort,
            "total_branches": len(plan["episodes"]),
            "total_decisions": plan["decisions"],
            "max_attempts": plan["max_attempts"],
            "plan_sha256": canonical_hash(plan),
            "model": plan["model"],
            "model_calls_made": 0,
        }, indent=2))
        return 0

    if args.baseline_plan:
        b_plan = baseline_plan(args.cohort, root=ROOT)
        print(json.dumps({
            "cohort": args.cohort,
            "total_baseline_branches": len(b_plan["episodes"]),
            "total_decisions": b_plan["decisions"],
            "model_calls_made": 0,
        }, indent=2))
        return 0

    if args.prepare_cases:
        sampling = read_json(ROOT / "configs/report2/sampling_manifest.json")
        batch_dir = args.directory.resolve()
        batch_dir.mkdir(parents=True, exist_ok=True)
        elasticities = [1.5] if args.cohort in {"main", "history"} else ([0.75, 2.25] if args.cohort == "elasticity" else [1.5, 0.75, 2.25])
        prepared_count = 0
        for block in sampling["evaluation_blocks"]:
            for e in elasticities:
                if e != 1.5 and not block["diagnostic_subset"]:
                    continue
                prepare_production_case(block, e, batch_dir=batch_dir, root=ROOT)
                get_or_create_prefix(block, e, batch_dir=batch_dir, root=ROOT)
                prepared_count += 1
        print(json.dumps({"status": "cases_prepared", "prepared_count": prepared_count, "model_calls_made": 0}, indent=2))
        return 0

    if args.run_baselines:
        res = run_all_baselines(batch_dir=args.directory.resolve(), cohort=args.cohort, root=ROOT)
        print(json.dumps(res, indent=2))
        return 0

    if args.prepare_handoff:
        if not args.snapshot:
            parser.error("--prepare-handoff requires --snapshot")
        folder = args.prepare_handoff.resolve()
        folder.mkdir(parents=True, exist_ok=False)
        snapshot = read_json(args.snapshot)
        ledger_path = ROOT / "results/budgets/stage2_pilot_v1.sqlite"
        proposal = build_production_proposal(
            snapshot,
            ledger_path,
            cohort=args.cohort,
            incremental_credit_limit=args.credit_limit,
            root=ROOT,
        )
        (folder / "proposal.json").write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")
        shutil_snap = folder / "gateway_snapshot.json"
        shutil_snap.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "proposal_prepared",
            "cohort": proposal["cohort"],
            "incremental_credit_limit": proposal["incremental_credit_limit"],
            "planned_branches": proposal["planned_branches"],
            "model_calls_made": 0,
            "next_gate": f"User manually reviews and runs --activate-and-run {folder.as_posix()}",
        }, indent=2))
        return 0

    if args.execute_model:
        if args.branch_index is None or not args.authorization or not args.budget:
            parser.error("--execute-model requires --branch-index, --authorization, and --budget")
        return run_production_model_branch(
            args.branch_index,
            args.authorization.resolve(),
            args.budget.resolve(),
            batch_dir=args.directory.resolve(),
            root=ROOT,
        )

    if args.activate_and_run:
        folder = args.activate_and_run.resolve()
        proposal = read_json(folder / "proposal.json")
        batch_dir = args.directory.resolve()
        receipt_file = folder / "activation_receipt.json"

        if not receipt_file.exists():
            if args.approve_credits is None:
                parser.error("Activation requires explicit --approve-credits matching proposal incremental limit")
            snapshot = read_json(folder / "gateway_snapshot.json")
            receipt = activate_production(proposal, snapshot, folder, args.approve_credits, root=ROOT)
            print(json.dumps(receipt, indent=2), flush=True)

        auth_path = folder / "approved_authorization.json"
        budget_path = folder / "approved_budget.json"
        plan = production_plan(proposal["cohort"], root=ROOT)

        def runner(idx, auth, budget):
            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--execute-model",
                "--branch-index", str(idx),
                "--authorization", str(auth),
                "--budget", str(budget),
                "--directory", str(batch_dir),
                "--cohort", proposal["cohort"],
            ]
            return subprocess.run(cmd, cwd=ROOT).returncode

        res, code = run_pending_production(plan, batch_dir, auth_path, budget_path, runner, manual=True, root=ROOT)
        print(json.dumps(res, indent=2), flush=True)
        if code:
            return code

        # Batch finished cleanly; run automatic audit
        ledger_path = ROOT / proposal["ledger_relative_path"]
        audit_res = audit_production(batch_dir, ledger_path, cohort=proposal["cohort"], root=ROOT)
        print(json.dumps({k: v for k, v in audit_res.items() if k != "branches"}, indent=2))
        return 0

    if args.check:
        batch_dir = args.directory.resolve()
        plan = production_plan(args.cohort, root=ROOT)
        ledger_path = ROOT / "results/budgets/stage2_pilot_v1.sqlite"
        completed, state, attempts = active_production_state(plan, batch_dir, ledger_path, root=ROOT)
        print(json.dumps({
            "status": "active_production_check",
            "cohort": args.cohort,
            "completed_branches": len(completed),
            "planned_branches": len(plan["episodes"]),
            "physical_attempts": attempts,
            "project_exposure_credits": state["exposure_nanos"] / 1_000_000_000,
            "remaining_project_credits": 20.0 - state["exposure_nanos"] / 1_000_000_000,
            "model_calls_made": 0,
        }, indent=2))
        return 0

    if args.audit:
        batch_dir = args.directory.resolve()
        ledger_path = ROOT / "results/budgets/stage2_pilot_v1.sqlite"
        audit_res = audit_production(batch_dir, ledger_path, cohort=args.cohort, root=ROOT)
        print(json.dumps({k: v for k, v in audit_res.items() if k != "branches"}, indent=2))
        return 0

    if args.prepare_recovery:
        handoff_dir = args.prepare_recovery.resolve()
        batch_dir = args.interrupted_batch.resolve()
        snapshot = read_json(args.snapshot) if args.snapshot else read_json(ROOT / "results/report2/milestone3/recovery2_gateway_snapshot.json")
        prop = prepare_production_recovery(batch_dir, handoff_dir, snapshot, cohort=args.cohort, root=ROOT)
        print(json.dumps({
            "status": "recovery_proposal_prepared",
            "interrupted_index": prop["interrupted_index"],
            "held_credits": prop["held_credits"],
            "model_calls_made": 0,
        }, indent=2))
        return 0

    if args.activate_and_resume:
        handoff_dir = args.activate_and_resume.resolve()
        batch_dir = args.interrupted_batch.resolve()
        if not args.approve_held_credits:
            parser.error("--activate-and-resume requires --approve-held-credits")
        proposal = read_json(handoff_dir / "recovery_proposal.json")
        receipt = activate_production_recovery(proposal, handoff_dir, batch_dir, args.approve_held_credits, root=ROOT)
        print(json.dumps(receipt, indent=2), flush=True)

        plan = production_plan(proposal["cohort"], root=ROOT)
        auth_path = handoff_dir.parent / "approved_authorization.json"
        budget_path = handoff_dir.parent / "approved_budget.json"

        def runner(idx, auth, budget):
            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--execute-model",
                "--branch-index", str(idx),
                "--authorization", str(auth),
                "--budget", str(budget),
                "--directory", str(batch_dir),
                "--cohort", proposal["cohort"],
            ]
            return subprocess.run(cmd, cwd=ROOT).returncode

        res, code = run_pending_production(plan, batch_dir, auth_path, budget_path, runner, manual=True, root=ROOT)
        print(json.dumps(res, indent=2), flush=True)
        if code:
            return code
        ledger_path = ROOT / proposal["ledger_relative_path"]
        audit_res = audit_production(batch_dir, ledger_path, cohort=proposal["cohort"], root=ROOT)
        print(json.dumps({k: v for k, v in audit_res.items() if k != "branches"}, indent=2))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

