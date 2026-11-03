import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from scripts import build_report2
from scripts import run_report2_stage5 as runner
from src.analysis.report2_stage5 import (
    OUTCOMES, block_means, describe, evidence_fingerprint, history_contrasts, paired_contrasts, recovery_delay,
    reliability, restart_events, restart_summary, verify_claim_evidence,
)
from src.experiments.report2 import evidence_hashes


def days(values_by_day, default):
    """14-element sequence for days 8..21 with overrides {day: value}."""
    return [values_by_day.get(d, default) for d in range(8, 22)]


class TestRecoveryRule(unittest.TestCase):
    control = days({}, 100.0)

    def test_immediate_recovery_at_day_15(self):
        self.assertEqual(recovery_delay(days({}, 100.0), days({}, 0), self.control), 1)

    def test_onset_day_19_qualifying_through_day_21(self):
        inv = days({d: 0.0 for d in range(8, 19)}, 100.0)
        self.assertEqual(recovery_delay(inv, days({}, 0), self.control), 5)

    def test_onset_after_day_19_is_censored(self):
        inv = days({d: 0.0 for d in range(8, 20)}, 100.0)
        self.assertIsNone(recovery_delay(inv, days({}, 0), self.control))

    def test_lost_sales_break_the_run(self):
        lost = days({16: 3}, 0)
        self.assertEqual(recovery_delay(days({}, 100.0), lost, self.control), 3)  # 17,18,19

    def test_tolerance_is_inclusive_and_relative_to_control(self):
        self.assertEqual(recovery_delay(days({}, 120.0), days({}, 0), self.control), 1)
        self.assertIsNone(recovery_delay(days({}, 120.1), days({}, 0), self.control))

    def test_zero_control_inventory_uses_floor_of_one(self):
        zero = days({}, 0.0)
        self.assertEqual(recovery_delay(days({}, 0.2), days({}, 0), zero), 1)
        self.assertIsNone(recovery_delay(days({}, 0.3), days({}, 0), zero))


def llm_rows(block, scenario, contributions, history="full", elasticity=1.5):
    rows = []
    for r, c in enumerate(contributions):
        row = {k: 0.0 for k in OUTCOMES}
        row.update(block_id=block, scenario=scenario, history=history, elasticity=elasticity,
                   realization=r, contribution=c, fill_rate=1.0)
        rows.append(row)
    return rows


def base_rows(block, scenario, adaptive, fixed, elasticity=1.5):
    out = []
    for policy, c in (("adaptive", adaptive), ("fixed", fixed)):
        row = {k: 0.0 for k in OUTCOMES}
        row.update(block_id=block, scenario=scenario, elasticity=elasticity, policy=policy,
                   contribution=c, fill_rate=0.9)
        out.append(row)
    return out


