"""Read saved genuine runs without contacting a model or changing scores."""
import hashlib
import json
from datetime import date, datetime, timedelta
import re
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_run(folder):
    folder = Path(folder)
    checks, qualifications = {}, []
    manifest = read(folder / "run_manifest.json")
    task = manifest["task"]
    checks["execution_succeeded"] = read(folder / "exit_status.json")["exit_code"] == 0
    checks["execution_finished"] = manifest["status"] == "execution_finished_requires_artifact_review"
    events = [json.loads(line) for line in (folder / "api_attempts.jsonl").read_text(encoding="utf-8").splitlines()]
    starts = {e["attempt_id"]: e for e in events if e["event"] == "started"}
    finishes = {e["attempt_id"]: e for e in events if e["event"] == "finished"}
    parses = {e["attempt_id"]: e for e in events if e["event"] == "parse_checked"}
    checks["all_attempts_finished"] = bool(starts) and starts.keys() == finishes.keys()
    checks["all_responses_valid"] = starts.keys() == parses.keys() and all(e["parse_status"] == "valid" for e in parses.values())
    checks["all_usage_known"] = all(e["status"] == "completed" and e.get("cost_usd") is not None for e in finishes.values())
    checks["raw_artifacts_present"] = all((folder / "attempts" / key / "response.json").is_file() and
                                               (folder / "attempts" / key / "request.json").is_file() for key in starts)
    totals = read(folder / "usage_totals.json")
    checks["totals_reconcile"] = (totals["attempts"] == len(starts) and
        totals["input_tokens"] == sum((e.get("usage") or {}).get("prompt_tokens", 0) for e in finishes.values()) and
        totals["output_tokens"] == sum((e.get("usage") or {}).get("completion_tokens", 0) for e in finishes.values()))
    budget = read(folder / "budget_summary.json")
    checks["accounting_settled"] = budget["pending_attempts"] == budget.get("blocking_uncertain_attempts", budget["uncertain_attempts"]) == 0
    checks["native_result_saved"] = (folder / "native_result.json").is_file()
    result = read(folder / "native_result.json") if checks["native_result_saved"] else None
    if isinstance(result, dict) and "total" in result:
        checks["native_coverage"] = result["total"] == manifest["expected_units"] and result["no_answer"] == 0
        checks["frozen_case_ids"] = {e["context"]["case_id"] for e in starts.values()} == set(manifest["selected_case_ids"])
        saved = list(folder.rglob("test_results.json"))
        checks["native_score_artifact"] = len(saved) == 1 and read(saved[0])["test_results"] == result
    elif task == "firm:consulting" and result:
        checks["native_coverage"] = (result["num_cases"] == result["num_finished"] == manifest["expected_units"] and result["num_failed"] == 0)
        checks["judge_observed"] = any(e["context"].get("validation_kind") == "judge" for e in starts.values())
    elif task == "firm:beergame" and result:
        checks["native_coverage"] = result["episodes"] == manifest["expected_units"]
        checks["full_25_week_horizon"] = all(e.get("weeks_completed") == 25 for e in result["episode_metrics"])
    elif task == "firm:edt":
        rollouts = list(folder.rglob("rollout.json"))
        checks["full_96_step_horizon"] = len(rollouts) == manifest["expected_units"] and all(read(p)["steps"] == 96 for p in rollouts)
        checks["decision_audit"] = (folder / "decision_events.jsonl").is_file()
    elif task == "icbe":
        import openpyxl
        paths = list(folder.glob("*.xlsx"))
        checks["native_workbook"] = len(paths) == 1
        if len(paths) == 1:
            book = openpyxl.load_workbook(paths[0], read_only=True, data_only=True)
            try:
                checks["full_ordered_pairs_and_rounds"] = book["Detailed Logs"].max_row - 1 == manifest["expected_units"] * manifest["configured_horizon"]
            finally:
                book.close()
        checks["all_decisions_logged"] = len(starts) == 2 * manifest["expected_units"] * manifest["configured_horizon"]
        qualifications.append("Two-round pilots cover the early native phase only. Workbook filename retains upstream 100Rounds regardless of configured horizon.")
    elif task.startswith("retail:"):
        checkpoints = [p for p in (folder / "checkpoints").glob("*.json") if re.fullmatch(r"day_\d+_checkpoint.json", p.name)]
        checks["daily_checkpoints"] = len(checkpoints) == manifest["configured_horizon"]
        trace = read(folder / "retail_trace.json") if (folder / "retail_trace.json").is_file() else []
        starts_by_day = {e["day"]: e for e in trace if e.get("message") == f"Day {e.get('day')} started"}
        checks["actual_daily_date_transitions"] = (len(starts_by_day) == manifest["configured_horizon"] and
            all(pdata["day"] in starts_by_day and date.fromisoformat(pdata["current_date"][:10]) ==
                date.fromisoformat(starts_by_day[pdata["day"]]["current_date"][:10]) + timedelta(days=1)
                for pdata in map(read, checkpoints)))
        forced = [e for e in trace if "Forced end_today" in str(e.get("message", ""))]
        checks["no_forced_day_transition"] = not forced
        qualifications.append("Retail needs review of tool errors and date transitions; checkpoint count alone does not establish decision quality.")
    else:
        checks["known_native_validator"] = False
    elapsed = (datetime.fromisoformat(manifest["finished_at_utc"]) - datetime.fromisoformat(manifest["started_at_utc"])).total_seconds()
    return {"run_id": folder.name, "task": task, "purpose": manifest["purpose"],
            "status": "validated_complete" if all(checks.values()) else "requires_review",
            "checks": checks, "qualifications": qualifications, "native_score": result,
            "attempts": len(starts), "input_tokens": totals["input_tokens"], "output_tokens": totals["output_tokens"],
            "estimated_gateway_credit_usd": sum(e.get("cost_usd") or 0 for e in finishes.values()),
            "missing_usage_attempts": sum(e.get("cost_usd") is None for e in finishes.values()),
            "api_latency_seconds": [e["latency_seconds"] for e in finishes.values()], "elapsed_seconds": elapsed,
            "models": sorted({e["requested_model"] for e in starts.values()}),
            "returned_models": sorted({e.get("returned_model") or "not_reported" for e in finishes.values()}),
            "artifact_sha256": {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in
                                ["run_manifest.json", "api_attempts.jsonl", "native_result.json", "runtime_identity.json"] if (folder / name).exists()},
            "cost_qualification": "Token-derived uncached gateway-tariff upper estimate, not independently verified billing.",
            "identity_qualification": "Returned model identifiers do not independently attest the actual served model."}
