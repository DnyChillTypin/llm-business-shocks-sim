"""Explicit manual transport restart, retaining every original request and charge.

The frozen runner remains unchanged. A reviewed incomplete branch is archived,
then replaced from its original prefix. This layer counts archived requests too.
Preparation/check/audit are offline; only the manual driver launches models.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.experiments.kaggle_protocol import write
from src.research.report2 import ROOT, canonical_hash, read_json
from src.research.report2_development import identity, verify as verify_continuation
from src.research.report2_interruption import file_hashes, json_lines, reconcile_requests
from src.research.report2_pilot import SCALE, connect_readonly, fingerprint, ledger_state, validate_snapshot

SOURCES = ("src/research/report2_recovery.py", "scripts/recover_report2_development.py",
           "tests/test_report2_recovery.py")
TIMEOUT = "api_APITimeoutError_http_unknown"


def code_hashes(root):
    return {n: hashlib.sha256((root / n).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for n in SOURCES}


def local_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root / "results/report2"):
        raise ValueError("Recovery artifacts must remain inside local results/report2.")
    return path


def read_ledger(path):
    with closing(connect_readonly(path)) as db:
        rows = db.execute("SELECT * FROM attempts ORDER BY id").fetchall()
        holds = db.execute("SELECT * FROM bounded_holds ORDER BY attempt_id").fetchall()
        fields = [r[1] for r in db.execute("PRAGMA table_info(attempts)")]
        return (db.execute("SELECT fingerprint FROM config").fetchone()[0], ledger_state(db),
                [dict(zip(fields, r)) for r in rows], [list(r) for r in holds])


def verify_original_files(batch, hashes, excluded=()):
    for relative, digest in hashes.items():
        if any(relative == p or relative.startswith(p + "/") for p in excluded):
            continue
        path = batch / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Previously reviewed canonical evidence changed: " + relative)


def archive_specs(proposal):
    key = proposal["restart_identity"]
    return (f"branches/{key}", f"requests/{key}", f"claims/{key}.json")


def prepare(continuation, review_file, snapshot, root=ROOT):
    from src.experiments.report2 import development_plan
    root, continuation, review_file = Path(root).resolve(), Path(continuation).resolve(), Path(review_file).resolve()
    for path in (continuation, review_file):
        local_path(root, path.relative_to(root))
    original = read_json(continuation / "proposal.json")
    verify_continuation(original, read_json(continuation / "gateway_snapshot.json"), root,
                        before_activation=False, fresh=False)
    incident = read_json(review_file)
    if (incident.get("status") != "interruption_reviewed_stage3_incomplete"
            or incident.get("audit_model_calls_made") != 0 or not incident.get("canonical_evidence_unchanged")
            or not incident.get("ledger_unchanged")):
        raise ValueError("A completed offline interruption review is required.")
    for name, digest in incident["review_source_sha256"].items():
        if hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() != digest:
            raise ValueError("Interruption reviewer changed after the saved review.")
    plan = development_plan(root)
    index = incident["interrupted"]["branch_index"]
    key = identity(plan, index)
    budget = read_json(continuation / "approved_budget.json")
    validate_snapshot(snapshot, budget)
    ledger = root / original["ledger_relative_path"]
    if ledger.resolve() != (root / "results/budgets" / f"{budget['budget_id']}.sqlite").resolve():
        raise ValueError("Recovery must use the existing cumulative budget identity.")
    active, state, rows, holds = read_ledger(ledger)
    batch = root / "results/report2/manual_development"
    if (active != fingerprint(budget) or state != incident["budget_state"]
            or file_hashes(batch) != incident["canonical_artifact_sha256"]):
        raise ValueError("Evidence or ledger changed after interruption review; review again.")
    failed = incident["interrupted"]["failed_requests"]
    if len(failed) != 1 or failed[0]["failure_category"] != TIMEOUT:
        raise ValueError("This recovery supports one reviewed transport timeout only.")
    attempt = next(r for r in rows if r["id"] == failed[0]["attempt_id"])
    if (attempt["run_id"] != key or attempt["status"] != "uncertain" or attempt["actual_nanos"] is not None
            or state["blocking_uncertain_attempts"] != 1 or state["pending_attempts"]
            or attempt["uncertainty_reason"] != TIMEOUT
            or Decimal(str(failed[0]["reserved_cost_usd"])) != Decimal(attempt["reserved_nanos"]) / SCALE):
        raise ValueError("Reviewed timeout and cumulative uncertain reservation differ.")
    pilot_ids = {identity(plan, i) for i in range(24)}
    pilot_attempts = sum(r["run_id"] in pilot_ids for r in rows)
    additional = (24 - index) * 28
    if state["attempts"] + additional > budget["max_attempts"] or pilot_attempts + additional > 672:
        raise ValueError("Reviewed restart cannot fit existing physical attempt ceilings.")
    if index < 1 or incident["completed_branches"] != index:
        raise ValueError("A contiguous completed cohort must precede the restart.")
    result = {"schema_version": 1, "status": "ready_for_user_manual_recovery", "model_calls_made": 0,
              "continuation": continuation.relative_to(root).as_posix(),
              "review": review_file.relative_to(root).as_posix(),
              "review_sha256": canonical_hash(incident), "source_sha256": code_hashes(root),
              "plan_sha256": canonical_hash(plan), "ledger_relative_path": original["ledger_relative_path"],
              "snapshot": snapshot, "old_budget": budget,
              "continuation_files": file_hashes(continuation),
              "before": state, "baseline_attempts": rows, "baseline_holds": holds,
              "original_artifacts": incident["canonical_artifact_sha256"],
              "restart_index": index, "restart_identity": key, "failed_attempt": attempt,
              "archive_attempt_ids": sorted(r["id"] for r in rows if r["run_id"] == key),
              "recovery_branch_indices": list(range(index, 24)), "pilot_attempts_before": pilot_attempts,
              "held_credits": attempt["reserved_nanos"] / SCALE,
              "additional_credit_limit": 0,
              "remaining_existing_retail_allocation": budget["scope_caps_usd"]["kaggle"] - state["scope_exposure_nanos"]["kaggle"] / SCALE,
              "replacement_policy": "Explicit transport restart from original matched prefix; archive partial outcomes and costs separately"}
    result["proposal_sha256"] = canonical_hash(result)
    return result


def verify(proposal, root=ROOT, *, fresh=False):
    from src.experiments.report2 import development_plan
    if (proposal["proposal_sha256"] != canonical_hash({k: v for k, v in proposal.items() if k != "proposal_sha256"})
            or proposal["source_sha256"] != code_hashes(root)
            or proposal["plan_sha256"] != canonical_hash(development_plan(root))):
        raise ValueError("Recovery proposal, source or frozen plan changed.")
    folder = local_path(root, proposal["continuation"])
    if file_hashes(folder) != proposal["continuation_files"]:
        raise ValueError("Original continuation approval evidence changed.")
    original = read_json(folder / "proposal.json")
    verify_continuation(original, read_json(folder / "gateway_snapshot.json"), root,
                        before_activation=False, fresh=False)
    if canonical_hash(read_json(local_path(root, proposal["review"]))) != proposal["review_sha256"]:
        raise ValueError("Original interruption review changed.")
    validate_snapshot(proposal["snapshot"], proposal["old_budget"],
                      now=None if fresh else datetime.fromisoformat(proposal["snapshot"]["checked_at_utc"]))
    return original


def check_before(proposal, root=ROOT, *, fresh=False):
    verify(proposal, root, fresh=fresh)
    active, state, rows, holds = read_ledger(root / proposal["ledger_relative_path"])
    if (active != fingerprint(proposal["old_budget"]) or state != proposal["before"]
            or rows != proposal["baseline_attempts"] or holds != proposal["baseline_holds"]):
        raise ValueError("Ledger changed since recovery preparation; no automatic reactivation.")
    batch = root / "results/report2/manual_development"
    # Execution lock contents are not research evidence.
    current = file_hashes(batch)
    current.pop(".kaggle_execution.lock", None)
    if current != proposal["original_artifacts"]:
        raise ValueError("Canonical evidence changed since recovery preparation.")
    return state


def validate_budget(proposal, new):
    old = proposal["old_budget"]
    allowed = {"approval_reference", "approved_at_utc", "qualification", "bounded_unknown_failure_categories"}
    expected_categories = sorted(set(old.get("bounded_unknown_failure_categories", [])) | {TIMEOUT})
    if (any(old.get(k) != new.get(k) for k in set(old) | set(new) if k not in allowed)
            or new.get("bounded_unknown_failure_categories") != expected_categories
            or not new.get("approval_reference") or new["approval_reference"] == old["approval_reference"]):
        raise ValueError("Recovery cannot change credit/attempt ceilings, identity, model, task coverage or tariffs.")


def activate(proposal, folder, *, approve_held_credits, root=ROOT):
    from scripts.run_report2_pilot import authorization_template, validate_authorization
    from src.experiments.report2 import development_plan
    if Decimal(str(approve_held_credits)) != Decimal(proposal["failed_attempt"]["reserved_nanos"]) / SCALE:
        raise ValueError("Manual approval must retain the entire reviewed unknown-charge reservation.")
    check_before(proposal, root, fresh=True)
    folder = Path(folder).resolve()
    local_path(root, folder.relative_to(root))
    for name in ("ledger_before_recovery.sqlite", "approved_budget.json", "approved_authorization.json", "archive", "activation_receipt.json"):
        if (folder / name).exists():
            raise ValueError("Recovery activation already started; inspect saved artifacts rather than reactivating.")
    now = datetime.now(timezone.utc).isoformat()
    budget = copy.deepcopy(proposal["old_budget"])
    budget.update(approval_reference=f"User manual reviewed transport restart; retain full timeout reserve at {now}",
                  approved_at_utc=now,
                  qualification="Restart interrupted development branch and finish frozen pilot; all archived charges retained; existing caps unchanged.",
                  bounded_unknown_failure_categories=sorted(set(budget.get("bounded_unknown_failure_categories", [])) | {TIMEOUT}))
    validate_budget(proposal, budget)
    auth = authorization_template(development_plan(root))
    auth.update(approved=True, approval_reference=budget["approval_reference"], allowed_branch_indices=list(range(24)),
                max_decisions=336, max_attempts=672, budget_sha256=fingerprint(budget),
                qualification="Reviewed transport replacement; wrapper additionally counts archived physical attempts.")
    validate_authorization(auth, budget, development_plan(root), proposal["restart_index"])
    path = root / proposal["ledger_relative_path"]
    with closing(connect_readonly(path)) as source, closing(sqlite3.connect(folder / "ledger_before_recovery.sqlite")) as target:
        source.backup(target)
    write(folder / "approved_budget.json", budget)
    write(folder / "approved_authorization.json", auth)
    hold = [proposal["failed_attempt"]["id"], budget["approval_reference"], now,
            "Reviewed timeout: usage unknown; retain entire original reservation, with no fabricated tokens or zero charge."]
    # Amendment and bounded hold are one transaction. Existing attempt rows are never updated.
    with closing(sqlite3.connect(path)) as db:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT fingerprint FROM config").fetchone()[0] != fingerprint(proposal["old_budget"]) or ledger_state(db) != proposal["before"]:
                raise ValueError("Ledger changed during recovery activation; transaction rolled back.")
            db.execute("INSERT INTO allowance_amendments VALUES (?,?,?)", (now, json.dumps(proposal["old_budget"]), json.dumps(budget)))
            db.execute("UPDATE config SET fingerprint=?", (fingerprint(budget),))
            db.execute("INSERT INTO bounded_holds VALUES (?,?,?,?)", hold)
            if ledger_state(db)["attempts_sha256"] != proposal["before"]["attempts_sha256"]:
                raise ValueError("Existing attempts changed; transaction rolled back.")
    batch = root / "results/report2/manual_development"
    # Resolve every move inside the specifically named batch/archive before any rename.
    archive = (folder / "archive").resolve()
    if not archive.is_relative_to(folder) or archive.is_relative_to(batch):
        raise ValueError("Recovery archive must be separate from the canonical batch.")
    for relative in archive_specs(proposal):
        source, destination = (batch / relative).resolve(), (archive / relative).resolve()
        if not source.is_relative_to(batch) or not destination.is_relative_to(archive) or destination.exists():
            raise ValueError("Archive move escaped the named workspace or would overwrite evidence.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
    archive_hashes = file_hashes(archive)
    expected = {n: h for n, h in proposal["original_artifacts"].items()
                if any(n == p or n.startswith(p + "/") for p in archive_specs(proposal))}
    if archive_hashes != expected:
        raise ValueError("Archive differs from reviewed partial evidence; model execution blocked.")
    receipt = {"status": "recovery_activated_awaiting_manual_models", "model_calls_made": 0,
               "proposal_sha256": proposal["proposal_sha256"], "budget_sha256": fingerprint(budget),
               "authorization_sha256": canonical_hash(auth), "retained_hold": hold,
               "archived_artifact_sha256": archive_hashes, "existing_attempts_unchanged": True,
               "credit_and_attempt_limits_unchanged": True}
    write(folder / "activation_receipt.json", receipt)
    return receipt


def active_state(proposal, folder, root=ROOT, *, fresh=False):
    from scripts.run_report2_pilot import check_prior_claim, validate_authorization
    from src.experiments.report2 import development_plan
    verify(proposal, root, fresh=fresh)
    folder = Path(folder)
    receipt, budget, auth = [read_json(folder / n) for n in ("activation_receipt.json", "approved_budget.json", "approved_authorization.json")]
    validate_budget(proposal, budget)
    plan = development_plan(root)
    validate_authorization(auth, budget, plan, proposal["restart_index"])
    if (receipt["proposal_sha256"] != proposal["proposal_sha256"] or receipt["budget_sha256"] != fingerprint(budget)
            or receipt["authorization_sha256"] != canonical_hash(auth) or auth["allowed_branch_indices"] != list(range(24))):
        raise ValueError("Recovery activation or manual authorization changed.")
    active, state, rows, holds = read_ledger(root / proposal["ledger_relative_path"])
    baseline = {r["id"]: r for r in proposal["baseline_attempts"]}
    if (active != fingerprint(budget) or [r for r in rows if r["id"] in baseline] != proposal["baseline_attempts"]
            or holds != sorted(proposal["baseline_holds"] + [receipt["retained_hold"]], key=lambda r: r[0])
            or receipt["retained_hold"][0] != proposal["failed_attempt"]["id"]
            or receipt["retained_hold"][1] != budget["approval_reference"]):
        raise ValueError("Historical attempts, retained holds or active allowance changed.")
    if state["pending_attempts"] or state["blocking_uncertain_attempts"]:
        raise ValueError("A new interrupted/unknown charge requires review; no automatic paid retry.")
    archive = folder / "archive"
    if file_hashes(archive) != receipt["archived_artifact_sha256"]:
        raise ValueError("Archived interruption evidence changed.")
    expected = {n: h for n, h in proposal["original_artifacts"].items()
                if any(n == p or n.startswith(p + "/") for p in archive_specs(proposal))}
    if receipt["archived_artifact_sha256"] != expected:
        raise ValueError("Archive differs from original reviewed evidence.")
    batch = root / "results/report2/manual_development"
    verify_original_files(batch, proposal["original_artifacts"], archive_specs(proposal))
    known = {identity(plan, i): i for i in range(24)}
    claims = {p.stem: p for p in (batch / "claims").glob("*.json")}
    if not set(claims) <= set(known):
        raise ValueError("Unexpected canonical claim appeared.")
    completed = []
    new_attempts = [r for r in rows if r["id"] not in baseline]
    for key, claim_path in claims.items():
        check_prior_claim(batch, claim_path)
        index, saved = known[key], read_json(claim_path)
        if saved["episode"] != plan["episodes"][index]:
            raise ValueError("Completed branch identity differs from the frozen plan.")
        if index >= proposal["restart_index"]:
            if saved["budget_sha256"] != fingerprint(budget) or saved["authorization_sha256"] != canonical_hash(auth):
                raise ValueError("Replacement branch differs from its recovery approval.")
            paid = [r for r in new_attempts if r["run_id"] == key]
            accounting = reconcile_requests(batch / "requests" / key, paid, key, complete=True)
            summary = read_json(batch / "branches" / key / "summary.json")
            if summary["model_calls_made"] != accounting["model_attempts"] or not 14 <= len(paid) <= 28:
                raise ValueError("Replacement response/physical request denominator differs.")
        completed.append(index)
    completed.sort()
    if completed != list(range(len(completed))) or len(completed) < proposal["restart_index"]:
        raise ValueError("The retained completed cohort changed or has a gap.")
    completed_keys = set(claims)
    if any(r["run_id"] not in completed_keys or known[r["run_id"]] < proposal["restart_index"] for r in new_attempts):
        raise ValueError("New paid attempts lack a completed recovery claim.")
    for kind in ("branches", "requests"):
        if {p.name for p in (batch / kind).iterdir() if p.is_dir()} != completed_keys:
            raise ValueError("Canonical branch/request artifacts differ from completed claims.")
    pilot_ids = set(known)
    pilot_attempts = sum(r["run_id"] in pilot_ids for r in rows)
    if (pilot_attempts > 672 or state["attempts"] > budget["max_attempts"]
            or state["exposure_nanos"] > round(budget["cap_usd"] * SCALE)
            or state["scope_exposure_nanos"]["kaggle"] > round(budget["scope_caps_usd"]["kaggle"] * SCALE)):
        raise ValueError("Cumulative physical attempt or credit ceiling exceeded.")
    return completed, state, pilot_attempts


def run_pending(proposal, folder, runner, root=ROOT, *, manual=False):
    if not manual:
        raise ValueError("Models require explicit user manual execution.")
    launched = 0
    for index in proposal["recovery_branch_indices"]:
        completed, state, pilot_attempts = active_state(proposal, folder, root, fresh=True)
        if index in completed:
            continue
        if pilot_attempts + 28 > 672 or state["attempts"] + 28 > proposal["old_budget"]["max_attempts"]:
            raise ValueError("Too few physical attempt slots remain, including archived requests.")
        print(json.dumps({"branch_index": index, "completed_before_launch": len(completed),
                          "physical_pilot_attempts_including_archive": pilot_attempts}), flush=True)
        code = runner(index, Path(folder) / "approved_authorization.json", Path(folder) / "approved_budget.json")
        launched += 1
        if code:
            return {"status": "stopped_requires_review", "failed_branch_index": index,
                    "new_branches_launched": launched, "next_gate": "Preserve new evidence; do not automatically retry"}, code
        completed, _, _ = active_state(proposal, folder, root, fresh=True)
        if index not in completed:
            raise ValueError("Child success lacks a validated completed claim.")
    return {"status": "development_execution_complete_requires_audit", "new_branches_launched": launched,
            "completed_branches": 24}, 0


def audit(proposal, folder, root=ROOT):
    import shutil
    from src.experiments.report2 import development_plan, validate_branch
    completed, state, pilot_attempts = active_state(proposal, folder, root)
    folder, plan = Path(folder), development_plan(root)
    batch = root / "results/report2/manual_development"
    out = folder / ("audit_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    out.mkdir()
    _, _, rows, _ = read_ledger(root / proposal["ledger_relative_path"])
    archived_ids = set(proposal["archive_attempt_ids"])
    records = []
    for index in completed:
        episode, key = plan["episodes"][index], identity(plan, index)
        run, group = batch / "branches" / key, batch / "cases" / episode["case_id"]
        copied = out / "validation_copies" / key
        shutil.copytree(run, copied)
        validate_branch(group / "prepared/inputs", read_json(group / "warmup/prefix.json"), copied, out / "replays" / key)
        summary = read_json(run / "summary.json")
        paid = [r for r in rows if r["run_id"] == key and r["id"] not in archived_ids]
        accounting = reconcile_requests(batch / "requests" / key, paid, key, complete=True)
        records.append({"branch_index": index, **episode, **accounting,
                        **{k: summary[k] for k in ("completed_decisions", "first_pass_valid", "repair_attempts",
                           "successful_repairs", "fallback_days", "post_split_contribution", "fill_rate")}})
    archived_rows = [r for r in rows if r["id"] in archived_ids]
    archived = reconcile_requests(folder / "archive/requests" / proposal["restart_identity"], archived_rows,
                                  proposal["restart_identity"], complete=False)
    totals = {k: sum(r[k] for r in records) for k in ("completed_decisions", "model_attempts", "known_credits",
              "serial_api_seconds", "first_pass_valid", "repair_attempts", "successful_repairs", "fallback_days")}
    if totals["model_attempts"] + archived["model_attempts"] != pilot_attempts:
        raise ValueError("Archived and completed request counts do not cover every physical pilot attempt.")
    # Recheck originals after saved-action replay; nothing under canonical storage is rewritten.
    active_state(proposal, folder, root)
    result = {"status": "development_pilot_audited_stage3_complete" if len(completed) == 24 else "partial_development_pilot_audited",
              "audit_model_calls_made": 0, "completed_branches": len(completed), "planned_branches": 24,
              "totals": totals, "archived_interruption": archived, "physical_pilot_attempts": pilot_attempts,
              "project_exposure_credits": state["exposure_nanos"] / SCALE,
              "remaining_project_credits": proposal["old_budget"]["cap_usd"] - state["exposure_nanos"] / SCALE,
              "production_evaluation_started": False, "branches": records,
              "qualification": "Development cohort only; archived partial outcomes excluded, all physical requests and uncertain reservations retained",
              "next_gate": "User reviews Stage 3 before any production evaluation"}
    if totals["completed_decisions"]:
        mean_cost = totals["known_credits"] / totals["completed_decisions"]
        mean_call_cost = totals["known_credits"] / totals["model_attempts"]
        result["production_cost_forecast"] = {
            "production_decisions": 18144, "maximum_completions_before_transport_retries": 36288,
            "base_credits": mean_cost * 18144,
            "all_repair_double_mean_request_usage_credits": mean_call_cost * 36288 * 2,
            "serial_api_hours_proxy": totals["serial_api_seconds"] / totals["completed_decisions"] * 18144 / 3600,
            "qualification": "Descriptive development extrapolation only; excludes future transport failures and reserve; no production authorization"}
    write(out / "development_audit.json", result)
    write(folder / "development_audit.json", result)
    return result
