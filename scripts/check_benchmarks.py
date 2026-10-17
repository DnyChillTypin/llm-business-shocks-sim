"""Check all native tasks without making LLM calls; write a readiness manifest."""
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
    session = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "results/setup_checks" / session
    output.mkdir(parents=True)
    report = {"created_at_utc": session, "paid_api_calls": 0, "checks": []}
    for task in ["dependencies", *TASKS]:
        folder = output / task.replace(":", "_")
        folder.mkdir()
        cmd = [sys.executable, "-m", "src.benchmarks.smoke", task, "--output", str(folder)]
        try:
            with (folder / "console.log").open("w", encoding="utf-8") as log:
                done = subprocess.run(cmd, cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"),
                                      stdout=log, stderr=subprocess.STDOUT, timeout=300)
            status = "passed" if done.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            status = "timeout"
        report["checks"].append({"task": task, "status": status, "log": str(folder / "console.log")})
        print(f"{status.upper()}: {task}", flush=True)
        (output / "readiness.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {output / 'readiness.json'}")
    return int(any(c["status"] != "passed" for c in report["checks"]))


if __name__ == "__main__":
    raise SystemExit(main())
