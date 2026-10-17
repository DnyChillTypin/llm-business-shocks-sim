"""Export a small, sanitized, saved-only Stage 2 evidence package."""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis.costs import cost_report
from src.benchmarks.common import TASKS
from src.benchmarks.validation import validate_run


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    # Detailed run IDs, request telemetry, approvals and account evidence stay
    # in ignored local storage. Publish only the explicit aggregate allowlist.
    out = ROOT / "results/analysis/stage2/private_evidence"
    out.mkdir(parents=True, exist_ok=True)
    validations, native_events, kaggle_events, episodes, frames, kaggle_checks, reviews = [], [], [], [], [], [], []
    for path in sorted((ROOT / "results/benchmarks").glob("*/*/run_manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["purpose"] != "pilot":
            continue
        run = path.parent
        report = validate_run(run)
        write(run / "validation.json", report)
        validations.append(report)
        native_events.extend(json.loads(line) for line in (run / "api_attempts.jsonl").read_text(encoding="utf-8").splitlines())
    for path in sorted((ROOT / "results/runs/kaggle_retailbench").glob("*/run_manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("purpose") != "pilot":
            continue
        run = path.parent
        if (run / "api_attempts.jsonl").exists():
            kaggle_events.extend(json.loads(line) for line in (run / "api_attempts.jsonl").read_text(encoding="utf-8").splitlines())
        if manifest["status"] == "validated_complete":
            summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
            episodes.append({"run_id": run.name, "window": manifest["window"], **summary})
            frame = pd.read_csv(run / "daily_results.csv")
            frame["run_id"], frame["window"] = run.name, manifest["window"]
            frames.append(frame)
        if (run / "validation.json").exists():
            kaggle_checks.append(json.loads((run / "validation.json").read_text(encoding="utf-8")))
        if (run / "quality_review.json").exists():
            reviews.append(json.loads((run / "quality_review.json").read_text(encoding="utf-8")))
    report = cost_report()
    assert report["totals"]["validated_native_pilot_tasks"] == len(TASKS) == 19
    assert report["totals"]["kaggle_validation_decisions"] == 42
    assert len(episodes) == 6 and len(kaggle_checks) == 2 and len(reviews) == 2
    matched = []
    for episode in episodes:
        run = ROOT / "results/runs/kaggle_retailbench" / episode["run_id"]
        initial = json.loads((run / "observations.jsonl").read_text(encoding="utf-8").splitlines()[0])
        manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
        frame = pd.read_csv(run / "daily_results.csv")
        matched.append({"run_id": run.name, "scenario": episode["scenario"], "policy": episode["policy"],
            "initial_observation_sha256": initial["sha256"], "prepared_checksums_sha256": manifest["prepared_checksums_sha256"],
            "base_demand_sha256": hashlib.sha256(frame[["date", "sku_id", "base_demand"]].to_csv(index=False).encode()).hexdigest()})
    for field in ("initial_observation_sha256", "prepared_checksums_sha256", "base_demand_sha256"):
        assert len({r[field] for r in matched}) == 1, field
    write(out / "matched_validation_inputs.json", {"status": "passed", "episodes": matched})
    assert report["totals"]["latest_budget"]["exposure_usd"] <= 2
    assert report["totals"]["attempts"] <= 250
    ledger = ROOT / "results/budgets/stage2_pilot_v1.sqlite"
    if not ledger.is_file():
        raise FileNotFoundError("Preserve the actual pilot ledger before exporting its audit.")
    db = sqlite3.connect(ledger)
    try:
        amendments = []
        for at, previous, current in db.execute("SELECT at,previous_manifest,new_manifest FROM allowance_amendments"):
            old, new = json.loads(previous), json.loads(current)
            amendments.append({"at_utc": at, "previous_cap_usd": old["cap_usd"], "new_cap_usd": new["cap_usd"],
                "approval_reference": new["approval_reference"], "max_attempts": new["max_attempts"],
                "scope_caps_usd": new["scope_caps_usd"], "bounded_unknown_failure_categories": new.get("bounded_unknown_failure_categories", [])})
        holds = [{"attempt_id": a, "approval_reference": reference, "at_utc": at, "explanation": explanation,
                  "reserved_credit_usd": reserve / 1e9, "actual_charge_usd": None, "status": status, "scope": scope}
                 for a, reference, at, explanation, reserve, status, scope in db.execute(
                     "SELECT h.attempt_id,h.approval_reference,h.at,h.explanation,a.reserved_nanos,a.status,a.scope FROM bounded_holds h JOIN attempts a ON a.id=h.attempt_id")]
    finally:
        db.close()
    write(out / "budget_audit.json", {"budget_id": "stage2_pilot_v1", "original_ledger_preserved": True,
        "allowance_amendments": amendments, "fully_retained_unknown_charge_holds": holds})
    write(out / "pilot_cost_report.json", report)
    write(out / "budget_summary.json", report["totals"]["latest_budget"])
    write(out / "native_pilot_validations.json", validations)
    write(out / "kaggle_pilot_validations.json", kaggle_checks)
    write(out / "kaggle_quality_reviews.json", reviews)
    write(out / "kaggle_validation_summary.json", episodes)
    write(out / "context_diagnostics.json", json.loads((ROOT / "results/verification/stage2/context_diagnostics.json").read_text()))
    for name, values in [("native_pilot_attempts.jsonl", native_events), ("kaggle_pilot_attempts.jsonl", kaggle_events)]:
        (out / name).write_text("".join(json.dumps(row) + "\n" for row in values), encoding="utf-8")
    pd.DataFrame(report["observations"]).to_csv(out / "pilot_usage.csv", index=False)
    pd.DataFrame(report["projections"]).to_csv(out / "cost_projections.csv", index=False)
    pd.DataFrame(episodes).to_csv(out / "kaggle_validation_summary.csv", index=False)
    pd.concat(frames, ignore_index=True).to_csv(out / "kaggle_validation_daily.csv", index=False)
    coverage = []
    for task in TASKS:
        valid = [r for r in validations if r["task"] == task and r["status"] == "validated_complete"]
        coverage.append({"task": task, "pilot_status": "validated_complete", "run_id": valid[-1]["run_id"],
                         "full_evaluation_completed": False})
    pd.DataFrame(coverage).to_csv(out / "pilot_coverage.csv", index=False)
    for cap, label, attempts, exclude_retail in [(report["totals"]["proposed_inclusive_full_cap_usd"], "full_scope", 30000, False),
                                                (report["totals"]["proposed_inclusive_nonretail_cap_usd"], "nonretail_first_draft", 3000, True)]:
        write(out / f"budget_proposal_{label}.json", {"approved": False, "currency": "USD_gateway_credit", "proposed_total_cap_inclusive_of_pilots": cap,
            "carry_forward_existing_pilot_exposure_usd": report["totals"]["latest_budget"]["exposure_usd"],
            "proposed_max_client_attempts_inclusive_of_pilots": attempts, "unallocated_reserve_fraction_at_least": .2,
            "retail_full_horizons_included": not exclude_retail, "evaluation_requires_separate_approval": True,
            "qualification": "Proposal from declared high planning scenarios, not a guaranteed worst-case bill. Preserve prior spending and held charges; do not reset the allowance."})
    files = [p for p in out.iterdir() if p.is_file() and p.name != "artifact_manifest.json"]
    write(out / "artifact_manifest.json", {"hash_rule": "SHA-256 UTF-8 text with CRLF normalized to LF", "files": {
        p.name: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in sorted(files)}})
    export_public_aggregates(out)
    print(json.dumps({"validated_native_tasks": 19, "completed_validation_episodes": len(episodes),
                      "completed_llm_validation_days": 42, "paid_primary_evaluation_episodes": 0,
                      "attempts": report["totals"]["attempts"], "exposure_usd": report["totals"]["latest_budget"]["exposure_usd"]}, indent=2))


def export_public_aggregates(private):
    """No request IDs, API transcripts, approval history or account balances."""
    import statistics
    public = ROOT / "docs/results/stage2"
    public.mkdir(parents=True, exist_ok=True)
    load = lambda name: json.loads((private / name).read_text(encoding="utf-8"))
    raw = load("pilot_cost_report.json")
    names = {r["run_id"]: f"pilot_{i:02d}" for i, r in enumerate(raw["observations"], 1)}
    blocked = {"run_id", "episode_id", "response_id", "attempt_id", "artifact_sha256", "api_latency_seconds",
               "started_at_utc", "finished_at_utc", "approval_reference", "allowance_sha256", "source_request", "request_sha256"}
    def scrub(value):
        if isinstance(value, dict):
            result = {k: scrub(v) for k, v in value.items() if k not in blocked}
            if value.get("run_id") in names:
                result["cohort"] = names[value["run_id"]]
            return result
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value
    observations = []
    for item in raw["observations"]:
        row = scrub(item)
        latencies = row.pop("latency_seconds", [])
        row.update(median_latency_seconds=statistics.median(latencies) if latencies else None,
                   mean_latency_seconds=statistics.mean(latencies) if latencies else None)
        observations.append(row)
    projections = []
    for item in raw["projections"]:
        row = dict(item)
        identity = row.pop("measured_run_id", None)
        row["measurement_cohort"] = names.get(identity)
        projections.append(row)
    budget_keys = {"currency", "attempts", "known_cost_usd", "unresolved_reserved_usd", "exposure_usd", "pending_attempts",
                   "uncertain_attempts", "bounded_carried_attempts", "bounded_carried_reserve_usd", "blocking_uncertain_attempts",
                   "cap_usd", "cost_basis", "limit_qualification"}
    budget = {k: v for k, v in raw["totals"]["latest_budget"].items() if k in budget_keys}
    totals = {**raw["totals"], "latest_budget": budget}
    safe = {"purpose": raw["purpose"], "observations": observations, "projections": projections, "totals": totals}
    write(public / "pilot_cost_report.json", safe)
    write(public / "budget_summary.json", budget)
    write(public / "native_pilot_validations.json", scrub(load("native_pilot_validations.json")))
    checks = scrub(load("kaggle_pilot_validations.json"))
    for row in checks:
        for field in ("initial_observation_sha256", "prepared_checksums_sha256", "base_demand_sha256"):
            row.pop(field, None)
    write(public / "kaggle_pilot_validations.json", checks)
    reviews = []
    for r in load("kaggle_quality_reviews.json"):
        reviews.append({k: r[k] for k in ("status", "decision", "scenario", "decision_opportunities", "repair_days", "fallback_days", "invalid_responses", "rationale", "required_reporting", "evaluation_authorized")})
    write(public / "kaggle_quality_reviews.json", reviews)
    episodes = scrub(load("kaggle_validation_summary.json"))
    write(public / "kaggle_validation_summary.json", episodes)
    pd.DataFrame(episodes).to_csv(public / "kaggle_validation_summary.csv", index=False)
    daily = pd.read_csv(private / "kaggle_validation_daily.csv").drop(columns=["run_id"])
    daily.to_csv(public / "kaggle_validation_daily.csv", index=False)
    pd.DataFrame(observations).to_csv(public / "pilot_usage.csv", index=False)
    pd.DataFrame(projections).to_csv(public / "cost_projections.csv", index=False)
    coverage = pd.read_csv(private / "pilot_coverage.csv")
    coverage["cohort"] = coverage["run_id"].map(names)
    coverage.drop(columns=["run_id"]).to_csv(public / "pilot_coverage.csv", index=False)
    write(public / "matched_validation_inputs.json", {"status": "passed", "episodes": 6,
        "identical_initial_observations": True, "identical_prepared_inputs": True, "identical_base_demand_paths": True})
    context = load("context_diagnostics.json")
    context = scrub(context)
    write(public / "context_diagnostics.json", context)
    for name in ("budget_proposal_full_scope.json", "budget_proposal_nonretail_first_draft.json"):
        write(public / name, load(name))
    events = []
    for name in ("native_pilot_attempts.jsonl", "kaggle_pilot_attempts.jsonl"):
        events.extend(json.loads(line) for line in (private / name).read_text(encoding="utf-8").splitlines())
    model_summary = []
    for model in sorted({e["requested_model"] for e in events if e["event"] == "finished"}):
        rows = [e for e in events if e["event"] == "finished" and e["requested_model"] == model]
        latencies = pd.Series([e["latency_seconds"] for e in rows])
        model_summary.append({"requested_model": model, "returned_models": sorted({e.get("returned_model") for e in rows if e.get("returned_model")}),
            "attempts": len(rows), "missing_usage_attempts": sum(e.get("cost_usd") is None for e in rows),
            "input_tokens": sum((e.get("usage") or {}).get("prompt_tokens", 0) for e in rows),
            "output_tokens": sum((e.get("usage") or {}).get("completion_tokens", 0) for e in rows),
            "known_estimated_cost_usd": sum(e.get("cost_usd") or 0 for e in rows),
            "median_latency_seconds": float(latencies.median()), "p95_latency_seconds": float(latencies.quantile(.95))})
    write(public / "model_usage_summary.json", model_summary)
    snapshot = json.loads((ROOT / "results/verification/stage2/gateway_final_snapshot.json").read_text(encoding="utf-8"))
    rates = {model: {k: value for k, value in row.items() if k in {"input_per_million", "output_per_million", "per_request"}}
             for model, row in snapshot["rates"].items()}
    write(public / "gateway_rates.json", {"provider": "ShopAIKey", "source": "https://api.shopaikey.com/pricing",
        "checked_on": snapshot["checked_at_utc"][:10], "pricing_version": snapshot["pricing_version"], "rates": rates})
    qc = load("qc_summary.json")
    qc.pop("local_test_log_sha256", None)
    qc["checked_on"] = qc.pop("checked_at_utc")[:10]
    write(public / "qc_summary.json", qc)
    write(private / "public_cohort_mapping.json", names)
    # Remove only explicitly enumerated detailed exports after the complete local
    # backup above. This never recursively deletes or touches raw experiment runs.
    detailed = ["native_pilot_attempts.jsonl", "kaggle_pilot_attempts.jsonl", "billing_reconciliation.json", "budget_audit.json",
        "allowance_amendment.json", "gateway_snapshot.json", "gateway_final_snapshot.json", "first_codefinqa_response.json",
        "first_codefinqa_validation.json", "first_codefinqa_score.json"]
    for name in detailed:
        path = public / name
        if path.exists():
            if not (private / name).is_file():
                raise RuntimeError(f"Missing local backup for detailed artifact {name}")
            path.unlink()
    files = [p for p in public.iterdir() if p.is_file() and p.name != "artifact_manifest.json"]
    write(public / "artifact_manifest.json", {"hash_rule": "SHA-256 UTF-8 text with CRLF normalized to LF",
        "publication_scope": "Aggregate synthetic research metrics only; no request IDs, transcripts, approval history or account/billing records.",
        "files": {p.name: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in sorted(files)}})


if __name__ == "__main__":
    main()
