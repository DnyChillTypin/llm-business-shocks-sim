"""Reviewed repeated transport recoveries over the unchanged frozen pilot runner.

Each handoff preserves all preceding archives/approvals and adds exactly one
reviewed timeout. Model launches remain explicit user manual operations.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil

from scripts.run_report2_pilot import check_prior_claim, validate_authorization
from src.experiments.kaggle_protocol import write
from src.experiments.report2 import development_plan, validate_branch
from src.research.report2 import ROOT, canonical_hash, read_json
from src.research.report2_interruption import file_hashes, json_lines, reconcile_requests, replay_partial
from src.research.report2_pilot import SCALE, fingerprint, validate_snapshot
from src.research import report2_recovery as previous

SOURCES = ("src/research/report2_recovery_chain.py", "scripts/resume_report2_development.py",
           "tests/test_report2_recovery_chain.py")


def code_hashes(root):
    return {n: hashlib.sha256((root / n).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for n in SOURCES}


def archive_entries(proposal, folder, receipt, root):
    return proposal.get("previous_archives", []) + [{
        "directory": (Path(folder) / "archive").relative_to(root).as_posix(),
        "identity": proposal["restart_identity"], "attempt_ids": proposal["archive_attempt_ids"],
        "sha256": receipt["archived_artifact_sha256"]}]


def check_history(proposal, root):
    for relative, hashes in proposal.get("history_files", {}).items():
        if file_hashes(previous.local_path(root, relative)) != hashes:
            raise ValueError("A previous recovery approval or archive changed.")
    for name, digest in proposal.get("chain_source_sha256", {}).items():
        if name not in SOURCES or code_hashes(root).get(name) != digest:
            raise ValueError("Recovery-chain source changed after preparation.")


def verify_archives(entries, rows, root):
    seen = set()
    results = []
    for entry in entries:
        folder = previous.local_path(root, entry["directory"])
        ids = set(entry["attempt_ids"])
        if seen & ids or file_hashes(folder) != entry["sha256"]:
            raise ValueError("Archived attempt IDs overlap or archived evidence changed.")
        seen |= ids
        paid = [r for r in rows if r["id"] in ids]
        if {r["id"] for r in paid} != ids:
            raise ValueError("An archived charge disappeared from the cumulative ledger.")
        results.append({"identity": entry["identity"], **reconcile_requests(
            folder / "requests" / entry["identity"], paid, entry["identity"], complete=False)})
    return seen, results


def replay_completed(index, plan, batch, rows, excluded_ids, output):
    key, episode = previous.identity(plan, index), plan["episodes"][index]
    run, group = batch / "branches" / key, batch / "cases" / episode["case_id"]
    manifest = read_json(run / "run_manifest.json")
    if manifest["policy"] != "llm_with_fallback" or any(manifest[k] != episode[k] for k in ("scenario", "history", "realization")):
        raise ValueError("Completed trajectory differs from its frozen treatment.")
    copied = output / "validation_copies" / key
    shutil.copytree(run, copied)
    validate_branch(group / "prepared/inputs", read_json(group / "warmup/prefix.json"), copied, output / "replays" / key)
    paid = [r for r in rows if r["run_id"] == key and r["id"] not in excluded_ids]
    accounting = reconcile_requests(batch / "requests" / key, paid, key, complete=True)
    summary = read_json(run / "summary.json")
    if summary["model_calls_made"] != len(paid) or not 14 <= len(paid) <= 28:
        raise ValueError("Completed trajectory and physical requests differ.")
    return {"branch_index": index, **episode, **accounting,
            **{k: summary[k] for k in ("completed_decisions", "first_pass_valid", "repair_attempts",
               "successful_repairs", "fallback_days", "post_split_contribution", "fill_rate")}}


def review_stopped(folder, output, root=ROOT):
    """Verify an activated recovery that stopped once; never alter its artifacts."""
    folder, output = Path(folder).resolve(), Path(output).resolve()
    previous.local_path(root, folder.relative_to(root))
    previous.local_path(root, output.relative_to(root))
    batch = root / "results/report2/manual_development"
    if output.exists() or output.is_relative_to(folder) or output.is_relative_to(batch):
        raise ValueError("Use a fresh separate local interruption-review directory.")
    proposal = read_json(folder / "proposal.json")
    previous.verify(proposal, root)
    check_history(proposal, root)
    receipt, budget, auth = [read_json(folder / n) for n in
                             ("activation_receipt.json", "approved_budget.json", "approved_authorization.json")]
    previous.validate_budget(proposal, budget)
    plan = development_plan(root)
    validate_authorization(auth, budget, plan, proposal["restart_index"])
    if (receipt["proposal_sha256"] != proposal["proposal_sha256"] or receipt["budget_sha256"] != fingerprint(budget)
            or receipt["authorization_sha256"] != canonical_hash(auth) or auth["allowed_branch_indices"] != list(range(24))):
        raise ValueError("Previous activated recovery approval changed.")
    active, state, rows, holds = previous.read_ledger(root / proposal["ledger_relative_path"])
    baseline_ids = {r["id"] for r in proposal["baseline_attempts"]}
    if (active != fingerprint(budget) or [r for r in rows if r["id"] in baseline_ids] != proposal["baseline_attempts"]
            or holds != sorted(proposal["baseline_holds"] + [receipt["retained_hold"]], key=lambda r: r[0])
            or receipt["retained_hold"][0] != proposal["failed_attempt"]["id"]
            or receipt["retained_hold"][1] != budget["approval_reference"]
            or state["pending_attempts"] or state["blocking_uncertain_attempts"] != 1):
        raise ValueError("Historical charges/holds changed or interruption is not one bounded unknown request.")
    previous.verify_original_files(batch, proposal["original_artifacts"], previous.archive_specs(proposal))
    expected_archive = {n: h for n, h in proposal["original_artifacts"].items()
                        if any(n == p or n.startswith(p + "/") for p in previous.archive_specs(proposal))}
    if receipt["archived_artifact_sha256"] != expected_archive:
        raise ValueError("Previous archive differs from its original reviewed evidence.")
    archives = archive_entries(proposal, folder, receipt, root)
    excluded_ids, archive_results = verify_archives(archives, rows, root)
    known = {previous.identity(plan, i): i for i in range(24)}
    claims = {p.stem: read_json(p) for p in (batch / "claims").glob("*.json")}
    failed = [known[k] for k, c in claims.items() if k in known and c["status"] != "validated_complete"]
    if not set(claims) <= set(known) or len(failed) != 1:
        raise ValueError("Expected one interrupted claim in the frozen cohort.")
    index, key = failed[0], previous.identity(plan, failed[0])
    if index not in proposal["recovery_branch_indices"] or set(claims) != {previous.identity(plan, i) for i in range(index + 1)}:
        raise ValueError("Completed branches must precede the reviewed interruption.")
    for kind in ("branches", "requests"):
        if {p.name for p in (batch / kind).iterdir() if p.is_dir()} != set(claims):
            raise ValueError("Canonical artifacts and claims differ.")
    new_rows = [r for r in rows if r["id"] not in baseline_ids]
    if any(r["run_id"] not in claims or known[r["run_id"]] < proposal["restart_index"] for r in new_rows):
        raise ValueError("Unrelated paid attempts appeared after recovery activation.")
    output.mkdir(parents=True)
    before = file_hashes(batch)
    records = []
    for i in range(index + 1):
        branch_id = previous.identity(plan, i)
        claim = claims[branch_id]
        if claim["episode"] != plan["episodes"][i]:
            raise ValueError("Claim differs from frozen episode identity.")
        if i >= proposal["restart_index"] and (claim["budget_sha256"] != fingerprint(budget)
                                                or claim["authorization_sha256"] != canonical_hash(auth)):
            raise ValueError("New branch differs from its previous recovery approval.")
        if i != index:
            check_prior_claim(batch, batch / "claims" / f"{branch_id}.json")
            records.append(replay_completed(i, plan, batch, rows, excluded_ids, output))
    group = batch / "cases" / plan["episodes"][index]["case_id"]
    run = batch / "branches" / key
    partial = replay_partial(group / "prepared/inputs", read_json(group / "warmup/prefix.json"), run, output / "partial_replay")
    partial_rows = [r for r in rows if r["run_id"] == key and r["id"] not in excluded_ids]
    accounting = reconcile_requests(batch / "requests" / key, partial_rows, key, complete=False)
    failed_requests = accounting["failed_requests"]
    if (len(failed_requests) != 1 or failed_requests[0]["failure_category"] != previous.TIMEOUT
            or not failed_requests[0]["logical_request_id"].startswith("day:" + partial["interrupted_decision_date"] + ":repair:")):
        raise ValueError("Only the reviewed transport timeout can be recovered.")
    pilot_attempts = sum(r["run_id"] in known for r in rows)
    if sum(r["model_attempts"] for r in records) + sum(r["model_attempts"] for r in archive_results) + len(partial_rows) != pilot_attempts:
        raise ValueError("Canonical and archived attempts do not fully cover the pilot.")
    if (pilot_attempts + (24 - index) * 28 > 672 or state["attempts"] + (24 - index) * 28 > budget["max_attempts"]
            or state["exposure_nanos"] > round(budget["cap_usd"] * SCALE)
            or state["scope_exposure_nanos"]["kaggle"] > round(budget["scope_caps_usd"]["kaggle"] * SCALE)):
        raise ValueError("Existing credit or physical-attempt ceiling cannot cover the reviewed restart.")
    if file_hashes(batch) != before or previous.read_ledger(root / proposal["ledger_relative_path"])[1] != state:
        raise ValueError("Original evidence or ledger changed during review.")
    result = {"status": "repeated_interruption_reviewed", "model_calls_made": 0, "completed_branches": index,
              "interrupted": {"branch_index": index, **partial, **accounting}, "completed": records,
              "prior_archives": archive_results, "physical_pilot_attempts": pilot_attempts,
              "budget_state": state, "canonical_artifact_sha256": before}
    write(output / "interruption_review.json", result)
    return result, budget, rows, holds, archives


def prepare(previous_folder, folder, snapshot, root=ROOT):
    previous_folder, folder = Path(previous_folder).resolve(), Path(folder).resolve()
    previous.local_path(root, folder.relative_to(root))
    if folder.exists() or folder.is_relative_to(previous_folder) or previous_folder.is_relative_to(folder):
        raise ValueError("Recovery needs a fresh handoff separate from all previous handoffs.")
    incident, budget, rows, holds, archives = review_stopped(previous_folder, folder / "review", root)
    validate_snapshot(snapshot, budget)
    old = read_json(previous_folder / "proposal.json")
    plan, state = development_plan(root), incident["budget_state"]
    index = incident["interrupted"]["branch_index"]
    key = previous.identity(plan, index)
    attempt_id = incident["interrupted"]["failed_requests"][0]["attempt_id"]
    attempt = next(r for r in rows if r["id"] == attempt_id)
    proposal = {**copy_fields(old), "status": "ready_for_user_manual_recovery", "model_calls_made": 0,
                "source_sha256": previous.code_hashes(root), "chain_source_sha256": code_hashes(root),
                "review": (folder / "review/interruption_review.json").relative_to(root).as_posix(),
                "review_sha256": canonical_hash(incident), "snapshot": snapshot, "old_budget": budget,
                "before": state, "baseline_attempts": rows, "baseline_holds": holds,
                "original_artifacts": incident["canonical_artifact_sha256"],
                "restart_index": index, "restart_identity": key, "failed_attempt": attempt,
                "archive_attempt_ids": sorted(r["id"] for r in rows if r["run_id"] == key
                                              and r["id"] not in {a for e in archives for a in e["attempt_ids"]}),
                "recovery_branch_indices": list(range(index, 24)), "previous_archives": archives,
                "history_files": {**old.get("history_files", {}), previous_folder.relative_to(root).as_posix(): file_hashes(previous_folder)},
                "pilot_attempts_before": incident["physical_pilot_attempts"],
                "held_credits": attempt["reserved_nanos"] / SCALE, "additional_credit_limit": 0,
                "remaining_existing_retail_allocation": budget["scope_caps_usd"]["kaggle"] - state["scope_exposure_nanos"]["kaggle"] / SCALE}
    proposal["proposal_sha256"] = canonical_hash(proposal)
    write(folder / "proposal.json", proposal)
    check_before(proposal, root, fresh=True)
    return proposal


def copy_fields(proposal):
    return {k: proposal[k] for k in ("schema_version", "continuation", "continuation_files", "plan_sha256",
                                     "ledger_relative_path", "replacement_policy")}


def check_before(proposal, root=ROOT, *, fresh=False):
    check_history(proposal, root)
    return previous.check_before(proposal, root, fresh=fresh)


def activate(proposal, folder, *, approve_held_credits, root=ROOT):
    check_history(proposal, root)
    return previous.activate(proposal, folder, approve_held_credits=approve_held_credits, root=root)


def active_state(proposal, folder, root=ROOT, *, fresh=False):
    check_history(proposal, root)
    return previous.active_state(proposal, folder, root, fresh=fresh)


def run_pending(proposal, folder, runner, root=ROOT, *, manual=False):
    if not manual:
        raise ValueError("Models require explicit user manual execution.")
    launched = 0
    for index in proposal["recovery_branch_indices"]:
        completed, state, attempts = active_state(proposal, folder, root, fresh=True)
        if index in completed:
            continue
        if attempts + 28 > 672 or state["attempts"] + 28 > proposal["old_budget"]["max_attempts"]:
            raise ValueError("Too few physical attempt slots remain including all archives.")
        print(json.dumps({"branch_index": index, "completed_before_launch": len(completed),
                          "physical_pilot_attempts_including_archives": attempts}), flush=True)
        code = runner(index, Path(folder) / "approved_authorization.json", Path(folder) / "approved_budget.json")
        launched += 1
        if code:
            return {"status": "stopped_requires_review", "failed_branch_index": index, "new_branches_launched": launched}, code
        if index not in active_state(proposal, folder, root, fresh=True)[0]:
            raise ValueError("Child success lacks a verified completed claim.")
    return {"status": "development_execution_complete_requires_audit", "completed_branches": 24,
            "new_branches_launched": launched}, 0


def audit(proposal, folder, root=ROOT):
    completed, state, attempts = active_state(proposal, folder, root)
    folder = Path(folder)
    plan, batch = development_plan(root), root / "results/report2/manual_development"
    receipt = read_json(folder / "activation_receipt.json")
    _, _, rows, _ = previous.read_ledger(root / proposal["ledger_relative_path"])
    excluded, archives = verify_archives(archive_entries(proposal, folder, receipt, root), rows, root)
    output = folder / ("audit_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir()
    records = [replay_completed(i, plan, batch, rows, excluded, output) for i in completed]
    totals = {k: sum(r[k] for r in records) for k in ("completed_decisions", "model_attempts", "known_credits",
              "serial_api_seconds", "first_pass_valid", "repair_attempts", "successful_repairs", "fallback_days")}
    if totals["model_attempts"] + sum(a["model_attempts"] for a in archives) != attempts:
        raise ValueError("Final audit does not cover all archived and canonical requests.")
    active_state(proposal, folder, root)
    result = {"status": "development_pilot_audited_stage3_complete" if len(completed) == 24 else "partial_development_pilot_audited",
              "audit_model_calls_made": 0, "completed_branches": len(completed), "planned_branches": 24,
              "totals": totals, "archived_interruptions": archives, "physical_pilot_attempts": attempts,
              "remaining_project_credits": proposal["old_budget"]["cap_usd"] - state["exposure_nanos"] / SCALE,
              "production_evaluation_started": False, "branches": records,
              "next_gate": "User reviews Stage 3 and cost feasibility before Stage 4"}
    if totals["completed_decisions"]:
        result["production_cost_forecast"] = {"production_decisions": 18144,
            "base_credits": totals["known_credits"] / totals["completed_decisions"] * 18144,
            "all_repair_double_mean_request_usage_credits": totals["known_credits"] / totals["model_attempts"] * 36288 * 2,
            "serial_api_hours_proxy": totals["serial_api_seconds"] / totals["completed_decisions"] * 18144 / 3600,
            "qualification": "Development extrapolation only; excludes future transport failures/reserve; no production authorization"}
    write(output / "development_audit.json", result)
    write(folder / "development_audit.json", result)
    return result