class TestContrasts(unittest.TestCase):
    def setUp(self):
        llm = (llm_rows("B1", "control", [100, 110, 120]) + llm_rows("B1", "demand_surge", [90, 90, 120])
               + llm_rows("B1", "control", [80, 80, 80], history="none")
               + llm_rows("B1", "demand_surge", [60, 60, 60], history="none")
               + llm_rows("B1", "control", [110, 110, 110], history="frozen")
               + llm_rows("B1", "demand_surge", [130, 130, 130], history="frozen"))
        base = base_rows("B1", "control", 130, 50) + base_rows("B1", "demand_surge", 140, 40)
        self.blocks = block_means(pd.DataFrame(llm))
        self.contrasts = paired_contrasts(self.blocks, pd.DataFrame(base))

    def get(self, scenario, history="full"):
        c = self.contrasts
        return c[(c["scenario"] == scenario) & (c["history"] == history)].iloc[0]

    def test_realizations_averaged_before_contrast(self):
        self.assertAlmostEqual(self.get("control")["contribution"], 110)
        self.assertEqual(self.get("control")["realizations"], 3)
        self.assertEqual((self.get("demand_surge")["contribution_min"], self.get("demand_surge")["contribution_max"]), (90, 120))

    def test_raw_and_adjusted_signs(self):
        self.assertAlmostEqual(self.get("control")["raw_vs_adaptive"], -20)
        self.assertAlmostEqual(self.get("demand_surge")["raw_vs_adaptive"], -40)
        # (100 - 110) - (140 - 130) = -20
        self.assertAlmostEqual(self.get("demand_surge")["adjusted_vs_adaptive"], -20)
        self.assertTrue(np.isnan(self.get("control")["adjusted_vs_adaptive"]))
        self.assertAlmostEqual(self.get("demand_surge")["raw_vs_fixed"], 60)

    def test_control_adjustment_stays_within_history(self):
        # none: (60 - 80) - (140 - 130) = -30
        self.assertAlmostEqual(self.get("demand_surge", "none")["adjusted_vs_adaptive"], -30)

    def test_history_contrast_full_minus_ablation(self):
        h = history_contrasts(self.blocks, {"B1"})
        none = h[h["ablation"] == "none"].set_index("scenario")
        self.assertAlmostEqual(none.loc["control", "full_minus_ablation"], 30)
        self.assertAlmostEqual(none.loc["demand_surge", "full_minus_ablation"], 40)
        self.assertAlmostEqual(none.loc["demand_surge", "shock_minus_control"], 10)
        frozen = h[h["ablation"] == "frozen"].set_index("scenario")
        self.assertAlmostEqual(frozen.loc["demand_surge", "full_minus_ablation"], -30)
        self.assertAlmostEqual(frozen.loc["demand_surge", "shock_minus_control"], -30)

    def test_missing_baseline_fails(self):
        with self.assertRaises(ValueError):
            paired_contrasts(self.blocks, pd.DataFrame(base_rows("B1", "control", 1, 1)))


