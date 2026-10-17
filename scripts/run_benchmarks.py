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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List all prepared tasks; no API calls.")
    sub.add_parser("check", help="Run local native readiness tests; no API calls.")
    run = sub.add_parser("run", help="Start one paid benchmark task.")
    run.add_argument("--task", required=True, choices=TASKS)
    args = parser.parse_args()
    if args.command == "list":
        print("\n".join(TASKS))
        return 0
    if args.command == "check":
        return subprocess.call([sys.executable, str(ROOT / "scripts/check_benchmarks.py")], cwd=ROOT)
    session = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "results/benchmarks" / args.task.replace(":", "_") / session
    output.mkdir(parents=True)
    command = [sys.executable, "-m", "src.benchmarks.worker", args.task, "--output", str(output)]
    print(f"Starting {args.task}; native output and usage: {output}", flush=True)
    with (output / "console.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"),
                                stdout=log, stderr=subprocess.STDOUT)
    (output / "exit_status.json").write_text(json.dumps({"exit_code": result.returncode}), encoding="utf-8")
    print(f"Exit code {result.returncode}. Log: {output / 'console.log'}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
