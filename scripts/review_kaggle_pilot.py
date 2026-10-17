"""Audit saved constraint failures and record an evidence-based fallback review."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.agents.llm import decode_action
from src.agents.baselines import choose_actions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    run = args.run
    read = lambda name: json.loads((run / name).read_text(encoding="utf-8"))
    lines = lambda name: [json.loads(line) for line in (run / name).read_text(encoding="utf-8").splitlines()]
    validation = read("validation.json")
    if validation["status"] != "validated_complete" or not all(validation["checks"].values()):
        raise ValueError("Review requires complete validated evidence.")
    observations = {r["date"]: r["observation"] for r in lines("observations.jsonl")}
    actions, failures = lines("actions.jsonl"), []
    for day in actions:
        obs = observations[day["date"]]
        if day["fallback_used"]:
            assert day["actions"] == choose_actions(obs, "adaptive")
        else:
            assert day["actions"] == decode_action(day["responses"][-1], obs)
        invalid = 0
        for text in day["responses"]:
            try:
                decode_action(text, obs)
            except ValueError as exc:
                if str(exc) != "Combined purchase cost exceeds current funds.":
                    raise ValueError("A different failure requires separate investigation before accepting this review.") from exc
                parsed = json.loads(text)
                amount = sum(v["order_quantity"] * obs["products"][sku]["unit_cost"] for sku, v in parsed.items())
                assert amount - obs["funds"] > 1e-6, "Investigate numerical precision instead of labeling a material model error."
                failures.append({"date": day["date"], "requested_purchase_cost": amount, "available_funds": obs["funds"]})
                invalid += 1
        assert invalid == day["invalid_responses"]
    report = {"status": "reviewed", "decision": "retain_frozen_operational_policy", "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run.name, "scenario": validation["scenario"], "decision_opportunities": len(actions),
        "repair_days": sum(a["repair_attempted"] for a in actions), "fallback_days": sum(a["fallback_used"] for a in actions),
        "invalid_responses": len(failures), "constraint_failures": failures,
        "actions_sha256": hashlib.sha256((run / "actions.jsonl").read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
        "hash_rule": "UTF-8 text after universal newline normalization",
        "rationale": "The observed failures are genuine cash-affordability errors, not a parser defect. Every final action is valid, fallbacks exactly match the frozen adaptive policy, and accounting checks pass. Retain the frozen operational policy to measure these failures rather than tuning away negative validation findings.",
        "required_reporting": "Primary outcomes include all fallback days; disclose first-pass validity, repairs,  unassisted completion, fallback frequency and operating cost. Do not describe this as pure unassisted LLM performance.",
        "evaluation_authorized": False}
    (run / "quality_review.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "constraint_failures"}, indent=2))


if __name__ == "__main__":
    main()
