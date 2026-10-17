"""Compare saved provider history with attempt metadata; never alter spend limits."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    items = snapshot["history"]["items"]
    matched, unresolved = [], []
    paths = [*(ROOT / "results/benchmarks").glob("*/*/api_attempts.jsonl"),
             *(ROOT / "results/runs/kaggle_retailbench").glob("*/api_attempts.jsonl")]
    for path in sorted(paths):
        for row in map(json.loads, path.read_text(encoding="utf-8").splitlines()):
            if row["event"] != "finished" or row["purpose"] != "pilot":
                continue
            usage = row.get("usage") or {}
            start = datetime.fromisoformat(row["started_at_utc"]).timestamp() - 10
            end = datetime.fromisoformat(row["finished_at_utc"]).timestamp() + 10
            matches = [r for r in items if r.get("model_name") == row["requested_model"] and
                start <= r.get("created_at", 0) <= end and r.get("prompt_tokens") == usage.get("prompt_tokens") and
                r.get("completion_tokens") == usage.get("completion_tokens")]
            if row["status"] == "completed" and len(matches) == 1:
                matched.append({"attempt_id": row["attempt_id"], "provider_reported_cost_usd": matches[0]["cost"],
                    "local_uncached_estimate_usd": row["cost_usd"]})
            else:
                unresolved.append({"attempt_id": row["attempt_id"], "failure_category": row.get("failure_category"),
                    "started_at_utc": row["started_at_utc"], "model": row["requested_model"],
                    "usage_known": bool(usage),
                    "reason": "SDK usage is known, but identical token/time entries do not uniquely identify a provider row." if usage else
                              "No SDK usage or unique matching charge record; missing usage is not zero and its full reserve remains held."})
    report = {"snapshot_checked_at_utc": snapshot["checked_at_utc"], "matched_completed_attempts": len(matched),
        "matched_provider_reported_cost_usd": sum(r["provider_reported_cost_usd"] for r in matched),
        "matched_local_uncached_estimate_usd": sum(r["local_uncached_estimate_usd"] for r in matched),
        "unresolved_attempts": unresolved, "matches": matched, "ledger_modified": False,
        "known_usage_unmatched_history_attempts": sum(r["usage_known"] for r in unresolved),
        "unknown_usage_attempts": sum(not r["usage_known"] for r in unresolved),
        "provider_charges_fully_reconciled": not unresolved,
        "qualification": "Matching provider history is available charging evidence, not independently audited billing. No charge inferred from an absent row. Further-call authorization and bounded held charges are determined separately by the approved allowance and ledger."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "matches"}, indent=2))
    return int(bool(unresolved))


if __name__ == "__main__":
    raise SystemExit(main())