class TestSummaries(unittest.TestCase):
    def test_describe_counts_signs_and_ignores_missing(self):
        d = describe(pd.Series([-2.0, 0.0, 3.0, np.nan]))
        self.assertEqual((d["n_blocks"], d["n_positive"], d["n_negative"]), (3, 1, 1))
        self.assertEqual((d["min"], d["median"], d["max"]), (-2.0, 0.0, 3.0))

    def test_reliability_denominators(self):
        llm = pd.DataFrame([{
            "setting": "main", "completed_decisions": 14, "first_pass_valid": 10, "repair_attempts": 4,
            "successful_repairs": 3, "fallback_days": 1, "api_attempts": 18, "input_tokens": 1,
            "output_tokens": 1, "known_credits": 0.01, "latency_total": 28.0}] * 2)
        r = reliability(llm).iloc[0]
        self.assertEqual(r["scheduled_decisions"], 28)
        self.assertAlmostEqual(r["first_pass_valid_share"], 20 / 28)
        self.assertAlmostEqual(r["repair_success_rate"], 6 / 8)
        self.assertAlmostEqual(r["fallback_share"], 2 / 28)
        # first-pass valid + successful repairs + fallback = all decisions
        self.assertEqual(r["first_pass_valid"] + r["successful_repairs"] + r["fallback_days"], r["completed_decisions"])

    def test_matched_diagnostic_subset(self):
        def row(setting, block, first):
            return {"setting": setting, "block_id": block, "completed_decisions": 14, "first_pass_valid": first,
                    "repair_attempts": 14 - first, "successful_repairs": 14 - first - 1, "fallback_days": 1,
                    "api_attempts": 28 - first, "input_tokens": 1, "output_tokens": 1, "known_credits": 0.01,
                    "latency_total": 14.0}
        llm = pd.DataFrame([row("main", "D1", 13), row("main", "D1", 13), row("main", "X1", 1),
                            row("history_none", "D1", 12)])
        r = reliability(llm, {"D1"}).set_index("setting")
        self.assertEqual(list(r.index), ["main", "history_none", "main_diagnostic"])
        self.assertEqual((r.loc["main_diagnostic", "branches"], r.loc["main_diagnostic", "blocks"]), (2, 1))
        self.assertAlmostEqual(r.loc["main_diagnostic", "first_pass_valid_share"], 26 / 28)
        self.assertAlmostEqual(r.loc["main", "first_pass_valid_share"], 27 / 42)
        # Repaired share is over decisions; repair success is over attempts.
        self.assertAlmostEqual(r.loc["main_diagnostic", "repair_attempt_share"], 2 / 28)
        self.assertAlmostEqual(r.loc["main_diagnostic", "successful_repair_share"], 0 / 28)
        self.assertAlmostEqual(r.loc["main", "successful_repair_share"], 12 / 42)
        self.assertAlmostEqual(r.loc["main", "repair_success_rate"], 12 / 15)
        self.assertNotIn("main_diagnostic", reliability(llm).set_index("setting").index)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class TestRestartSummary(unittest.TestCase):
    def proposal(self, identity, reason=None, failed=(), held=0.0):
        return {"interrupted_identity": identity, "interrupted_index": 0, "held_credits": held,
                "failed_attempt": {"uncertainty_reason": reason} if reason else None,
                "accounting": {"failed_requests": list(failed)}}

    def test_events_distinct_branches_and_causes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {
                "production": [self.proposal("A", "api_APITimeoutError_http_unknown", held=0.007),
                               self.proposal("A", "api_InternalServerError_http_503", held=0.007),
                               self.proposal("B", "process_interrupted_gateway_outcome_unknown", held=0.007)],
                "history": [self.proposal("A", None, failed=[
                    {"failure_category": "api_APIConnectionError_http_unknown", "started_at_utc": "2026-01-02"},
                    {"failure_category": "api_APITimeoutError_http_unknown", "started_at_utc": "2026-01-01"}],
                    held=0.007)],
                "elasticity": [self.proposal("C", "api_RateLimitError_http_429", held=0.007),
                               self.proposal("D")],
            }
            for folder, proposals in plan.items():
                for i, p in enumerate(proposals, 1):
                    d = root / "results/report2" / folder / f"recovery{i}"
                    write_json(d / "recovery_proposal.json", p)
                    write_json(d / "recovery_receipt.json", {"status": "production_recovery_activated",
                                                             "interrupted_identity": p["interrupted_identity"],
                                                             "approved_held_credits": p["held_credits"]})
            (root / "results/report2/production/recovery_notes").mkdir()  # not a numbered restart
            events = restart_events(root)
            s = restart_summary(events).set_index("cohort")
            self.assertEqual(len(events), 6)
            self.assertEqual(s.loc["main", "restart_events"], 3)
            self.assertEqual(s.loc["main", "distinct_branches"], 2)
            # The same identity in another cohort is a different branch.
            self.assertEqual(s.loc["total", "distinct_branches"], 5)
            self.assertEqual(s.loc["total", "cause_timeout"], 1)
            self.assertEqual(s.loc["total", "cause_server_error"], 1)
            self.assertEqual(s.loc["total", "cause_process_interrupted"], 1)
            self.assertEqual(s.loc["history", "cause_connection_error"], 1)  # latest failed request when no attempt
            self.assertEqual(s.loc["total", "cause_rate_limit"], 1)
            self.assertEqual(s.loc["total", "cause_no_failed_request"], 1)
            self.assertEqual(s.loc["total", "cause_other"], 0)
            self.assertEqual(s.loc["total", "restarts_with_reserve"], 5)
            self.assertEqual(events.loc[events["cause_group"] == "server_error", "http_status"].tolist(), [503])


class TestEvidenceHashes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.batch = Path(self.tmp.name)
        run = self.batch / "branches/abc"
        run.mkdir(parents=True)
        for name in ("observations.jsonl", "actions.jsonl", "daily_results.csv", "summary.json", "prefix_audit.json"):
            (run / name).write_text(f"{name} content\n", encoding="utf-8")
        write_json(run / "run_manifest.json", {"status": "validated_complete"})
        requests = self.batch / "requests/abc"
        write_json(requests / "attempts/1/response.json", {"ok": True})
        (requests / "api_attempts.jsonl").write_text("{}\n", encoding="utf-8")
        self.request_hashes = {p.relative_to(requests).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in requests.rglob("*") if p.is_file()}
        self.claim = self.batch / "claims/abc.json"
        write_json(self.claim, {"status": "validated_complete", "evidence_sha256": evidence_hashes(run),
                                "request_artifact_sha256": self.request_hashes})

    def tearDown(self):
        self.tmp.cleanup()

    def test_matching_evidence_passes(self):
        verify_claim_evidence(self.batch, self.claim, llm=True)

    def test_changed_branch_evidence_fails(self):
        (self.batch / "branches/abc/daily_results.csv").write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            verify_claim_evidence(self.batch, self.claim, llm=True)

    def test_changed_or_extra_request_artifact_fails(self):
        (self.batch / "requests/abc/attempts/1/response.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Request artifacts changed"):
            verify_claim_evidence(self.batch, self.claim, llm=True)

    def test_extra_request_file_fails(self):
        (self.batch / "requests/abc/extra.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Request artifacts changed"):
            verify_claim_evidence(self.batch, self.claim, llm=True)

    def test_llm_claim_without_request_hashes_fails(self):
        claim = json.loads(self.claim.read_text(encoding="utf-8"))
        del claim["request_artifact_sha256"]
        write_json(self.claim, claim)
        with self.assertRaisesRegex(ValueError, "request_artifact_sha256"):
            verify_claim_evidence(self.batch, self.claim, llm=True)


