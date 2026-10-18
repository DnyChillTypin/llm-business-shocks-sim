"""Rehashed edits must still fail the independent saved-result reconciliation."""
import csv
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_public_stage5 import check_execution
from src.experiments.kaggle_protocol import read, write, primary_matrix


class PrimaryReportingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / ".cache")
        self.addCleanup(self.temporary.cleanup)
        self.public = Path(self.temporary.name) / "public"
        shutil.copytree(ROOT / "docs/results/stage5", self.public)
        self.matrix = primary_matrix(read(ROOT / "configs/study.json"))
        self.before = read(self.public / "preparation.json")["budget_snapshot"]

    def rehash(self, name):
        manifest = read(self.public / "artifact_manifest.json")
        manifest["files"][name] = hashlib.sha256((self.public / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        write(self.public / "artifact_manifest.json", manifest)

    def edit_csv(self, name, edit):
        path = self.public / name
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        edit(rows)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        self.rehash(name)

    def assert_rejected(self):
        with self.assertRaises(AssertionError):
            check_execution(self.public, self.matrix, self.before)

    def test_rehashed_contribution_edit_is_rejected_by_daily_reconciliation(self):
        self.edit_csv("coverage.csv", lambda rows: rows[0].update(contribution=float(rows[0]["contribution"]) + 1))
        self.assert_rejected()

    def test_rehashed_fallback_edit_is_rejected_by_episode_flags(self):
        def change(rows):
            row = next(r for r in rows if r["policy"] == "llm_with_fallback")
            row["fallback_used"] = "False" if row["fallback_used"] == "True" else "True"
        self.edit_csv("daily_results.csv", change)
        self.assert_rejected()

    def test_rehashed_cost_edit_is_rejected_by_cohort_and_carryover_totals(self):
        status = read(self.public / "status.json")
        status["budget_snapshot"]["primary_exposure_credits"] += .01
        write(self.public / "status.json", status)
        self.rehash("status.json")
        self.assert_rejected()


if __name__ == "__main__":
    unittest.main()
