"""Offline incident review without editing claims, responses, or the paid ledger.

This reviews a stopped development cohort. It never authorizes a retry or treats
an incomplete trajectory as a completed research result.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from src.research.report2 import ROOT, canonical_hash, read_json
from src.research.report2_development import identity, validate_update, verify
from src.research.report2_pilot import MODEL, SCALE, connect_readonly, fingerprint, ledger_state


def file_hashes(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(directory).rglob("*") if p.is_file()}


def json_lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def reconcile_requests(directory, rows, run_id, *, complete):
    """Join unique physical attempt IDs, including unknown failed charges."""
    events = json_lines(Path(directory) / "api_attempts.jsonl")
    starts = [e for e in events if e["event"] == "started"]
    finishes = [e for e in events if e["event"] == "finished"]
    by_id = {r["id"]: r for r in rows}
    if (len(by_id) != len(rows) or len(starts) != len(rows) or len(finishes) != len(rows)
            or {e["attempt_id"] for e in starts} != set(by_id)
            or {e["attempt_id"] for e in finishes} != set(by_id)):
        raise ValueError("Request events and unique cumulative ledger attempts differ.")
    started = {e["attempt_id"]: e for e in starts}
    for event in finishes:
        row = by_id[event["attempt_id"]]
        begin = started[event["attempt_id"]]
        if (row["run_id"] != run_id or row["model"] != MODEL or row["scope"] != "kaggle"
                or any(e.get("run_id") != run_id or e.get("requested_model") != MODEL
                       or e.get("purpose") != "pilot" for e in (begin, event))
                or event["request_sha256"] != begin["request_sha256"]
                or event["logical_request_id"] != begin["logical_request_id"]
                or not math.isclose(begin["reserved_cost_usd"], row["reserved_nanos"] / SCALE,
                                    abs_tol=1e-12, rel_tol=0)):
            raise ValueError("Request identity or conservative reservation differs from the ledger.")
        if event["status"] == "completed":
            if (row["status"] != "settled" or row["actual_nanos"] is None
                    or event.get("cost_usd") is None
                    or not math.isclose(event["cost_usd"], row["actual_nanos"] / SCALE,
                                        abs_tol=1e-12, rel_tol=0)):
                raise ValueError("Completed request charge differs from the ledger.")
        elif (complete or event["status"] != "failed" or row["status"] != "uncertain"
              or row["actual_nanos"] is not None or event.get("cost_usd") is not None
              or event.get("usage") is not None
              or event.get("failure_category") != row["uncertainty_reason"]):
            raise ValueError("Failed request uncertainty was lost or presented as complete.")
    return {
        "model_attempts": len(rows),
        "known_credits": sum(r["actual_nanos"] or 0 for r in rows) / SCALE,
        "unknown_charge_reserved_credits": sum(r["reserved_nanos"] for r in rows if r["status"] == "uncertain") / SCALE,
        "serial_api_seconds": sum(e["latency_seconds"] for e in finishes),
        "failed_requests": [{k: e.get(k) for k in ("attempt_id", "logical_request_id", "failure_category",
                            "latency_seconds", "reserved_cost_usd", "started_at_utc", "finished_at_utc")}
                            for e in finishes if e["status"] == "failed"],
    }


def replay_partial(prepared, prefix, run, replay):
    """Verify saved decisions plus the observation whose request was interrupted."""
    from src.experiments.report2 import (advance, branch_descriptor, restore_prefix,
                                         treat_history, validate_decision)
    manifest = read_json(Path(run) / "run_manifest.json")
    expected = branch_descriptor(prepared, prefix, **{k: manifest[k] for k in
                                 ("scenario", "history", "policy", "realization")})
    if (manifest["status"] != "incomplete" or manifest["policy"] != "llm_with_fallback"
            or manifest["branch_id"] != canonical_hash(expected)
            or any(manifest.get(k) != v for k, v in expected.items())):
        raise ValueError("Interrupted branch identity or incomplete status changed.")
    observations = json_lines(Path(run) / "observations.jsonl")
    action_path = Path(run) / "actions.jsonl"
    actions = json_lines(action_path) if action_path.exists() else []
    if not 0 <= len(actions) < 14 or len(observations) != len(actions) + 1:
        raise ValueError("Expected completed actions followed by one interrupted observation.")
    env = restore_prefix(prepared, prefix, replay, manifest["scenario"])
    frozen = {sku: copy.deepcopy(rows[-14:]) for sku, rows in env._history.items()}
    for index, saved in enumerate(observations):
        current = treat_history(env.observe(), manifest["history"], frozen)
        if current != saved["observation"] or canonical_hash(current) != saved["sha256"]:
            raise ValueError("Partial observation differs from independent reconstruction.")
        if index < len(actions):
            action = actions[index]
            if action["date"] != current["date"]:
                raise ValueError("Partial decision date differs from reconstruction.")
            validate_decision(action, current, manifest["policy"])
            advance(env, current, action["actions"])
    return {"saved_decisions_verified": len(actions), "scheduled_decisions": 14,
            "last_saved_decision_date": actions[-1]["date"] if actions else None,
            "interrupted_decision_date": observations[-1]["observation"]["date"],
            "included_in_completed_outcomes": False}


def review(handoff, output, root=ROOT):
    from scripts.run_report2_pilot import check_prior_claim, validate_authorization
    from src.experiments.report2 import development_plan, validate_branch
    root, handoff, output = Path(root).resolve(), Path(handoff).resolve(), Path(output).resolve()
    local = root / "results/report2"
    batch = local / "manual_development"
    if (not handoff.is_relative_to(local) or not output.is_relative_to(local)
            or output.is_relative_to(batch) or output == local or output.exists()):
        raise ValueError("Use a fresh local review directory outside the canonical batch.")
    proposal = read_json(handoff / "proposal.json")
    verify(proposal, read_json(handoff / "gateway_snapshot.json"), root, before_activation=False, fresh=False)
    budget, auth = read_json(handoff / "approved_budget.json"), read_json(handoff / "approved_authorization.json")
    receipt = read_json(handoff / "activation_receipt.json")
    plan = development_plan(root)
    validate_update(proposal["old_allowance"], budget, proposal["before"], proposal["broader_envelope"], proposal["incremental_credit_limit"])
    validate_authorization(auth, budget, plan, 1)
    if receipt["proposal_sha256"] != proposal["proposal_sha256"] or receipt["budget_sha256"] != fingerprint(budget):
        raise ValueError("Continuation activation receipt differs from its allowance.")
    ledger = root / proposal["ledger_relative_path"]
    with closing(connect_readonly(ledger)) as db:
        state = ledger_state(db)
        rows = db.execute("SELECT * FROM attempts ORDER BY id").fetchall()
        fields = [r[1] for r in db.execute("PRAGMA table_info(attempts)")]
        active = db.execute("SELECT fingerprint FROM config").fetchone()[0]
    remaining = {identity(plan, i) for i in range(1, 24)}
    if (active != fingerprint(budget)
            or canonical_hash({"rows": [r for r in rows if r[1] not in remaining]}) != proposal["before"]["attempts_sha256"]
            or state["holds_sha256"] != proposal["before"]["holds_sha256"]
            or state["pending_attempts"] or state["blocking_uncertain_attempts"] != 1):
        raise ValueError("Expected unchanged historical rows/holds and one unknown failed charge.")
    delta = state["exposure_nanos"] - proposal["before"]["exposure_nanos"]
    if not 0 <= delta <= round(proposal["incremental_credit_limit"] * SCALE):
        raise ValueError("Continuation exposure exceeds its approval.")
    before = file_hashes(batch)
    claims = {p.stem: read_json(p) for p in (batch / "claims").glob("*.json")}
    known = {identity(plan, i): i for i in range(24)}
    failed = [known[k] for k, c in claims.items() if k in known and c["status"] != "validated_complete"]
    if not set(claims) <= set(known) or len(failed) != 1:
        raise ValueError("Expected exactly one interrupted branch in the frozen cohort.")
    failed_index = failed[0]
    if set(claims) != {identity(plan, i) for i in range(failed_index + 1)}:
        raise ValueError("Completed branches must precede the interrupted branch without gaps.")
    if any(r[1] in remaining and r[1] not in claims for r in rows):
        raise ValueError("Paid attempts exist without their canonical branch claim.")
    for kind in ("branches", "requests"):
        if {p.name for p in (batch / kind).iterdir() if p.is_dir()} != set(claims):
            raise ValueError("Canonical artifacts and claims differ.")
    first = root / proposal["first_directory"]
    first_budget, first_auth = read_json(first / "approved_budget.json"), read_json(first / "approved_authorization.json")
    completed, interrupted = [], None
    output.mkdir(parents=True, exist_ok=False)
    for index in range(failed_index + 1):
        episode, key = plan["episodes"][index], identity(plan, index)
        claim = claims[key]
        allowance, authorization = (first_budget, first_auth) if index == 0 else (budget, auth)
        if (claim["episode"] != episode or claim["budget_sha256"] != fingerprint(allowance)
                or claim["authorization_sha256"] != canonical_hash(authorization)):
            raise ValueError("Branch differs from its historical manual approval.")
        run, group = batch / "branches" / key, batch / "cases" / episode["case_id"]
        manifest = read_json(run / "run_manifest.json")
        if any(manifest[k] != episode[k] for k in ("scenario", "history", "realization")):
            raise ValueError("Branch treatment differs from its frozen plan entry.")
        prefix, prepared = read_json(group / "warmup/prefix.json"), group / "prepared/inputs"
        paid = [dict(zip(fields, r)) for r in rows if r[1] == key]
        accounting = reconcile_requests(batch / "requests" / key, paid, key, complete=index != failed_index)
        if index != failed_index:
            check_prior_claim(batch, batch / "claims" / f"{key}.json")
            # The frozen validator rewrites its input; validate a copy to keep evidence untouched.
            saved_copy = output / "validation_copies" / key
            shutil.copytree(run, saved_copy)
            validate_branch(prepared, prefix, saved_copy, output / "replays" / key)
            summary = read_json(run / "summary.json")
            if summary["model_calls_made"] != len(paid) or not 14 <= len(paid) <= 28:
                raise ValueError("Completed branch request denominator differs from its summary.")
            completed.append({"branch_index": index, **episode, **accounting,
                              **{k: summary[k] for k in ("completed_decisions", "first_pass_valid", "repair_attempts",
                                 "successful_repairs", "fallback_days")}})
        else:
            partial = replay_partial(prepared, prefix, run, output / "replays" / key)
            if (len(accounting["failed_requests"]) != 1
                    or not accounting["failed_requests"][0]["logical_request_id"].startswith(
                        "day:" + partial["interrupted_decision_date"] + ":repair:")):
                raise ValueError("The failed request differs from the interrupted decision.")
            interrupted = {"branch_index": index, **episode, **accounting, **partial}
    if file_hashes(batch) != before:
        raise ValueError("Canonical evidence changed during offline review.")
    with closing(connect_readonly(ledger)) as db:
        if ledger_state(db) != state or db.execute("SELECT fingerprint FROM config").fetchone()[0] != active:
            raise ValueError("Cumulative ledger changed during offline review.")
    totals = {k: sum(r[k] for r in completed) for k in ("completed_decisions", "model_attempts", "known_credits",
              "first_pass_valid", "repair_attempts", "successful_repairs", "fallback_days", "serial_api_seconds")}
    pilot_known = round((totals["known_credits"] + interrupted["known_credits"]) * SCALE)
    first_known = round(completed[0]["known_credits"] * SCALE)
    if pilot_known - first_known + round(interrupted["unknown_charge_reserved_credits"] * SCALE) != delta:
        raise ValueError("Incident cost and cumulative continuation exposure differ.")
    sources = ("src/research/report2_interruption.py", "scripts/review_report2_interruption.py",
               "tests/test_report2_interruption.py")
    result = {"status": "interruption_reviewed_stage3_incomplete", "audit_model_calls_made": 0,
              "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
              "review_source_sha256": {name: hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                                       for name in sources},
              "canonical_evidence_unchanged": True, "ledger_unchanged": True,
              "completed_branches": len(completed), "planned_branches": 24, "completed_totals": totals,
              "interrupted": interrupted, "not_started_branch_indices": list(range(failed_index + 1, 24)),
              "project_exposure_credits": state["exposure_nanos"] / SCALE,
              "project_remaining_after_reservations_credits": budget["cap_usd"] - state["exposure_nanos"] / SCALE,
              "overall_credit_cap": budget["cap_usd"], "production_evaluation_started": False,
              "budget_state": state, "canonical_artifact_sha256": before, "completed": completed,
              "next_gate": "Review a separate transport-failure recovery handoff before any user manual model command",
              "recovery_plan": [
                  "Retain the failed request's entire reservation; never infer zero charge or fabricate a response.",
                  "Back up the ledger and bind the interrupted claim, requests and partial trajectory to an immutable archive.",
                  "Prepare an explicit reviewed restart from the same frozen warm-up; keep branches already completed.",
                  "Account for archived attempts as well as replacement requests; keep existing credit and attempt limits.",
                  "Require a new user manual recovery command; stop again on any interrupted branch.",
                  "Audit all 24 completed branches plus archived costs before reviewing Stage 4."],
              "qualification": "Descriptive development evidence only. Partial decisions are excluded from complete-branch outcomes; all attempts and reserved charges remain operational evidence."}
    (output / "interruption_review.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
