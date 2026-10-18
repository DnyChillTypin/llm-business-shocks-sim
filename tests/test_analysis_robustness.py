import hashlib
import tempfile
import unittest
from pathlib import Path

from src.analysis.robustness import isolated_inputs, validate_baseline
from src.experiments.kaggle_protocol import read, write


class SensitivityIsolationTests(unittest.TestCase):
    def test_override_changes_only_the_copy_and_rebuilds_its_manifest_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "primary"
            base.mkdir()
            write(base / "manifest.json", dict(settings=dict(elasticity=1.5, holding_cost_ratio=.001), initial_funds=100))
            (base / "episode.csv").write_text("private demand remains unchanged\n")
            write(base / "artifact_checksums.json", {})
            before = {p.name: p.read_bytes() for p in base.iterdir()}
            target = isolated_inputs(base, Path(temporary) / "sensitivity", .75)
            self.assertEqual(before, {p.name: p.read_bytes() for p in base.iterdir()})
            changed, original = read(target / "manifest.json"), read(base / "manifest.json")
            self.assertEqual(changed["settings"].pop("elasticity"), .75)
            original["settings"].pop("elasticity")
            self.assertEqual(changed, original)
            self.assertEqual((target / "episode.csv").read_bytes(), before["episode.csv"])
            checksums = read(target / "artifact_checksums.json")
            self.assertEqual(checksums["manifest.json"], hashlib.sha256((target / "manifest.json").read_bytes()).hexdigest())

    def test_nested_primary_target_and_unplanned_assumptions_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "primary"
            source.mkdir()
            for target, elasticity in ((source / "child", .75), (Path(temporary) / "other", 2.0)):
                with self.assertRaises(ValueError):
                    isolated_inputs(source, target, elasticity)

    def test_baseline_validator_rejects_llm_and_undeclared_sensitivity_before_io(self):
        for policy, elasticity in (("llm_with_fallback", .75), ("adaptive", 3.0)):
            with self.assertRaises(ValueError):
                validate_baseline("unused", "unused", elasticity=elasticity, scenario="control", policy=policy, cache="unused")
