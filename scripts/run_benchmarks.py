"""Windows/Linux launcher. List/check are free; run starts a paid native task."""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.benchmarks.common import TASKS
from src.benchmarks.planning import run_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List all prepared tasks; no API calls.")
    sub.add_parser("check", help="Run local native readiness tests; no API calls.")
    run = sub.add_parser("run", help="Start one paid benchmark task.")
    run.add_argument("--task", required=True, choices=TASKS)
    run.add_argument("--config", type=Path)
    run.add_argument("--purpose", choices=["pilot", "evaluation"])
    run.add_argument("--case-limit", type=int)
    run.add_argument("--budget", type=Path, help="User-approved allowance manifest; shared spending persists across tasks.")
    run.add_argument("--consulting-recovery", type=Path, help="Re-audited completed independent Consulting sessions; full frozen ten-case plan remains unchanged.")
    run.add_argument("--dry-run", action="store_true", help="Print the exact bounded plan; no credentials, network, or paid calls.")
    args = parser.parse_args()
    if args.command == "list":
        print("\n".join(TASKS))
        return 0
    if args.command == "check":
        return subprocess.call([sys.executable, str(ROOT / "scripts/check_benchmarks.py")], cwd=ROOT)
    try:
        plan = run_plan(args.task, config_path=args.config, purpose=args.purpose, case_limit=args.case_limit)
    except ValueError as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return 0
    if args.consulting_recovery and (args.task != "firm:consulting" or plan["purpose"] != "evaluation"):
        parser.error("Completed-session recovery is restricted to the full frozen Consulting evaluation.")
    if not args.budget:
        parser.error("Paid execution requires --budget with an explicitly approved allowance. Use --dry-run to inspect first.")
    session = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "results/benchmarks" / args.task.replace(":", "_") / session
    output.mkdir(parents=True)
    (output / "launch_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    command = [sys.executable, "-m", "src.benchmarks.worker", args.task, "--output", str(output),
               "--plan", str(output / "launch_plan.json"), "--budget", str(args.budget.resolve())]
    if args.consulting_recovery:
        command += ["--consulting-recovery", str(args.consulting_recovery.resolve())]
    print(f"Starting {args.task}; native output and usage: {output}", flush=True)
    with (output / "console.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"),
                                stdout=log, stderr=subprocess.STDOUT)
    (output / "exit_status.json").write_text(json.dumps({"exit_code": result.returncode}), encoding="utf-8")
    print(f"Exit code {result.returncode}. Log: {output / 'console.log'}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
