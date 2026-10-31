"""Offline first-branch costing and explicit manual allowance activation.

No model client or credential access. Activation only narrows existing credit and
attempt allocations, journals the change, and preserves every attempt and hold.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

from src.research.report2 import ROOT, PROTOCOL, canonical_hash, read_json
from src.research.report2_runtime import verify_implementation

MODEL = "gpt-4.1-mini-2025-04-14"
SOURCE_FILES = ("src/research/report2_pilot.py", "scripts/prepare_report2_pilot.py", "tests/test_report2_pilot.py")
SCALE = 1_000_000_000


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_hashes(root=ROOT):
    return {p: hashlib.sha256((root / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in SOURCE_FILES}


def connect_readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def ledger_state(db):
    attempts = db.execute("SELECT * FROM attempts ORDER BY id").fetchall()
    holds = db.execute("SELECT * FROM bounded_holds ORDER BY attempt_id").fetchall()
    charged = "CASE WHEN status='settled' THEN actual_nanos ELSE MAX(reserved_nanos,COALESCE(actual_nanos,0)) END"
    count, exposure, pending, blocking = db.execute(
        f"SELECT COUNT(*),COALESCE(SUM({charged}),0),COALESCE(SUM(status='pending'),0),"
        "COALESCE(SUM(status='uncertain' AND id NOT IN (SELECT attempt_id FROM bounded_holds)),0) FROM attempts").fetchone()
    scopes = {r[0]: r[1] for r in db.execute(f"SELECT scope,COALESCE(SUM({charged}),0) FROM attempts GROUP BY scope")}
    return {"attempts": count, "exposure_nanos": exposure, "scope_exposure_nanos": scopes,
            "pending_attempts": pending, "blocking_uncertain_attempts": blocking,
            "attempts_sha256": canonical_hash({"rows": attempts}),
            "holds_sha256": canonical_hash({"rows": holds}), "retained_holds": len(holds)}


def current_allowance(path):
    with closing(connect_readonly(path)) as db:
        row = db.execute("SELECT new_manifest FROM allowance_amendments ORDER BY rowid DESC LIMIT 1").fetchone()
        if row is None:
            raise ValueError("No journaled cumulative allowance is available; do not create a replacement ledger.")
        allowance = json.loads(row[0])
        if db.execute("SELECT fingerprint FROM config").fetchone()[0] != fingerprint(allowance):
            raise ValueError("Latest allowance does not match the existing ledger fingerprint.")
        state = ledger_state(db)
    if state["pending_attempts"] or state["blocking_uncertain_attempts"]:
        raise ValueError("Pending or unresolved unbounded charges block preparation.")
    return allowance, state


def validate_snapshot(snapshot, allowance, now=None):
    now = now or datetime.now(timezone.utc)
    if (snapshot.get("provider") != "ShopAIKey" or snapshot.get("base_url") != "https://api.shopaikey.com/v1"
            or snapshot.get("rates_verified") is not True or snapshot.get("missing_models")
            or snapshot.get("paid_api_calls") != 0):
        raise ValueError("A successful read-only configured-gateway snapshot is required.")
    checked = datetime.fromisoformat(snapshot["checked_at_utc"])
    if checked.tzinfo is None or not timedelta(0) <= now - checked <= timedelta(hours=24):
        raise ValueError("Gateway snapshot must be timezone-aware, recent within 24 hours, and not future-dated.")
    precision = Decimal("0.000000000001")
    for model, old in allowance["rates"].items():
        fresh = snapshot["rates"].get(model)
        if fresh is None:
            raise ValueError("An existing allowed model is missing from current applicable tariffs.")
        for field in ("input_per_million", "output_per_million", "per_request"):
            a, b = Decimal(str(old.get(field, 0))), Decimal(str(fresh.get(field, 0)))
            if not a.is_finite() or not b.is_finite() or b < 0 or a.quantize(precision) != b.quantize(precision):
                raise ValueError("Tariffs changed; a separate reviewed rate migration is required.")
    return {**snapshot["rates"][MODEL], "per_request": snapshot["rates"][MODEL].get("per_request", 0)}


def token_cost(rate, input_tokens, output_tokens):
    return float((Decimal(str(input_tokens)) * Decimal(str(rate["input_per_million"]))
                  + Decimal(str(output_tokens)) * Decimal(str(rate["output_per_million"]))) / Decimal(1_000_000)
                 + Decimal(str(rate.get("per_request", 0))))


def legacy_usage(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    inputs = sum(int(r["input_tokens"]) for r in rows)
    outputs = sum(int(r["output_tokens"]) for r in rows)
    attempts = sum(int(r["physical_attempts"]) for r in rows)
    if not rows or attempts <= 0:
        raise ValueError("Historical usage is empty.")
    return {"cohort": "Legacy Stage 5 primary, 12 episodes of 21 decisions",
            "source_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "decisions": len(rows) * 21, "attempts": attempts,
            "input_tokens": inputs, "output_tokens": outputs,
            "serial_api_seconds": sum(float(r["total_serial_api_seconds"]) for r in rows),
            "qualification": "Earlier protocol and context; a planning proxy, not a measured report 2 pilot"}


def cost_worksheet(rate, allowance, historical, observations, protocol):
    from src.agents.llm import serialize_observation
    system = (ROOT / protocol["model"]["system_prompt"]).read_text(encoding="utf-8")
    bounds = []
    for row in observations:
        params = {"model": MODEL, "temperature": 0, "max_tokens": 1024, "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": serialize_observation(row["observation"])}]}
        bounds.append(len(json.dumps(params, sort_keys=True, ensure_ascii=False).encode())
                      + allowance.get("protocol_token_allowance", 4096))
    if len(bounds) != 14:
        raise ValueError("Costing requires 14 development observations, not an evaluation cohort.")
    per_call_input = historical["input_tokens"] / historical["attempts"]
    per_call_output = historical["output_tokens"] / historical["attempts"]
    expected_calls = 14 * historical["attempts"] / historical["decisions"]
    average_cost = token_cost(rate, per_call_input, per_call_output)
    # A high planning scenario, explicitly not a tokenizer or provider guarantee.
    repair_extra = 16 * protocol["model"]["max_output_tokens"] + 1024
    high = 14 * token_cost(rate, max(bounds), 1024) + 14 * token_cost(rate, max(bounds) + repair_extra, 1024)
    return {"currency": "USD_gateway_credit", "branch_index": 0, "decisions": 14, "max_completions": 28,
            "development_observations_sha256": canonical_hash({"rows": observations}),
            "rates": {k: rate[k] for k in ("input_per_million", "output_per_million", "per_request")},
            "historical_proxy": historical,
            "historical_mean_input_tokens_per_attempt": per_call_input,
            "historical_mean_output_tokens_per_attempt": per_call_output,
            "low_credits": 14 * average_cost, "base_credits": expected_calls * average_cost,
            "high_mean_usage_credits": 28 * average_cost,
            "high_reserved_payload_scenario_credits": high,
            "expected_attempts_from_legacy_repair_rate": expected_calls,
            "legacy_serial_time_proxy_seconds": expected_calls * historical["serial_api_seconds"] / historical["attempts"],
            "development_input_reservation_bounds": {"minimum": min(bounds), "maximum": max(bounds)},
            "high_scenario_assumption": "Every day repairs; 1024 output tokens each call; repair adds 16 UTF-8 bytes per output token plus 1024 bytes of scaffolding. Planning assumption, not a guaranteed token-byte bound.",
            "absolute_single_attempt_reservation_ceiling_credits": token_cost(rate, allowance["max_input_tokens_bound"], 1024),
            "qualification": "Local estimates at verified uncached rates; not provider-side billing guarantees. The scope and attempt caps can stop the run before completion."}


def validate_transition(old, new, before, credit_limit):
    """Allow this pilot to consume less of an existing approval, never expand it."""
    allowed_changes = {"approved_at_utc", "approval_reference", "qualification", "allowed_tasks",
                       "scope_caps_usd", "max_attempts", "rates_source", "rates_verified_at_utc", "pricing_version"}
    if any(old.get(k) != new.get(k) for k in set(old) | set(new) if k not in allowed_changes):
        raise ValueError("Pilot activation cannot change identity, global cap, tariff values or other approval fields.")
    limit = Decimal(str(credit_limit))
    if not limit.is_finite() or not 0 < limit <= Decimal("0.50"):
        raise ValueError("First-branch credit limit must be positive and no greater than 0.50.")
    if new.get("approved") is not True or not new.get("approval_reference") or new["approval_reference"] == old["approval_reference"]:
        raise ValueError("Manual activation requires a distinct explicit approval reference.")
    if set(new["allowed_tasks"]) != set(old["allowed_tasks"]) | {"report2:development"}:
        raise ValueError("Only the development pilot task may be added.")
    expected_attempts = before["attempts"] + 28
    if new["max_attempts"] != expected_attempts or expected_attempts > old["max_attempts"]:
        raise ValueError("Pilot must fit 28 attempts inside the prior aggregate ceiling.")
    expected_scope = Decimal(before["scope_exposure_nanos"].get("kaggle", 0)) / SCALE + limit
    if (Decimal(str(new["scope_caps_usd"]["kaggle"])) != expected_scope
            or expected_scope > Decimal(str(old["scope_caps_usd"]["kaggle"]))
            or any(new["scope_caps_usd"].get(k) != v for k, v in old["scope_caps_usd"].items() if k != "kaggle")
            or set(new["scope_caps_usd"]) != set(old["scope_caps_usd"])):
        raise ValueError("Only a smaller Kaggle allocation may be activated.")
    if sum(Decimal(str(v)) for v in new["scope_caps_usd"].values()) > Decimal(str(old["cap_usd"])):
        raise ValueError("Scope allocations exceed the unchanged global cap.")


def build_proposal(snapshot, ledger_path, historical, observations, *, credit_limit=0.50, root=ROOT):
    from src.experiments.report2 import development_plan
    verify_implementation(root)
    protocol = read_json(root / PROTOCOL)
    old, before = current_allowance(ledger_path)
    expected_ledger = root / "results/budgets" / f"{old['budget_id']}.sqlite"
    if Path(ledger_path).resolve() != expected_ledger.resolve():
        raise ValueError("Use the existing ledger path derived from its unchanged budget identity.")
    rate = validate_snapshot(snapshot, old)
    plan = development_plan(root)
    quote = cost_worksheet(rate, old, historical, observations, protocol)
    if not math.isfinite(float(credit_limit)) or not 0 < credit_limit <= 0.50:
        raise ValueError("First branch proposal may reserve at most 0.50 credits.")
    new = copy.deepcopy(old)
    new.update(approval_reference="manual activation pending; not an approval", approved_at_utc=None,
               rates_source="https://api.shopaikey.com/pricing", rates_verified_at_utc=snapshot["checked_at_utc"],
               pricing_version=snapshot["pricing_version"], max_attempts=before["attempts"] + 28,
               qualification="First report 2 manual branch only; narrower allocation and attempt ceiling; historical charges and held reserves retained.")
    new["allowed_tasks"] = list(dict.fromkeys([*old["allowed_tasks"], "report2:development"]))
    new["scope_caps_usd"]["kaggle"] = float(Decimal(before["scope_exposure_nanos"].get("kaggle", 0)) / SCALE + Decimal(str(credit_limit)))
    validate_transition(old, new, before, credit_limit)
    balances = snapshot.get("balance", {})
    reported = [balances[k] for k in ("balance", "remaining") if type(balances.get(k)) in (float, int)]
    if reported and min(reported) < credit_limit:
        raise ValueError("Provider-reported remaining credit is below the proposed first-branch ceiling.")
    proposal = {"schema_version": 1, "stage": "3_preparation", "status": "prepared_awaiting_manual_activation_and_model_run",
                "prepared_at_utc": datetime.now(timezone.utc).isoformat(), "model_calls_made": 0,
                "plan_sha256": canonical_hash(plan), "implementation_sha256": plan["implementation_sha256"],
                "source_sha256": source_hashes(root), "gateway_snapshot_sha256": canonical_hash(snapshot),
                "ledger_relative_path": Path(ledger_path).resolve().relative_to(root.resolve()).as_posix(),
                "before": before, "old_allowance_sha256": fingerprint(old),
                "old_allowance": old, "prospective_allowance": new,
                "incremental_credit_limit": credit_limit, "allowed_branch_indices": [0],
                "cost_worksheet": quote,
                "next_gate": "User manually activates the exact cap and executes branch 0; measured pilot audit pending"}
    proposal["proposal_sha256"] = canonical_hash(proposal)
    return proposal


def verify_proposal(proposal, snapshot, root=ROOT, *, require_unmodified_ledger=True, require_fresh_snapshot=True):
    from src.experiments.report2 import development_plan
    verify_implementation(root)
    if (proposal["proposal_sha256"] != canonical_hash({k: v for k, v in proposal.items() if k != "proposal_sha256"})
            or proposal["source_sha256"] != source_hashes(root)
            or proposal["gateway_snapshot_sha256"] != canonical_hash(snapshot)
            or proposal["plan_sha256"] != canonical_hash(development_plan(root))):
        raise ValueError("Preparation code, plan or bound evidence changed.")
    if fingerprint(proposal["old_allowance"]) != proposal["old_allowance_sha256"]:
        raise ValueError("The proposal's original allowance differs from its bound ledger fingerprint.")
    expected_ledger = root / "results/budgets" / f"{proposal['old_allowance']['budget_id']}.sqlite"
    if (root / proposal["ledger_relative_path"]).resolve() != expected_ledger.resolve():
        raise ValueError("Proposal ledger path differs from its unchanged budget identity.")
    validate_snapshot(snapshot, proposal["old_allowance"],
                      now=None if require_fresh_snapshot else datetime.fromisoformat(snapshot["checked_at_utc"]))
    if require_unmodified_ledger:
        old, state = current_allowance(root / proposal["ledger_relative_path"])
        if fingerprint(old) != proposal["old_allowance_sha256"] or state != proposal["before"]:
            raise ValueError("Cumulative ledger changed after costing; prepare a fresh handoff.")


def activate_proposal(proposal, snapshot, directory, *, approve_credit_limit, root=ROOT):
    """Manual-only, no model requests. Back up, journal, and narrow the allowance."""
    from scripts.run_report2_pilot import authorization_template, validate_authorization
    from src.experiments.report2 import development_plan
    verify_proposal(proposal, snapshot, root)
    if Decimal(str(approve_credit_limit)) != Decimal(str(proposal["incremental_credit_limit"])):
        raise ValueError("Manual credit approval differs from the concrete proposal.")
    directory = Path(directory)
    ledger_path = root / proposal["ledger_relative_path"]
    backup = directory / "ledger_before_activation.sqlite"
    if backup.exists() or (directory / "approved_budget.json").exists() or (directory / "approved_authorization.json").exists():
        raise ValueError("Activation artifacts already exist; inspect the prior activation rather than overwrite them.")
    new = copy.deepcopy(proposal["prospective_allowance"])
    now = datetime.now(timezone.utc).isoformat()
    new.update(approval_reference=f"User manually activated report2 branch 0 with {approve_credit_limit} credit limit at {now}", approved_at_utc=now)
    validate_transition(proposal["old_allowance"], new, proposal["before"], approve_credit_limit)
    plan = development_plan(root)
    auth = authorization_template(plan)
    auth.update(approved=True, approval_reference=new["approval_reference"], budget_sha256=fingerprint(new))
    validate_authorization(auth, new, plan, 0)
    with closing(connect_readonly(ledger_path)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    # Write concrete files first. Until the ledger transaction commits, their
    # fingerprint cannot open the existing ledger, so a partial write cannot spend.
    for name, value in (("approved_budget.json", new), ("approved_authorization.json", auth)):
        with (directory / name).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2) + "\n")
    db = sqlite3.connect(ledger_path)
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            if (db.execute("SELECT fingerprint FROM config").fetchone()[0] != proposal["old_allowance_sha256"]
                    or ledger_state(db) != proposal["before"]):
                raise ValueError("Ledger changed during activation; no allowance update committed.")
            db.execute("INSERT INTO allowance_amendments VALUES (?,?,?)", (now, json.dumps(proposal["old_allowance"]), json.dumps(new)))
            db.execute("UPDATE config SET fingerprint=?", (fingerprint(new),))
            if ledger_state(db) != proposal["before"]:
                raise ValueError("Historical attempts or holds changed; rolling back activation.")
    finally:
        db.close()
    receipt = {"status": "activated_awaiting_manual_model_run", "model_calls_made": 0,
               "proposal_sha256": proposal["proposal_sha256"], "budget_sha256": fingerprint(new),
               "incremental_credit_limit": approve_credit_limit, "branch_index": 0,
               "historical_attempts_and_holds_unchanged": True, "backup": backup.name}
    (directory / "activation_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def audit_first_branch(proposal, snapshot, directory, root=ROOT):
    """Audit completed user-run evidence; an absent result is pending, not a failure or score."""
    from scripts.run_report2_pilot import check_prior_claim, validate_authorization
    from src.experiments.report2 import development_plan, validate_branch
    verify_proposal(proposal, snapshot, root, require_unmodified_ledger=False, require_fresh_snapshot=False)
    directory = Path(directory)
    plan = development_plan(root)
    identity = canonical_hash({"plan": canonical_hash(plan), "episode": plan["episodes"][0]})
    batch = root / "results/report2/manual_development"
    claim_path = batch / "claims" / f"{identity}.json"
    if not claim_path.exists():
        return {"stage": 3, "status": "awaiting_user_manual_model_run", "pilot_measured": False,
                "audit_model_calls_made": 0, "branch_index": 0}
    check_prior_claim(batch, claim_path)
    budget = read_json(directory / "approved_budget.json")
    auth = read_json(directory / "approved_authorization.json")
    validate_authorization(auth, budget, plan, 0)
    claim = read_json(claim_path)
    if claim["budget_sha256"] != fingerprint(budget) or claim["authorization_sha256"] != canonical_hash(auth):
        raise ValueError("Pilot evidence is bound to a different allowance or authorization.")
    case_id = plan["episodes"][0]["case_id"]
    prepared = batch / "cases" / case_id / "prepared/inputs"
    prefix = read_json(batch / "cases" / case_id / "warmup/prefix.json")
    run = batch / "branches" / identity
    replay = directory / ("audit_replay_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    validate_branch(prepared, prefix, run, replay)
    ledger_path = root / proposal["ledger_relative_path"]
    with closing(connect_readonly(ledger_path)) as db:
        current = ledger_state(db)
        if db.execute("SELECT fingerprint FROM config").fetchone()[0] != fingerprint(budget):
            raise ValueError("Allowance changed after the pilot; reconcile before further execution.")
        historical_rows = db.execute("SELECT * FROM attempts WHERE run_id != ? ORDER BY id", (identity,)).fetchall()
        if (canonical_hash({"rows": historical_rows}) != proposal["before"]["attempts_sha256"]
                or current["holds_sha256"] != proposal["before"]["holds_sha256"]):
            raise ValueError("Earlier charges/holds changed or an additional run appeared.")
        ledger_rows = db.execute("SELECT id,actual_nanos,status FROM attempts WHERE run_id=?", (identity,)).fetchall()
        count = len(ledger_rows)
        cost = sum(row[1] or 0 for row in ledger_rows)
    events = [json.loads(s) for s in (batch / "requests" / identity / "api_attempts.jsonl").read_text().splitlines()]
    started = [e for e in events if e["event"] == "started"]
    finished = [e for e in events if e["event"] == "finished"]
    ledger_by_id = {row[0]: row for row in ledger_rows}
    if (len({e["attempt_id"] for e in started}) != len(started)
            or len({e["attempt_id"] for e in finished}) != len(finished)
            or {e["attempt_id"] for e in started} != set(ledger_by_id)
            or {e["attempt_id"] for e in finished} != set(ledger_by_id)
            or any(row[2] != "settled" for row in ledger_rows)
            or any(e.get("requested_model") != MODEL or e.get("status") != "completed"
                   or e.get("cost_usd") is None
                   or not math.isclose(e["cost_usd"], ledger_by_id[e["attempt_id"]][1] / SCALE, abs_tol=1e-9, rel_tol=0)
                   for e in finished)):
        raise ValueError("Unique attempt IDs, model identity or per-attempt charges differ from the ledger.")
    summary = read_json(run / "summary.json")
    inputs = sum(e["usage"]["prompt_tokens"] for e in finished)
    outputs = sum(e["usage"]["completion_tokens"] for e in finished)
    if (count != len(started) or count != len(finished) or count != summary["model_calls_made"]
            or count > 28 or current["pending_attempts"] or current["blocking_uncertain_attempts"]
            or current["exposure_nanos"] - proposal["before"]["exposure_nanos"] != cost
            or Decimal(cost) / SCALE > Decimal(str(proposal["incremental_credit_limit"]))):
        raise ValueError("Attempts, charge deltas or the branch spending ceiling do not reconcile.")
    result = {"stage": 3, "status": "first_branch_audited_remaining_development_pilot_pending",
              "pilot_measured": True, "audit_model_calls_made": 0, "user_model_attempts": count,
              "branch_index": 0, "input_tokens": inputs, "output_tokens": outputs,
              "known_credits": cost / SCALE,
              "serial_api_seconds": sum(e["latency_seconds"] for e in finished),
              "completed_decisions": summary["completed_decisions"], "first_pass_valid": summary["first_pass_valid"],
              "repair_attempts": summary["repair_attempts"], "successful_repairs": summary["successful_repairs"],
              "fallback_days": summary["fallback_days"], "post_split_contribution": summary["post_split_contribution"],
              "completed_development_branches": 1, "planned_development_branches": len(plan["episodes"]),
              "full_development_budget_proposal_credits": None,
              "next_gate": "Review measured first-branch reliability and cost before expanding the manual pilot"}
    (directory / "pilot_audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
