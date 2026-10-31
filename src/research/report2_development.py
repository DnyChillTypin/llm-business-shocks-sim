"""Continue the development pilot while retaining its first audited branch.

Preparation, checking and auditing are offline. Only an explicit manual driver
may launch the existing single-branch model command in fresh subprocesses.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.research.report2 import ROOT, canonical_hash, read_json
from src.research.report2_runtime import verify_implementation
from src.research.report2_pilot import (MODEL, SCALE, audit_first_branch, connect_readonly,
    current_allowance, fingerprint, ledger_state, token_cost, validate_snapshot)

SOURCES = ("src/research/report2_development.py", "scripts/continue_report2_development.py",
           "tests/test_report2_development.py")


def code_hashes(root=ROOT):
    return {name: hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for name in SOURCES}


def identity(plan, index):
    return canonical_hash({"plan": canonical_hash(plan), "episode": plan["episodes"][index]})


def first_files(root, first):
    from src.experiments.report2 import development_plan
    plan = development_plan(root)
    files = [first / name for name in ("proposal.json", "approved_budget.json", "approved_authorization.json", "pilot_audit.json")]
    files.append(root / "results/report2/manual_development/claims" / f"{identity(plan, 0)}.json")
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def validate_update(old, new, before, envelope, limit):
    allowed = {"scope_caps_usd", "max_attempts", "approval_reference", "approved_at_utc",
               "qualification", "rates_source", "rates_verified_at_utc", "pricing_version"}
    if any(old.get(k) != new.get(k) for k in set(old) | set(new) if k not in allowed):
        raise ValueError("Continuation cannot change global credit cap, budget identity, tariffs or task coverage.")
    limit = Decimal(str(limit))
    if not limit.is_finite() or not 0 < limit <= 1:
        raise ValueError("This continuation supports at most one incremental gateway credit.")
    if old["cap_usd"] != envelope["cap_usd"] or old["budget_id"] != envelope["budget_id"]:
        raise ValueError("The broader approval must match the active overall budget identity.")
    expected_scope = Decimal(before["scope_exposure_nanos"].get("kaggle", 0)) / SCALE + limit
    if (Decimal(str(new["scope_caps_usd"]["kaggle"])) != expected_scope
            or expected_scope > Decimal(str(envelope["scope_caps_usd"]["kaggle"]))
            or set(new["scope_caps_usd"]) != set(old["scope_caps_usd"])
            or any(new["scope_caps_usd"][k] != v for k, v in old["scope_caps_usd"].items() if k != "kaggle")
            or sum(Decimal(str(v)) for v in new["scope_caps_usd"].values()) > Decimal(str(old["cap_usd"]))):
        raise ValueError("Continuation allocation exceeds the approved retail envelope.")
    if new["max_attempts"] != before["attempts"] + 23 * 28 or new["max_attempts"] > envelope["max_attempts"]:
        raise ValueError("Exactly 644 additional attempts must fit the broader approved attempt ceiling.")
    if not new.get("approval_reference") or new["approval_reference"] == old["approval_reference"]:
        raise ValueError("A distinct manual continuation approval reference is required.")


def prepare(snapshot, ledger_path, first, root=ROOT):
    from src.experiments.report2 import development_plan
    verify_implementation(root)
    first = Path(first).resolve()
    if not first.is_relative_to(root / "results/report2"):
        raise ValueError("First-branch evidence must remain inside the local report 2 workspace.")
    initial = read_json(first / "proposal.json")
    audit = audit_first_branch(initial, read_json(first / "gateway_snapshot.json"), first, root)
    if not audit.get("pilot_measured") or audit["completed_development_branches"] != 1:
        raise ValueError("A complete audited first branch is required before continuation.")
    old, before = current_allowance(ledger_path)
    expected = root / "results/budgets" / f"{old['budget_id']}.sqlite"
    if Path(ledger_path).resolve() != expected.resolve():
        raise ValueError("Use the unchanged cumulative ledger identity.")
    rate = validate_snapshot(snapshot, old)
    plan = development_plan(root)
    if len(plan["episodes"]) != 24:
        raise ValueError("The frozen development matrix must contain exactly 24 branches.")
    batch = root / "results/report2/manual_development"
    claims = list((batch / "claims").glob("*.json"))
    if len(claims) != 1 or claims[0].stem != identity(plan, 0):
        raise ValueError("Preparation requires only the audited first branch; use the existing continuation for later progress.")
    envelope = initial["old_allowance"]
    limit = 1.0
    new = copy.deepcopy(old)
    new.update(max_attempts=before["attempts"] + 644,
               approval_reference="manual continuation approval pending", approved_at_utc=None,
               rates_source="https://api.shopaikey.com/pricing", rates_verified_at_utc=snapshot["checked_at_utc"],
               pricing_version=snapshot["pricing_version"],
               qualification="Remaining 23 report2 development branches only; first branch retained; 1 additional credit and 644 attempts; overall cap unchanged.")
    new["scope_caps_usd"]["kaggle"] = float(Decimal(before["scope_exposure_nanos"].get("kaggle", 0)) / SCALE + Decimal(str(limit)))
    validate_update(old, new, before, envelope, limit)
    balances = snapshot.get("balance", {})
    reported = [balances[k] for k in ("remaining", "balance") if type(balances.get(k)) in (float, int)]
    if reported and min(reported) < limit:
        raise ValueError("Provider-reported remaining credit is below the continuation ceiling.")
    mean_in = audit["input_tokens"] / audit["user_model_attempts"]
    mean_out = audit["output_tokens"] / audit["user_model_attempts"]
    mean_cost = token_cost(rate, mean_in, mean_out)
    forecast = {"currency": "USD_gateway_credit", "basis": "One audited control/full-history development branch; extrapolation only",
                "remaining_branches": 23, "remaining_decisions": 322, "maximum_additional_attempts": 644,
                "expected_attempts": audit["user_model_attempts"] * 23,
                "base_credits": mean_cost * audit["user_model_attempts"] * 23,
                "all_repair_mean_usage_credits": mean_cost * 644,
                "double_mean_usage_all_repair_credits": mean_cost * 644 * 2,
                "serial_api_minutes_proxy": audit["serial_api_seconds"] * 23 / 60,
                "incremental_credit_limit": limit,
                "qualification": "Different histories and shocks may change usage and reliability. Hard local accounting limits can stop an incomplete branch; provider billing is not independently attested."}
    result = {"schema_version": 1, "stage": "3_remaining_development", "status": "prepared_awaiting_user_manual_run",
              "model_calls_made": 0, "plan_sha256": canonical_hash(plan), "source_sha256": code_hashes(root),
              "first_files_sha256": first_files(root, first), "first_directory": first.relative_to(root).as_posix(),
              "gateway_snapshot_sha256": canonical_hash(snapshot),
              "ledger_relative_path": expected.relative_to(root).as_posix(),
              "old_allowance": old, "old_allowance_sha256": fingerprint(old), "before": before,
              "broader_envelope": envelope, "prospective_allowance": new,
              "pending_branch_indices": list(range(1, 24)), "incremental_credit_limit": limit,
              "forecast": forecast}
    result["proposal_sha256"] = canonical_hash(result)
    return result


def verify(proposal, snapshot, root=ROOT, *, before_activation=True, fresh=True):
    from src.experiments.report2 import development_plan
    verify_implementation(root)
    if (proposal["proposal_sha256"] != canonical_hash({k: v for k, v in proposal.items() if k != "proposal_sha256"})
            or proposal["source_sha256"] != code_hashes(root)
            or proposal["plan_sha256"] != canonical_hash(development_plan(root))
            or proposal["gateway_snapshot_sha256"] != canonical_hash(snapshot)
            or fingerprint(proposal["old_allowance"]) != proposal["old_allowance_sha256"]
            or proposal["pending_branch_indices"] != list(range(1, 24))):
        raise ValueError("Continuation proposal, code, plan or original allowance changed.")
    first = (root / proposal["first_directory"]).resolve()
    if not first.is_relative_to(root / "results/report2") or first_files(root, first) != proposal["first_files_sha256"]:
        raise ValueError("The first audited branch or its approval evidence changed.")
    initial = read_json(first / "proposal.json")
    if proposal["broader_envelope"] != initial["old_allowance"]:
        raise ValueError("Broader approval does not match the retained first-branch preparation.")
    validate_snapshot(snapshot, proposal["old_allowance"],
                      now=None if fresh else datetime.fromisoformat(snapshot["checked_at_utc"]))
    expected = root / "results/budgets" / f"{proposal['old_allowance']['budget_id']}.sqlite"
    if (root / proposal["ledger_relative_path"]).resolve() != expected.resolve():
        raise ValueError("Continuation ledger path differs from its budget identity.")
    validate_update(proposal["old_allowance"], proposal["prospective_allowance"], proposal["before"],
                    proposal["broader_envelope"], proposal["incremental_credit_limit"])
    if before_activation:
        old, state = current_allowance(expected)
        if fingerprint(old) != proposal["old_allowance_sha256"] or state != proposal["before"]:
            raise ValueError("Ledger changed since continuation costing; no automatic reactivation.")


def activate(proposal, snapshot, directory, *, approve_credit_limit, root=ROOT):
    from scripts.run_report2_pilot import authorization_template, validate_authorization
    from src.experiments.report2 import development_plan
    verify(proposal, snapshot, root)
    if Decimal(str(approve_credit_limit)) != Decimal(str(proposal["incremental_credit_limit"])):
        raise ValueError("Manual continuation approval must match the proposed credit ceiling.")
    folder = Path(directory)
    for name in ("ledger_before_activation.sqlite", "approved_budget.json", "approved_authorization.json"):
        if (folder / name).exists():
            raise ValueError("Continuation activation artifacts already exist; inspect them before proceeding.")
    new = copy.deepcopy(proposal["prospective_allowance"])
    now = datetime.now(timezone.utc).isoformat()
    new.update(approval_reference=f"User manually approved remaining report2 development branches with {approve_credit_limit} incremental credits at {now}",
               approved_at_utc=now)
    validate_update(proposal["old_allowance"], new, proposal["before"], proposal["broader_envelope"], approve_credit_limit)
    plan = development_plan(root)
    auth = authorization_template(plan)
    # The original runner counts requests cumulatively across the entire pilot.
    # Include already-complete branch 0 in the 336/672 totals; its claim blocks reruns.
    auth.update(approved=True, approval_reference=new["approval_reference"], allowed_branch_indices=list(range(24)),
                max_decisions=336, max_attempts=672, budget_sha256=fingerprint(new))
    validate_authorization(auth, new, plan, 1)
    path = root / proposal["ledger_relative_path"]
    with closing(connect_readonly(path)) as source, closing(sqlite3.connect(folder / "ledger_before_activation.sqlite")) as target:
        source.backup(target)
    for name, value in (("approved_budget.json", new), ("approved_authorization.json", auth)):
        with (folder / name).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2) + "\n")
    with closing(sqlite3.connect(path)) as db:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT fingerprint FROM config").fetchone()[0] != proposal["old_allowance_sha256"] or ledger_state(db) != proposal["before"]:
                raise ValueError("Ledger changed during manual activation; transaction rolled back.")
            db.execute("INSERT INTO allowance_amendments VALUES (?,?,?)", (now, json.dumps(proposal["old_allowance"]), json.dumps(new)))
            db.execute("UPDATE config SET fingerprint=?", (fingerprint(new),))
            if ledger_state(db) != proposal["before"]:
                raise ValueError("Prior attempts or holds changed; activation rolled back.")
    receipt = {"status": "activated_remaining_development_pending", "proposal_sha256": proposal["proposal_sha256"],
               "budget_sha256": fingerprint(new), "incremental_credit_limit": approve_credit_limit,
               "model_calls_made": 0, "prior_attempts_and_holds_unchanged": True}
    (folder / "activation_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def active_state(proposal, snapshot, folder, root=ROOT, *, fresh=True):
    from src.experiments.report2 import development_plan
    from scripts.run_report2_pilot import check_prior_claim, validate_authorization
    verify(proposal, snapshot, root, before_activation=False, fresh=fresh)
    folder = Path(folder)
    receipt = read_json(folder / "activation_receipt.json")
    budget = read_json(folder / "approved_budget.json")
    auth = read_json(folder / "approved_authorization.json")
    plan = development_plan(root)
    if receipt["proposal_sha256"] != proposal["proposal_sha256"] or receipt["budget_sha256"] != fingerprint(budget):
        raise ValueError("Active allowance receipt differs from the continuation proposal.")
    validate_update(proposal["old_allowance"], budget, proposal["before"], proposal["broader_envelope"], proposal["incremental_credit_limit"])
    validate_authorization(auth, budget, plan, 1)
    if auth["allowed_branch_indices"] != list(range(24)):
        raise ValueError("Continuation authorization must cover the full frozen development pilot.")
    path = root / proposal["ledger_relative_path"]
    remaining_ids = [identity(plan, i) for i in range(1, 24)]
    with closing(connect_readonly(path)) as db:
        if db.execute("SELECT fingerprint FROM config").fetchone()[0] != fingerprint(budget):
            raise ValueError("The active cumulative allowance changed; review before continuing.")
        state = ledger_state(db)
        marks = ",".join("?" for _ in remaining_ids)
        old_rows = db.execute(f"SELECT * FROM attempts WHERE run_id NOT IN ({marks}) ORDER BY id", remaining_ids).fetchall()
        charged_runs = {r[0] for r in db.execute(f"SELECT DISTINCT run_id FROM attempts WHERE run_id IN ({marks})", remaining_ids)}
    if canonical_hash({"rows": old_rows}) != proposal["before"]["attempts_sha256"] or state["holds_sha256"] != proposal["before"]["holds_sha256"]:
        raise ValueError("Earlier attempts/holds changed or an unrelated run appeared.")
    if state["pending_attempts"] or state["blocking_uncertain_attempts"]:
        raise ValueError("Pending or unbounded unknown charges require review; no automatic paid retry.")
    batch = root / "results/report2/manual_development"
    completed = []
    known = {identity(plan, i): i for i in range(24)}
    for claim in (batch / "claims").glob("*.json"):
        if claim.stem not in known:
            raise ValueError("Unexpected branch claim in the frozen development cohort.")
        check_prior_claim(batch, claim)
        saved = read_json(claim)
        if known[claim.stem] != 0 and (saved["budget_sha256"] != fingerprint(budget) or saved["authorization_sha256"] != canonical_hash(auth)):
            raise ValueError("Completed continuation branch used a different approval.")
        completed.append(known[claim.stem])
    if 0 not in completed:
        raise ValueError("The original first branch must remain completed.")
    completed_ids = {identity(plan, i) for i in completed}
    request_dirs = {p.name for p in (batch / "requests").glob("*") if p.is_dir()}
    if not charged_runs.issubset(completed_ids) or not request_dirs.issubset(completed_ids):
        raise ValueError("Paid or request artifacts exist without a verified completed claim; inspect before any continuation.")
    delta = state["exposure_nanos"] - proposal["before"]["exposure_nanos"]
    if delta < 0 or Decimal(delta) / SCALE > Decimal(str(proposal["incremental_credit_limit"])):
        raise ValueError("Continuation exposure exceeds its incremental ceiling.")
    return sorted(completed), state


def run_pending(proposal, snapshot, folder, runner, root=ROOT, *, manual=False):
    """Invoke an injected subprocess runner only after explicit user execution."""
    if not manual:
        raise ValueError("Model execution requires an explicit user manual command.")
    folder = Path(folder)
    completed, _ = active_state(proposal, snapshot, folder, root)
    new_runs = 0
    for index in range(1, 24):
        if index in completed:
            continue
        print(json.dumps({"branch_index": index, "completed_before_launch": len(completed), "planned_branches": 24}), flush=True)
        code = runner(index, folder / "approved_authorization.json", folder / "approved_budget.json")
        if code != 0:
            return {"status": "stopped_requires_review", "failed_branch_index": index, "new_branches_launched": new_runs + 1,
                    "next_gate": "Preserve the claim and request evidence review; do not retry the interrupted branch"}, code
        new_runs += 1
        completed, _ = active_state(proposal, snapshot, folder, root)
        if index not in completed:
            raise ValueError("Child reported success without a verified completed claim.")
    return {"status": "development_execution_complete_requires_audit", "completed_branches": len(completed),
            "new_branches_launched": new_runs, "next_gate": "Offline cohort audit before Stage 4"}, 0


def audit(proposal, snapshot, folder, root=ROOT):
    from src.experiments.report2 import development_plan, validate_branch
    folder = Path(folder)
    if not (folder / "activation_receipt.json").exists():
        verify(proposal, snapshot, root, fresh=False)
        return {"stage": 3, "status": "awaiting_user_manual_continuation", "completed_branches": 1,
                "planned_branches": 24, "audit_model_calls_made": 0}
    completed, state = active_state(proposal, snapshot, folder, root, fresh=False)
    plan = development_plan(root)
    batch = root / "results/report2/manual_development"
    first = root / proposal["first_directory"]
    approval_sets = {
        "first": (read_json(first / "approved_budget.json"), read_json(first / "approved_authorization.json")),
        "continuation": (read_json(folder / "approved_budget.json"), read_json(folder / "approved_authorization.json")),
    }
    audit_dir = folder / ("audit_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    audit_dir.mkdir()
    rows = []
    with closing(connect_readonly(root / proposal["ledger_relative_path"])) as db:
        for index in completed:
            episode = plan["episodes"][index]
            key = identity(plan, index)
            run = batch / "branches" / key
            claim = read_json(batch / "claims" / f"{key}.json")
            branch_manifest = read_json(run / "run_manifest.json")
            if (claim.get("episode") != episode or branch_manifest.get("policy") != "llm_with_fallback"
                    or any(branch_manifest.get(k) != episode[k] for k in ("scenario", "history", "realization"))):
                raise ValueError(f"Branch {index} scenario/history identity differs from its frozen plan entry.")
            budget, auth = approval_sets["first" if index == 0 else "continuation"]
            if claim["budget_sha256"] != fingerprint(budget) or claim["authorization_sha256"] != canonical_hash(auth):
                raise ValueError("A completed branch differs from its historical approval.")
            group = batch / "cases" / episode["case_id"]
            prefix = read_json(group / "warmup/prefix.json")
            validate_branch(group / "prepared/inputs", prefix, run, audit_dir / f"branch_{index:02d}")
            ledger_rows = db.execute("SELECT id,actual_nanos,status FROM attempts WHERE run_id=?", (key,)).fetchall()
            by_id = {row[0]: row for row in ledger_rows}
            events = [json.loads(s) for s in (batch / "requests" / key / "api_attempts.jsonl").read_text().splitlines()]
            starts = [e for e in events if e["event"] == "started"]
            finishes = [e for e in events if e["event"] == "finished"]
            if (len(starts) != len(by_id) or len(finishes) != len(by_id)
                    or len({e["attempt_id"] for e in starts}) != len(starts)
                    or len({e["attempt_id"] for e in finishes}) != len(finishes)
                    or {e["attempt_id"] for e in starts} != set(by_id)
                    or {e["attempt_id"] for e in finishes} != set(by_id)
                    or any(row[2] != "settled" or row[1] is None for row in ledger_rows)
                    or any(e.get("requested_model") != MODEL or e.get("status") != "completed"
                           or e.get("cost_usd") is None
                           or not math.isclose(e["cost_usd"], by_id[e["attempt_id"]][1] / SCALE, abs_tol=1e-9, rel_tol=0)
                           for e in finishes)):
                raise ValueError(f"Branch {index} attempt identities or charges differ from the ledger.")
            summary = read_json(run / "summary.json")
            if summary["model_calls_made"] != len(by_id) or not 14 <= len(by_id) <= 28:
                raise ValueError("Branch response counts differ from the saved summary.")
            rows.append({"branch_index": index, **episode, "decisions": summary["completed_decisions"],
                         "first_pass_valid": summary["first_pass_valid"], "repair_attempts": summary["repair_attempts"],
                         "successful_repairs": summary["successful_repairs"], "fallback_days": summary["fallback_days"],
                         "model_attempts": len(by_id), "known_credits": sum(row[1] for row in ledger_rows) / SCALE,
                         "input_tokens": sum(e["usage"]["prompt_tokens"] for e in finishes),
                         "output_tokens": sum(e["usage"]["completion_tokens"] for e in finishes),
                         "serial_api_seconds": sum(e["latency_seconds"] for e in finishes),
                         "post_split_contribution": summary["post_split_contribution"], "fill_rate": summary["fill_rate"]})
    spent = sum(Decimal(str(r["known_credits"])) for r in rows if r["branch_index"] != 0)
    if abs(spent - Decimal(state["exposure_nanos"] - proposal["before"]["exposure_nanos"]) / SCALE) > Decimal("0.000000001"):
        raise ValueError("Continuation cost and cumulative exposure delta differ.")
    totals = {k: sum(r[k] for r in rows) for k in ("decisions", "first_pass_valid", "repair_attempts", "successful_repairs",
              "fallback_days", "model_attempts", "known_credits", "input_tokens", "output_tokens", "serial_api_seconds")}
    complete = completed == list(range(24))
    result = {"stage": 3, "status": "development_pilot_audited_stage3_complete" if complete else "partial_development_pilot_audited",
              "completed_branches": len(completed), "planned_branches": 24, "audit_model_calls_made": 0,
              "production_evaluation_started": False, "totals": totals,
              "remaining_project_credits": proposal["old_allowance"]["cap_usd"] - state["exposure_nanos"] / SCALE,
              "qualification": "Development evidence only; two selected cases, not the production matrix or population-level adaptation evidence",
              "next_gate": "User reviews Stage 3 before production evaluation preparation", "branches": rows}
    (folder / "development_audit.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
