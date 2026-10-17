"""Verify the aggregate Stage 3 publication boundary without contacting a model."""
import csv
import hashlib
import json
import re
from pathlib import Path

from check_public_stage2 import check

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/results/stage3"
FILES = {"artifact_manifest.json", "status.json", "evaluation_cohorts.json", "family_metrics.json",
         "budget_summary.json", "native_coverage.csv", "evaluation_usage.csv", "qc_summary.json"}


def main():
    paths = [p for p in PUBLIC.iterdir() if p.is_file()]
    if {p.name for p in paths} - FILES:
        raise ValueError("Unexpected Stage 3 public artifact; inspect its publication scope.")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if re.search(r"\b[0-9a-f]{32}\b|\b20\d{6}T\d{12,}Z\b", text):
            raise ValueError(f"Raw request/cohort identifier in {path.name}")
        if path.suffix == ".json":
            check(json.loads(text))
        else:
            for row in csv.DictReader(text.splitlines()):
                check(row)
    provenance = json.loads((PUBLIC / "artifact_manifest.json").read_text())
    assert provenance["hash_rule"] == "SHA-256 UTF-8 text with CRLF normalized to LF"
    manifest = provenance["files"]
    assert set(manifest) == {p.name for p in paths} - {"artifact_manifest.json"}
    for name, digest in manifest.items():
        assert hashlib.sha256((PUBLIC / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest, name
    assert (ROOT / "docs/results/native_coverage.csv").read_bytes() == (PUBLIC / "native_coverage.csv").read_bytes()
    print(f"Stage 3 aggregate publication boundary and artifact hashes passed: {len(paths)} files.")


if __name__ == "__main__":
    main()
