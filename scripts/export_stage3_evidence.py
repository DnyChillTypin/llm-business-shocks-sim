"""Rebuild aggregate Stage 3 evidence from local saved runs; never calls an API."""
import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.benchmarks.budget import BudgetLedger
from src.benchmarks.common import TASKS
from src.benchmarks.planning import run_plan
from src.benchmarks.validation import validate_run
from src.analysis.native_metrics import reasoning_metric

PUBLIC = ROOT / "docs/results/stage3"
PRIVATE = ROOT / "results/analysis/stage3"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def classification(task):
    if task == "firm:factset":
        return "Factset extension with substituted model"
    if task in {"icbe", "firm:edt"}:
        return "native logic with compatibility adaptation and substituted models"
    return "native logic with substituted model"


def cohort_record(folder, manifest, label):
    events_path = folder / "api_attempts.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()] if events_path.exists() else []
    starts = [e for e in events if e["event"] == "started"]
    finishes = [e for e in events if e["event"] == "finished"]
    parses = [e for e in events if e["event"] == "parse_checked"]
    validation = None
    if (folder / "exit_status.json").exists() and manifest.get("status") == "execution_finished_requires_artifact_review":
        validation = validate_run(folder)
        write_json(folder / "validation.json", validation)
    score = validation.get("native_score") if validation else None
    status = validation["status"] if validation else manifest["status"]
    cases = [read(p) for p in sorted((folder / "case_records").glob("*.json"))]
    metric = reasoning_metric(manifest["task"], score, cases) if validation and isinstance(score, dict) and "accuracy" in score else {}
    finished_by_id = {e["attempt_id"]: e for e in finishes}
    held = sum(max(0, e["reserved_cost_usd"] - (finished_by_id.get(e["attempt_id"], {}).get("cost_usd") or 0))
               for e in starts if finished_by_id.get(e["attempt_id"], {}).get("cost_usd") is None)
    record = {"cohort": label, "task": manifest["task"], "status": status,
              "method_classification": classification(manifest["task"]),
              "expected_units": manifest["expected_units"], "configured_horizon": manifest["configured_horizon"],
              "saved_reasoning_cases": len(cases),
              "native_accuracy_unit": metric.get("native_accuracy_unit"),
              "native_correct_units": metric.get("native_correct_units"),
              "native_scored_units": metric.get("native_scored_units"),
              "exact_case_accuracy": metric.get("exact_case_accuracy"),
              "correct": score.get("correct") if isinstance(score, dict) else None,
              "scored_cases": score.get("total") if isinstance(score, dict) else None,
              "accuracy": score.get("accuracy") if isinstance(score, dict) else None,
              "no_answer": score.get("no_answer") if isinstance(score, dict) else None,
              "attempts": len(starts), "completed_responses": sum(e["status"] == "completed" for e in finishes),
              "replayed_decisions": len(read(folder / "icbe_recovery.json")["decisions"]) if (folder / "icbe_recovery.json").exists() else 0,
              "attempts_without_observed_gateway_outcome": len(starts) - len(finishes),
              "invalid_responses": sum(e.get("parse_status") != "valid" for e in parses),
              "unknown_usage_responses": sum(e.get("cost_usd") is None for e in finishes),
              "input_tokens": sum((e.get("usage") or {}).get("prompt_tokens", 0) for e in finishes),
              "output_tokens": sum((e.get("usage") or {}).get("completion_tokens", 0) for e in finishes),
              "estimated_gateway_credits": sum(e.get("cost_usd") or 0 for e in finishes),
              "unresolved_reserved_credits": held,
              "conservative_exposure_credits": sum(e.get("cost_usd") or 0 for e in finishes) + held,
              "api_seconds": sum(e["latency_seconds"] for e in finishes),
              "elapsed_seconds": ((datetime.fromisoformat(manifest["finished_at_utc"]) - datetime.fromisoformat(manifest["started_at_utc"])).total_seconds()
                                  if manifest.get("finished_at_utc") else None),
              "failure_category": manifest.get("failure_category"),
              "requested_models": sorted({e["requested_model"] for e in starts}),
              "returned_models": sorted({e.get("returned_model") or "not_reported" for e in finishes}),
              "checks": validation["checks"] if validation else {},
              "project_commit": read(folder / "runtime_identity.json")["project_commit"],
              "project_tracked_dirty": read(folder / "runtime_identity.json")["project_tracked_dirty"]}
    if manifest["task"] == "firm:consulting":
        judges = [e for e in finishes if e["status"] == "completed" and e["context"].get("validation_kind") == "judge"]
        scores = [json.loads(read(folder / "attempts" / e["attempt_id"] / "response.json")["choices"][0]["message"]["content"]) for e in judges]
        record["observed_consulting_judgments"] = len(scores)
        record["observed_mean_judge_scores"] = {k: sum(s[k] for s in scores) / len(scores) for k in
            ("structure", "quant", "business_sense", "communication", "overall")} if scores else None
        record["recovered_consulting_sessions"] = len(read(folder / "consulting_recovery.json")["cases"]) if (folder / "consulting_recovery.json").exists() else 0
    return record, validation