class TestEvidenceCache(unittest.TestCase):
    def test_fingerprint_tracks_claim_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claim = root / "results/report2/production/claims/x.json"
            write_json(claim, {"status": "validated_complete"})
            before = evidence_fingerprint(root)
            self.assertEqual(before["claim_files"], 1)
            self.assertEqual(before, evidence_fingerprint(root))
            write_json(claim, {"status": "validated_complete", "evidence_sha256": {}})
            self.assertNotEqual(before["fingerprint"], evidence_fingerprint(root)["fingerprint"])

    def test_stale_or_tampered_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "evidence"
            episodes, daily = pd.DataFrame({"a": [1]}), pd.DataFrame({"b": [2]})
            current = {"fingerprint": "f1", "claim_files": 1, "analysis_source_sha256": "s"}
            self.assertIsNone(runner.load_cache(cache, current))  # no cache yet
            runner.save_cache(cache, current, episodes, daily, {"llm_branches": 1})
            loaded = runner.load_cache(cache, current)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded[2], {"llm_branches": 1})
            self.assertIsNone(runner.load_cache(cache, {**current, "fingerprint": "f2"}))
            pd.DataFrame({"a": [9]}).to_pickle(cache.with_suffix(".episodes.pkl"))
            self.assertIsNone(runner.load_cache(cache, current))
            runner.save_cache(cache, current, episodes, daily, {})
            cache.with_suffix(".fingerprint.json").unlink()
            self.assertIsNone(runner.load_cache(cache, current))


class TestManuscriptClaimMap(unittest.TestCase):
    def values(self):
        v = build_report2.Values()
        v.add("a.b", "$-$1{,}234", "tables/x.csv", "row s=1; column mean")
        return v

    def test_every_used_key_and_table_is_mapped(self):
        tex = ("% header mentions \\val{ignored.key}\nGap \\val{a.b} units. 50\\% \\val{a.b}\n"
               "\\input{generated/tab_main.tex}\n")
        claims = build_report2.manuscript_claim_map(self.values(), tex, {"tab_main": "A & $-$2 \\\\\n\\midrule\n"})
        self.assertEqual(claims["key"].tolist(), ["a.b", "tab_main.row1"])
        self.assertEqual(claims.loc[0, "value"], "-1,234")
        self.assertEqual(claims.loc[0, "source"], "tables/x.csv")
        self.assertEqual(claims.loc[1, "value"], "A | -2")

    def test_unmapped_key_fails(self):
        with self.assertRaisesRegex(ValueError, "undefined=\\['c.d'\\]"):
            build_report2.manuscript_claim_map(self.values(), "\\val{a.b} \\val{c.d}", {})
        v = self.values()
        v["e.f"] = "1"  # value without provenance
        with self.assertRaisesRegex(ValueError, "unmapped=\\['e.f'\\]"):
            build_report2.manuscript_claim_map(v, "\\val{e.f}", {})

    def test_untraced_table_fails(self):
        with self.assertRaisesRegex(ValueError, "tables=\\['tab_unknown'\\]"):
            build_report2.manuscript_claim_map(self.values(), "\\input{generated/tab_unknown.tex}", {})


if __name__ == "__main__":
    unittest.main()
