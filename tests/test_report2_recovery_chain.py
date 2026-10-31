"""Successive manual recoveries retain every archive and cumulative charge."""
import json
import shutil
import unittest
from unittest.mock import Mock, patch

import test_report2_recovery as fixtures
from src.benchmarks.budget import BudgetLedger
from src.experiments.kaggle_protocol import write
from src.research.report2 import ROOT, canonical_hash, read_json
from src.research.report2_development import identity
from src.research.report2_interruption import file_hashes, reconcile_requests
from src.research.report2_pilot import MODEL, fingerprint
from src.research import report2_recovery as base
from src.research import report2_recovery_chain as chain


class RepeatedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.RecoveryTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        f = self.f
        patch("src.research.report2_recovery_chain.development_plan", return_value=f.plan).start()

        def claim_check(batch, path):
            if read_json(path)["status"] != "validated_complete":
                raise ValueError("Incomplete claim blocks model execution")

        patch("src.research.report2_recovery_chain.check_prior_claim", side_effect=claim_check).start()
        for name in chain.SOURCES:
            path = f.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, path)
        self.first_proposal = f.activated()
        write(f.folder / "proposal.json", self.first_proposal)
        for case in ("dev_1", "dev_2"):
            write(f.batch / "cases" / case / "warmup/prefix.json", {"fixture": True})
        for index in (10, 11, 12):
            f.driver(index, f.folder / "approved_authorization.json", f.folder / "approved_budget.json")
        self.second = f.root / "results/report2/recovery_second"
        self.budget, self.auth = read_json(f.folder / "approved_budget.json"), read_json(f.folder / "approved_authorization.json")
        self.key = identity(f.plan, 13)
        ledger = BudgetLedger(self.budget, f.path, run_id=self.key, scope="kaggle")
        ledger.reserve("second_timeout", MODEL, 100, 10)
        ledger.settle("second_timeout", uncertain_reason=base.TIMEOUT)
        f.write_requests(self.key, [r for r in base.read_ledger(f.path)[2] if r["id"] == "second_timeout"])
        write(f.batch / "branches" / self.key / "run_manifest.json", {"status": "incomplete"})
        write(f.batch / "claims" / f"{self.key}.json", {"status": "claimed_before_client_creation",
              "episode": f.plan["episodes"][13], "budget_sha256": fingerprint(self.budget),
              "authorization_sha256": canonical_hash(self.auth)})

        def replay(index, plan, batch, rows, excluded_ids, output):
            key = identity(plan, index)
            summary = read_json(batch / "branches" / key / "summary.json")
            paid = [r for r in rows if r["run_id"] == key and r["id"] not in excluded_ids]
            return {"branch_index": index, **summary, **reconcile_requests(batch / "requests" / key, paid, key, complete=True)}

        patch("src.research.report2_recovery_chain.replay_completed", side_effect=replay).start()
        patch("src.research.report2_recovery_chain.replay_partial", return_value={"saved_decisions_verified": 0,
              "interrupted_decision_date": "2023-05-19", "included_in_completed_outcomes": False}).start()

    def prepared(self):
        return chain.prepare(self.f.folder, self.second, self.f.snapshot, self.f.root)

    def activated(self):
        p = self.prepared()
        chain.activate(p, self.second, approve_held_credits=str(p["held_credits"]), root=self.f.root)
        return p

    def test_second_preparation_audits_all_completed_and_archived_requests_readonly(self):
        before, originals = base.read_ledger(self.f.path), file_hashes(self.f.batch)
        p = self.prepared()
        self.assertEqual(p["restart_index"], 13)
        self.assertEqual(p["recovery_branch_indices"], list(range(13, 24)))
        self.assertEqual(p["archive_attempt_ids"], ["second_timeout"])
        self.assertEqual(len(p["previous_archives"]), 1)
        self.assertEqual(base.read_ledger(self.f.path), before)
        self.assertEqual(file_hashes(self.f.batch), originals)
        self.assertEqual(p["additional_credit_limit"], 0)

    def test_second_activation_preserves_both_unknown_rows_and_prior_archive(self):
        before = base.read_ledger(self.f.path)
        original_archive = file_hashes(self.f.folder / "archive")
        p = self.activated()
        after = base.read_ledger(self.f.path)
        self.assertEqual(after[2], before[2])
        self.assertEqual(after[1]["exposure_nanos"], before[1]["exposure_nanos"])
        self.assertEqual(after[1]["blocking_uncertain_attempts"], 0)
        self.assertEqual(len(after[3]), len(before[3]) + 1)
        self.assertEqual(file_hashes(self.f.folder / "archive"), original_archive)
        self.assertEqual(chain.active_state(p, self.second, self.f.root)[0], list(range(13)))
        self.assertEqual(read_json(self.second / "approved_budget.json")["cap_usd"], 20)

    def test_edited_prior_archive_or_approval_blocks_launch(self):
        p = self.activated()
        path = self.f.folder / "approved_authorization.json"
        path.write_text("{}")
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "previous recovery approval or archive changed"):
            chain.run_pending(p, self.second, runner, self.f.root, manual=True)
        runner.assert_not_called()

    def test_wrong_hold_amount_leaves_real_transitions_untouched(self):
        p = self.prepared()
        before = base.read_ledger(self.f.path)
        with self.assertRaisesRegex(ValueError, "entire reviewed"):
            chain.activate(p, self.second, approve_held_credits="0", root=self.f.root)
        self.assertEqual(base.read_ledger(self.f.path), before)

    def test_final_audit_accounts_for_both_archives_and_skips_completed(self):
        p = self.activated()
        calls = []

        def driver(index, auth, budget):
            calls.append(index)
            code = self.f.driver(index, auth, budget)
            baseline_ids = {r["id"] for r in p["baseline_attempts"]}
            key = identity(self.f.plan, index)
            self.f.write_requests(key, [r for r in base.read_ledger(self.f.path)[2]
                                       if r["run_id"] == key and r["id"] not in baseline_ids])
            return code

        result, code = chain.run_pending(p, self.second, driver, self.f.root, manual=True)
        self.assertEqual((code, result["completed_branches"]), (0, 24))
        self.assertEqual(calls, list(range(13, 24)))
        result = chain.audit(p, self.second, self.f.root)
        self.assertEqual(result["totals"]["completed_decisions"], 336)
        self.assertEqual(result["physical_pilot_attempts"], 339)
        self.assertEqual(len(result["archived_interruptions"]), 2)
        self.assertEqual(sum(a["model_attempts"] for a in result["archived_interruptions"]), 3)
        runner = Mock()
        repeated, code = chain.run_pending(p, self.second, runner, self.f.root, manual=True)
        self.assertEqual((code, repeated["new_branches_launched"]), (0, 0))
        runner.assert_not_called()

    def test_new_interruption_stops_again_without_retry(self):
        p = self.activated()

        def driver(index, auth, budget):
            ledger = BudgetLedger(read_json(budget), self.f.path, run_id=identity(self.f.plan, index), scope="kaggle")
            ledger.reserve("third_timeout", MODEL, 100, 10)
            ledger.settle("third_timeout", uncertain_reason=base.TIMEOUT)
            return 1

        result, code = chain.run_pending(p, self.second, driver, self.f.root, manual=True)
        self.assertEqual((code, result["failed_branch_index"]), (1, 13))
        runner = Mock()
        with self.assertRaisesRegex(ValueError, "new interrupted/unknown"):
            chain.run_pending(p, self.second, runner, self.f.root, manual=True)
        runner.assert_not_called()

        # The same branch may fail again: a third handoff must retain both older archives.
        self.f.write_requests(self.key, [r for r in base.read_ledger(self.f.path)[2] if r["id"] == "third_timeout"])
        budget = read_json(self.second / "approved_budget.json")
        auth = read_json(self.second / "approved_authorization.json")
        write(self.f.batch / "branches" / self.key / "run_manifest.json", {"status": "incomplete"})
        write(self.f.batch / "claims" / f"{self.key}.json", {"status": "claimed_before_client_creation",
              "episode": self.f.plan["episodes"][13], "budget_sha256": fingerprint(budget),
              "authorization_sha256": canonical_hash(auth)})
        third = chain.prepare(self.second, self.f.root / "results/report2/third", self.f.snapshot, self.f.root)
        self.assertEqual(len(third["previous_archives"]), 2)
        self.assertEqual(third["archive_attempt_ids"], ["third_timeout"])


if __name__ == "__main__":
    unittest.main()