def task_metrics(folder, validation, label):
    task, score = validation["task"], validation["native_score"]
    if task == "firm:consulting":
        states = read(next(folder.rglob("consulting_interview_states.json")))["cases"]
        reused = len(read(folder / "consulting_recovery.json")["cases"]) if (folder / "consulting_recovery.json").exists() else 0
        return {"cohort": label, "task": task, "sessions": score["num_finished"], "native_mean_judge_scores": score["metrics"],
                "recovered_completed_sessions": reused, "fresh_sessions": score["num_finished"] - reused,
                "session_message_counts": [len(s["history"]) for s in states],
                "overall_judge_score_range": [min(s["judge_scores"]["overall"] for s in states), max(s["judge_scores"]["overall"] for s in states)],
                "outcome_units": "Judge rubric scores from 0 to 10",
                "qualification": "Scores are judgments by the substituted judge model, not independent human ratings. Where recovery is used, earliest completed independent sessions are re-audited and passed unchanged to the native ten-case aggregator; all source-cohort costs remain separately counted."}
    if task == "firm:beergame":
        episodes = [{k: e.get(k) for k in ("scenario_id", "weeks_completed", "controlled_role", "opponent_policy",
                    "total_cost_controlled", "total_cost_supply_chain", "bullwhip_controlled", "avg_backlog_controlled")}
                    for e in score["episode_metrics"]]
        return {"cohort": label, "task": task, "episodes": episodes,
                "outcome_units": "Native simulation monetary units, distinct from gateway credits",
                "offline_saved_action_audit": read(folder / "beer_audit.json") if (folder / "beer_audit.json").exists() else None,
                "native_aggregate_metrics": {k: v for k, v in score.items() if k != "episode_metrics"},
                "qualification": "Inspect supply-chain amplification separately from controlled-retailer cost. Missing upstream aggregate metrics remain null."}
    if task == "firm:edt":
        rollout = read(next(folder.rglob("rollout.json")))
        decisions = [json.loads(line) for line in (folder / "decision_events.jsonl").read_text().splitlines()]
        event = next(e for e in decisions if e["event"] == "native_edt_normalization")
        schema = event["normalized_schema"]
        return {"cohort": label, "task": task, "rollout_summary": {k: v for k, v in rollout.items() if type(v) in (int, float, bool) or v is None},
                "outcome_units": "Native synthetic business monetary units, distinct from gateway credits",
                "scenario_decision_summary": {"capital_C": schema["C"], "risk_R": schema["R"], "available_projects": len(schema["P"]),
                    "selected_projects": sum(isinstance(p, list) and p[0] == 1 for p in schema["P"]),
                    "native_projection_applied": event["projection_applied"]},
                "synthetic_business_metrics": {k: v for k, v in rollout.get("metrics", {}).items() if type(v) in (int, float) or v is None},
                "qualification": "One configured scenario; synthetic model outcome, not a causal estimate of real business performance."}
    if task == "icbe":
        import openpyxl
        book = openpyxl.load_workbook(next(folder.glob("*.xlsx")), read_only=True, data_only=True)
        try:
            entries = list(book["Detailed Logs"].values)
            rows = [dict(zip(entries[0], values)) for values in entries[1:]]
        finally:
            book.close()
        grouped = defaultdict(list)
        for row in rows:
            grouped[(row["Match ID"], row["Market Phase"])].append(row)
        phases = []
        # Header names are checked against the saved native workbook before export.
        for (pair, phase), records in grouped.items():
            first = records[0]
            phases.append({"ordered_pair": pair, "phase": phase,
                           "model_a": first["Model A"], "model_b": first["Model B"], "rounds": len(records),
                           "cooperation_rate_a": sum(r["Move A"] == "COOPERATE" for r in records) / len(records),
                           "cooperation_rate_b": sum(r["Move B"] == "COOPERATE" for r in records) / len(records),
                           "points_a": sum(r["Pts A"] for r in records), "points_b": sum(r["Pts B"] for r in records)})
        reused = len(read(folder / "icbe_recovery.json")["decisions"]) if (folder / "icbe_recovery.json").exists() else 0
        return {"cohort": label, "task": task, "phase_metrics": phases,
                "replayed_observed_decisions": reused, "fresh_decisions": validation["attempts"],
                "outcome_units": "Native game payoff points and cooperation proportions",
                "qualification": "One ordered match per model pair; rounds are dependent observations. Output ceiling is 4096 rather than upstream 150 tokens. Any replay uses actual prior validated responses at identical native requests; histories, phase changes and points are reconstructed by the native simulator, and source charges remain separately counted."}
    return None


