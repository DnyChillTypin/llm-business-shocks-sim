"""Bind report 2 engineering code separately from the unchanged sampling freeze."""
import hashlib
from pathlib import Path

from src.research.report2 import ROOT, MANIFEST, build_manifest, canonical_hash, read_json

RUNTIME = "configs/report2/implementation_manifest.json"
FILES = (
    "src/experiments/report2.py", "src/experiments/report2_fixtures.py",
    "src/research/report2_runtime.py", "scripts/run_report2_pilot.py",
    "scripts/check_report2_runner.py", "tests/test_report2_runner.py",
    "src/experiments/kaggle.py", "src/experiments/kaggle_protocol.py",
    "src/benchmarks/common.py", "src/benchmarks/budget.py",
    "src/benchmarks/gateway.py", "src/benchmarks/errors.py",
    "configs/benchmarks.json", "requirements-research.txt",
)


def implementation_manifest(root=ROOT):
    sampling = read_json(root / MANIFEST)
    if sampling != build_manifest(root):
        raise ValueError("Milestone 1 sampling or frozen inputs changed.")
    result = {"schema_version": 1, "milestone": 2,
              "sampling_sha256": sampling["manifest_sha256"],
              "restoration": "Audited seven-day deterministic replay",
              "opaque_fields_excluded": ["native UUIDs", "log timestamps"],
              "model_execution": "user_manually_only", "model_calls_authorized": False,
              "production_runner_enabled": False,
              "input_text_sha256": {name: hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                                    for name in FILES}}
    result["implementation_sha256"] = canonical_hash(result)
    return result


def verify_implementation(root=ROOT):
    expected = implementation_manifest(root)
    if expected != read_json(root / RUNTIME):
        raise ValueError("Runner implementation changed after its milestone freeze.")
    return expected
