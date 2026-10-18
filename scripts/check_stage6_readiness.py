"""Read-only Stage 6 plan/source checks; --private audits saved evidence without model calls."""
import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import sqlite3
import sys
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check_public_stage2 import check
from src.experiments.kaggle_protocol import (read, primary_matrix, episode_evidence_digest,
    require_fallback_reviews)
from src.research.design import canonical_hash

PUBLIC = ROOT / "docs/results/stage6"


def text_hash(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def private_inventory():
    study = read(ROOT / "configs/study.json")
    matrix = primary_matrix(study)
    identities = {e["episode_id"] for e in matrix["episodes"]}
    root = ROOT / "results/runs/kaggle_retailbench"
    assert not (root / ".kaggle_execution.lock").exists()
    require_fallback_reviews(root)
    allowance_path = ROOT / ".cache/approvals/stage5_allowance.approved.json"
    allowance = read(allowance_path)
    ledger = ROOT / "results/budgets" / (allowance["budget_id"] + ".sqlite")
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (allowance_path, ledger)]
    with closing(sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("SELECT fingerprint FROM config").fetchone()[0] == hashlib.sha256(json.dumps(allowance, sort_keys=True).encode()).hexdigest()
        attempts, exposure = db.execute("SELECT COUNT(*),SUM(COALESCE(actual_nanos,reserved_nanos)) FROM attempts").fetchone()
        assert db.execute("SELECT COUNT(*) FROM attempts WHERE status='pending' OR (status='uncertain' AND id NOT IN (SELECT attempt_id FROM bounded_holds))").fetchone()[0] == 0
        settled = {r[0]: r[1:] for r in db.execute("SELECT id,status,actual_nanos,run_id FROM attempts")}
    saved = read(ROOT / "docs/results/stage5/status.json")["budget_snapshot"]
    assert attempts == saved["total_project_attempts"] and exposure == round(saved["inclusive_project_exposure_credits"] * 1e9)
    counts = dict(episodes=0, action_records=0, observation_records=0, primary_llm_episodes=0,
        request_starts=0, known_usage_records=0, latency_records=0, primary_quality_reviews=0)
    seen = set()
    expected_days = [(date.fromisoformat(study["kaggle"]["windows"]["primary_evaluation"]["start"]) + timedelta(days=i)).isoformat() for i in range(21)]
    for manifest_path in root.glob("*/run_manifest.json"):
        manifest = read(manifest_path)
        if manifest.get("episode_id") not in identities:
            continue
        assert manifest["episode_id"] not in seen and manifest["status"] == "validated_complete"
        seen.add(manifest["episode_id"])
        run = manifest_path.parent
        validation = read(run / "validation.json")
        assert validation["status"] == "validated_complete" and all(validation["checks"].values())
        assert validation["evidence_sha256"] == episode_evidence_digest(run)
        lines = lambda name: [json.loads(s) for s in (run / name).read_text(encoding="utf-8").splitlines()]
        actions, observations = lines("actions.jsonl"), lines("observations.jsonl")
        assert [r["date"] for r in actions] == [r["date"] for r in observations] == expected_days
        for action, record in zip(actions, observations):
            observation = record["observation"]
            assert {"funds", "lead_days", "products", "elasticity_assumption"} <= set(observation)
            assert set(action["actions"]) == set(observation["products"])
            for sku, value in action["actions"].items():
                assert type(value["order_quantity"]) is int and value["order_quantity"] >= 0
                assert value["price_multiplier"] in (.9, 1., 1.1)
                product = observation["products"][sku]
                assert {"inventory", "on_order", "reference_price", "unit_cost", "history"} <= set(product)
                assert product["reference_price"] > 0 and product["unit_cost"] > 0
        counts["episodes"] += 1
        counts["action_records"] += len(actions)
        counts["observation_records"] += len(observations)
        if manifest["policy"] != "llm_with_fallback":
            continue
        counts["primary_llm_episodes"] += 1
        assert read(run / "quality_review.json")["status"] == "reviewed"
        counts["primary_quality_reviews"] += 1
        events = lines("api_attempts.jsonl")
        starts = [r for r in events if r["event"] == "started"]
        finishes = [r for r in events if r["event"] == "finished"]
        assert len(starts) == len(finishes) and {r["attempt_id"] for r in starts} == {r["attempt_id"] for r in finishes}
        counts["request_starts"] += len(starts)
        for event in finishes:
            assert event["status"] == "completed" and event["cost_usd"] is not None
            assert all(type(event["usage"][k]) is int and event["usage"][k] >= 0 for k in ("prompt_tokens", "completion_tokens"))
            assert math.isfinite(event["latency_seconds"]) and event["latency_seconds"] >= 0
            assert settled[event["attempt_id"]] == ("settled", int(Decimal(str(event["cost_usd"])) * Decimal(10**9)), run.name)
            counts["known_usage_records"] += 1
            counts["latency_records"] += 1
    assert seen == identities
    assert counts == dict(episodes=36, action_records=756, observation_records=756, primary_llm_episodes=12,
        request_starts=396, known_usage_records=396, latency_records=396, primary_quality_reviews=12)
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in (allowance_path, ledger)]
    return {**counts, "ledger_and_allowance_unchanged": True, "no_model_calls_or_simulation_runs": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", action="store_true", help="Additionally audit ignored local logs and the existing ledger read-only.")
    args = parser.parse_args()
    files = {"preparation.json", "source_snapshot.json"}
    if (PUBLIC / "status.json").exists():
        # The preparation checkpoint remains historical. Once execution artifacts
        # exist, validate their own strict allowlist and hashes with the execution checker.
        subprocess.run([sys.executable, str(ROOT / "scripts/check_public_stage6.py")], check=True)
    else:
        assert {p.name for p in PUBLIC.iterdir() if p.is_file()} == files
    paths = [*(PUBLIC / name for name in files), ROOT / "configs/analysis/stage6.template.json"]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b[0-9a-f]{32}\b|\b20\d{6}T\d{12,}Z\b", text), path.name
        check(json.loads(text))
    prep, snapshot = read(PUBLIC / "preparation.json"), read(PUBLIC / "source_snapshot.json")
    plan = read(ROOT / "configs/analysis/stage6.template.json")
    study = read(ROOT / "configs/study.json")
    assert prep["status"] == "prepared_not_executed" and prep["stage"] == 6
    assert prep["new_model_completion_calls"] == prep["new_simulation_episodes"] == 0
    assert prep["analysis_executed"] is False and plan["approved"] is False
    assert plan["paid_calls_authorized"] is False and plan["analysis_executed"] is False
    assert snapshot["hash_rule"] == "SHA-256 UTF-8 text with CRLF normalized to LF"
    assert snapshot["source_commit"] == "0af4710"
    expected = {"configs/study.json", "docs/results/study_design_manifest.json"}
    expected |= {p.relative_to(ROOT).as_posix() for stage in (2, 3, 5) for p in (ROOT / f"docs/results/stage{stage}").iterdir() if p.is_file()}
    assert set(snapshot["files"]) == expected
    for relative, digest in snapshot["files"].items():
        path = (ROOT / relative).resolve()
        assert path.is_relative_to(ROOT) and text_hash(path) == digest, relative
    assert prep["source_snapshot_sha256"] == plan["source_snapshot_sha256"] == canonical_hash(snapshot)
    assert prep["analysis_plan_sha256"] == canonical_hash(plan)
    assert plan["study_sha256"] == canonical_hash(study)
    assert plan["primary_window"] == study["kaggle"]["windows"]["primary_evaluation"]
    assert plan["recovery"] == study["kaggle"]["recovery"]
    assert plan["relative_gain"] == study["kaggle"]["relative_gain"]
    assert plan["control_adjusted_contrast"] == study["kaggle"]["control_adjusted_contrast"]
    assert plan["inference"] == study["inference"]
    assert plan["phase_days"] == {"pre_shock": [1, 7], "shock": [8, 14], "post_shock": [15, 21]}
    assert plan["baseline_elasticity_sensitivity"]["elasticities"] == [.75, 1.5, 2.25]
    assert plan["baseline_elasticity_sensitivity"]["new_baseline_episodes"] == 48
    assert plan["baseline_elasticity_sensitivity"]["executed"] is False
    assert plan["paid_extensions"]["enabled"] is False
    counts = plan["expected_output_rows"]
    assert counts == dict(episode_metrics=36, paired_shock_contrasts=18, control_comparisons=6,
        policy_shock_minus_control=27, per_scenario_summaries=6, phase_summaries=108,
        action_traces=756, behavioral_response=27, recovery=27, llm_episode_reliability_costs=12,
        baseline_elasticity_summary=72, native_task_coverage=19)
    current = read(ROOT / "docs/results/stage5/status.json")
    assert current["exit_gate_passed"] is True and current["missing_matrix_indices"] == []
    assert prep["budget_snapshot"] == current["budget_snapshot"]
    native = read(ROOT / "docs/results/stage3/status.json")
    assert (native["validated_tasks"], native["failed_tasks"], native["deferred_tasks"]) == (14, 1, 4)
    assert prep["private_source_preflight"] == dict(episodes=36, action_records=756, observation_records=756,
        primary_llm_episodes=12, request_starts=396, known_usage_records=396, latency_records=396,
        primary_quality_reviews=12, ledger_and_allowance_unchanged=True, no_model_calls_or_simulation_runs=True)
    if args.private:
        assert private_inventory() == prep["private_source_preflight"]
    print(f"Historical Stage 6 preparation passed: {len(expected)} pinned inputs and frozen analysis rules preserved.")


if __name__ == "__main__":
    main()