def main():
    PUBLIC.mkdir(parents=True, exist_ok=True)
    manifests = sorted((ROOT / "results/benchmarks").glob("*/*/run_manifest.json"))
    selected = [(p.parent, read(p)) for p in manifests if read(p).get("purpose") == "evaluation"]
    selected.sort(key=lambda item: item[1]["started_at_utc"])
    cohorts, metrics, mapping = [], [], []
    for index, (folder, manifest) in enumerate(selected, 1):
        label = f"evaluation_{index:02d}"
        record, validation = cohort_record(folder, manifest, label)
        cohorts.append(record)
        mapping.append({"cohort": label, "local_folder": str(folder), "validation": validation})
        if validation and validation["status"] == "validated_complete":
            metric = task_metrics(folder, validation, label)
            if metric:
                metrics.append(metric)
    coverage = []
    for task in TASKS:
        plan = run_plan(task, purpose="evaluation")
        runs = [c for c in cohorts if c["task"] == task]
        complete = [c for c in runs if c["status"] == "validated_complete"]
        coverage.append({"task": task, "method_classification": classification(task),
            "status": "deferred" if task.startswith("retail:") else "validated_complete" if complete else runs[-1]["status"] if runs else "planned",
            "planned_units": plan["expected_units"], "configured_horizon": plan["configured_horizon"],
            "validated_units": plan["expected_units"] if complete else 0,
            "evaluation_cohorts": len(runs), "failed_or_incomplete_cohorts": sum(c["status"] != "validated_complete" for c in runs),
            "qualifications": "Retail excluded from this execution route; original scope remains outstanding." if task.startswith("retail:") else ""})
    allowance_path = ROOT / ".cache/approvals/stage3_nonretail_v2.json"
    if not allowance_path.exists():
        allowance_path = ROOT / ".cache/approvals/stage3_nonretail_v1.json"
    allowance = read(allowance_path)
    ledger = BudgetLedger(allowance, ROOT / "results/budgets" / (allowance["budget_id"] + ".sqlite"), run_id="stage3_export")
    summary = ledger.summary()
    transition = read(ROOT / "results/verification/stage3/allowance_transition.json")
    budget = {k: summary[k] for k in ("currency", "attempts", "known_cost_usd", "unresolved_reserved_usd", "exposure_usd",
              "pending_attempts", "uncertain_attempts", "bounded_carried_attempts", "blocking_uncertain_attempts", "cap_usd")}
    budget.update(prior_pilot_exposure=transition["before"]["exposure_usd"], prior_pilot_attempts=transition["before"]["attempts"],
                  scope_caps=allowance["scope_caps_usd"], total_attempt_ceiling=allowance["max_attempts"],
                  unallocated_reserve=allowance["cap_usd"] - sum(allowance["scope_caps_usd"].values()),
                  qualification="Token-derived uncached tariff upper estimates plus full unknown-charge holds; not independently verified provider billing.")
    outstanding = [r for r in coverage if not r["task"].startswith("retail:") and r["status"] != "validated_complete"]
    failed = [r for r in outstanding if r["status"] in {"failed", "requires_review"}]
    status = {"stage": 3, "execution_route": "non-Retail first pass",
              "route_status": "validated_complete" if not outstanding else "requires_review" if failed else "in_progress_or_incomplete",
              "original_full_stage_status": "incomplete_native_failure_and_Retail_deferred" if failed else "incomplete_Retail_deferred",
              "validated_tasks": sum(r["status"] == "validated_complete" for r in coverage),
              "failed_tasks": len(failed),
              "outstanding_nonretail_tasks": [r["task"] for r in outstanding],
              "deferred_tasks": sum(r["status"] == "deferred" for r in coverage),
              "research_qualifications": ["Substituted gateway models; not exact published-model reproduction.",
                  "Factset extension is reported separately.", "No cross-family pooled score.",
                  "Returned model identifiers do not independently attest served model weights.",
                  "Raw transcripts and account metadata remain in ignored local evidence."]}
    write_json(PUBLIC / "status.json", status)
    write_json(PUBLIC / "evaluation_cohorts.json", cohorts)
    write_json(PUBLIC / "family_metrics.json", metrics)
    write_json(PUBLIC / "budget_summary.json", budget)
    write_csv(PUBLIC / "native_coverage.csv", coverage)
    usage = [{k: v for k, v in c.items() if k not in {"checks", "requested_models", "returned_models", "project_commit", "project_tracked_dirty", "observed_consulting_judgments", "observed_mean_judge_scores", "recovered_consulting_sessions"}} for c in cohorts]
    write_csv(PUBLIC / "evaluation_usage.csv", usage)
    write_csv(ROOT / "docs/results/native_coverage.csv", coverage)
    write_json(PRIVATE / "index.json", mapping)
    write_json(ROOT / "results/benchmarks/coverage.json", {"coverage": coverage, "local_cohorts": mapping})
    files = [p for p in PUBLIC.iterdir() if p.is_file() and p.name != "artifact_manifest.json"]
    write_json(PUBLIC / "artifact_manifest.json", {"hash_rule": "SHA-256 UTF-8 text with CRLF normalized to LF",
        "files": {p.name: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in sorted(files)}})
    print(json.dumps({**status, "aggregate_exposure_credits": summary["exposure_usd"]}, indent=2))


if __name__ == "__main__":
    main()
