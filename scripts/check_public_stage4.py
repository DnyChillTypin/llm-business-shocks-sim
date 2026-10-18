"""Check the saved Stage 4 aggregate boundary and exact validation/planned denominators."""
import csv
import hashlib
import json
import re
from pathlib import Path

from check_public_stage2 import check

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/results/stage4"
FILES = {"preparation.json", "status.json", "qc_summary.json", "validation_coverage.csv", "primary_plan.csv", "artifact_manifest.json"}


def main():
    paths = [p for p in PUBLIC.iterdir() if p.is_file()]
    assert {p.name for p in paths} == FILES
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b[0-9a-f]{32}\b|\b20\d{6}T\d{12,}Z\b", text), path.name
        if path.suffix == ".json":
            check(json.loads(text))
        else:
            for row in csv.DictReader(text.splitlines()):
                check(row)
    manifest = json.loads((PUBLIC / "artifact_manifest.json").read_text())
    assert manifest["hash_rule"] == "SHA-256 UTF-8 text with CRLF normalized to LF"
    assert set(manifest["files"]) == FILES - {"artifact_manifest.json"}
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((PUBLIC / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest
    qc = json.loads((PUBLIC / "qc_summary.json").read_text())
    assert qc["exit_gate_passed"] and all(qc["checks"].values())
    assert qc["new_model_completion_calls"] == qc["new_primary_policy_episodes"] == 0
    coverage = list(csv.DictReader((PUBLIC / "validation_coverage.csv").read_text().splitlines()))
    assert len(coverage) == 36 and sum(int(r["days"]) for r in coverage) == 756
    assert len({(r["store_id"], r["product_id"], r["scenario"], r["policy"]) for r in coverage}) == 36
    assert all(r["status"] == "validated_complete" and r["model_completion_calls"] == "0" for r in coverage)
    assert sum(r["agent_kind"] == "baseline" for r in coverage) == 24
    assert sum(r["agent_kind"] == "scripted" for r in coverage) == 12
    assert all(r["legacy_baseline_parity"] == "True" for r in coverage if r["agent_kind"] == "baseline")
    planned = list(csv.DictReader((PUBLIC / "primary_plan.csv").read_text().splitlines()))
    assert len(planned) == 36 and sum(int(r["planned_days"]) for r in planned if r["policy"] == "llm_with_fallback") == 252
    assert all(r["primary_execution_status"] == "not_executed" for r in planned)
    template = ROOT / "configs/runs/kaggle_primary.template.json"
    assert hashlib.sha256(template.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == qc["primary_authorization_template_sha256"]
    authorization = json.loads(template.read_text())
    assert authorization["approved"] is False and authorization["budget_id"] is None and authorization["max_attempts"] == 504
    print("Stage 4 public boundary, hashes, 36 validation fixtures and unexecuted primary plan passed.")


if __name__ == "__main__":
    main()
