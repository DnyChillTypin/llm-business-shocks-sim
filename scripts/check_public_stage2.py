"""Check the aggregate-only Stage 2 publication boundary; no API calls."""
import json
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/results/stage2"
FORBIDDEN = {"run_id", "attempt_id", "response_id", "episode_id", "approval_reference", "allowance_sha256", "artifact_sha256",
             "api_key", "authorization", "x-api-key", "balance", "remaining", "groups", "history", "source_request",
             "request_sha256", "system_fingerprint", "routing", "started_at_utc", "finished_at_utc", "reviewed_at_utc"}
PUBLIC_FILES = {"artifact_manifest.json", "pilot_cost_report.json", "budget_summary.json", "native_pilot_validations.json",
    "kaggle_pilot_validations.json", "kaggle_quality_reviews.json", "kaggle_validation_summary.json", "kaggle_validation_summary.csv",
    "kaggle_validation_daily.csv", "pilot_usage.csv", "cost_projections.csv", "pilot_coverage.csv", "matched_validation_inputs.json",
    "context_diagnostics.json", "budget_proposal_full_scope.json", "budget_proposal_nonretail_first_draft.json",
    "model_usage_summary.json", "gateway_rates.json", "qc_summary.json"}


def check(value):
    if isinstance(value, dict):
        bad = FORBIDDEN.intersection(k.lower() for k in value)
        if bad:
            raise ValueError(f"Private metadata fields in public aggregate: {sorted(bad)}")
        for item in value.values():
            check(item)
    elif isinstance(value, list):
        for item in value:
            check(item)


def main():
    count = 0
    for path in PUBLIC.iterdir():
        if not path.is_file():
            continue
        if path.name not in PUBLIC_FILES:
            raise ValueError(f"File outside the reviewed aggregate allowlist: {path.name}")
        if path.suffix == ".jsonl":
            raise ValueError("Request-level JSONL belongs in ignored local evidence.")
        text = path.read_text(encoding="utf-8")
        inspected = text
        if path.name == "gateway_rates.json":
            rates = json.loads(text)
            if rates.get("source") != "https://api.shopaikey.com/pricing":
                raise ValueError("Rate provenance must be the public tariff endpoint.")
            inspected = inspected.replace(rates.get("pricing_version", "not_present"), "PUBLIC_TARIFF_VERSION")
        if re.search(r"\b[0-9a-f]{32}\b|\b20\d{6}T\d{12,}Z\b", inspected):
            raise ValueError(f"Raw request/cohort identifier in {path.name}")
        if path.suffix == ".json":
            check(json.loads(text))
        elif path.suffix == ".csv":
            columns = next(csv.reader(text.splitlines()))
            if FORBIDDEN.intersection(columns):
                raise ValueError(f"Private metadata columns in {path.name}")
        count += 1
    print(f"Aggregate publication boundary passed: {count} files; no request IDs, transcripts, approval history or account/billing metadata.")


if __name__ == "__main__":
    main()
