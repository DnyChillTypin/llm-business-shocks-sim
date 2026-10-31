"""Production experiment planning, authorization, budgeting, and auditing for Report 2.

Offline only. No real model calls or unapproved credential usage.
Enforces cumulative 20-credit cap, ledger preservation, and strict authorization bindings.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

from src.research.report2 import ROOT, PROTOCOL, MANIFEST, canonical_hash, read_json

TASK = "report2:production"
MODEL = "gpt-4.1-mini-2025-04-14"
SCALE = 1_000_000_000
TIMEOUT = "api_APITimeoutError_http_unknown"
BOUNDED_FAILURES = [
    "api_APITimeoutError_http_unknown",
    "api_CancelledError_http_unknown",
    "api_InternalServerError_http_503",
    "process_interrupted_gateway_outcome_unknown",
]
PRODUCTION_SOURCES = (
    "src/research/report2_production.py",
    "src/experiments/report2_production.py",
    "scripts/run_report2_production.py",
    "tests/test_report2_production.py",
)


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def code_hashes(root=ROOT) -> dict[str, str]:
    return {p: hashlib.sha256((root / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for p in PRODUCTION_SOURCES if (root / p).exists()}


def file_hashes(directory: Path) -> dict[str, str]:
    directory = Path(directory)
    if not directory.exists():
        return {}
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*")) if p.is_file()}


def connect_readonly(path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def ledger_state(db: sqlite3.Connection) -> dict:
    attempts = db.execute("SELECT * FROM attempts ORDER BY id").fetchall()
    holds = db.execute("SELECT * FROM bounded_holds ORDER BY attempt_id").fetchall()
    charged = "CASE WHEN status='settled' THEN actual_nanos ELSE MAX(reserved_nanos,COALESCE(actual_nanos,0)) END"
    count, exposure, pending, blocking = db.execute(
        f"SELECT COUNT(*),COALESCE(SUM({charged}),0),COALESCE(SUM(status='pending'),0),"
        "COALESCE(SUM(status='uncertain' AND id NOT IN (SELECT attempt_id FROM bounded_holds)),0) FROM attempts"
    ).fetchone()
    scopes = {r[0]: r[1] for r in db.execute(f"SELECT scope,COALESCE(SUM({charged}),0) FROM attempts GROUP BY scope")}
    return {
        "attempts": count,
        "exposure_nanos": exposure,
        "scope_exposure_nanos": scopes,
        "pending_attempts": pending,
        "blocking_uncertain_attempts": blocking,
        "attempts_sha256": canonical_hash({"rows": attempts}),
        "holds_sha256": canonical_hash({"rows": holds}),
        "retained_holds": len(holds),
    }


def read_ledger(path: str | Path):
    with closing(connect_readonly(path)) as db:
        rows = db.execute("SELECT * FROM attempts ORDER BY id").fetchall()
        holds = db.execute("SELECT * FROM bounded_holds ORDER BY attempt_id").fetchall()
        fields = [r[1] for r in db.execute("PRAGMA table_info(attempts)")]
        row_dicts = [dict(zip(fields, r)) for r in rows]
        hold_lists = [list(h) for h in holds]
        cfg = db.execute("SELECT fingerprint FROM config").fetchone()
        fp = cfg[0] if cfg else ""
        return fp, ledger_state(db), row_dicts, hold_lists


def current_allowance(path: str | Path) -> tuple[dict, dict]:
    with closing(connect_readonly(path)) as db:
        row = db.execute("SELECT new_manifest FROM allowance_amendments ORDER BY rowid DESC LIMIT 1").fetchone()
        if row is None:
            raise ValueError("No journaled cumulative allowance is available; do not create a replacement ledger.")
        allowance = json.loads(row[0])
        cfg = db.execute("SELECT fingerprint FROM config").fetchone()
        if cfg is None or cfg[0] != fingerprint(allowance):
            raise ValueError("Latest allowance does not match the existing ledger fingerprint.")
        state = ledger_state(db)
    if state["pending_attempts"] or state["blocking_uncertain_attempts"]:
        raise ValueError("Pending or unresolved unbounded charges block preparation.")
    return allowance, state


def validate_snapshot(snapshot: dict, allowance: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if (snapshot.get("provider") != "ShopAIKey"
            or snapshot.get("base_url") != "https://api.shopaikey.com/v1"
            or snapshot.get("rates_verified") is not True
            or snapshot.get("missing_models")
            or snapshot.get("paid_api_calls") != 0):
        raise ValueError("A successful read-only configured-gateway snapshot is required.")
    checked = datetime.fromisoformat(snapshot["checked_at_utc"])
    if checked.tzinfo is None or not timedelta(0) <= now - checked <= timedelta(hours=24):
        raise ValueError("Gateway snapshot must be timezone-aware, recent within 24 hours, and not future-dated.")
    precision = Decimal("0.000000000001")
    for model, old in allowance.get("rates", {}).items():
        fresh = snapshot["rates"].get(model)
        if fresh is None:
            raise ValueError("An existing allowed model is missing from current applicable tariffs.")
        for field in ("input_per_million", "output_per_million", "per_request"):
            a, b = Decimal(str(old.get(field, 0))), Decimal(str(fresh.get(field, 0)))
            if not a.is_finite() or not b.is_finite() or b < 0 or a.quantize(precision) != b.quantize(precision):
                raise ValueError("Tariffs changed; a separate reviewed rate migration is required.")
    return {**snapshot["rates"][MODEL], "per_request": snapshot["rates"][MODEL].get("per_request", 0)}


def production_plan(cohort: str = "main", root: Path = ROOT) -> dict:
    """Generate canonical production evaluation plans deterministically."""
    if cohort not in {"main", "history", "elasticity", "all"}:
        raise ValueError(f"Unknown production cohort: {cohort}")
    protocol = read_json(root / PROTOCOL)
    sampling = read_json(root / MANIFEST)
    conditions = protocol["branching"]["conditions"]
    realizations = list(range(protocol["sampling"]["repeated_llm_realizations"]))

    episodes = []
    blocks = sampling["evaluation_blocks"]

    # 1. Main cohort: 36 blocks x 4 conditions x 3 realizations = 432 branches
    # history = "full", elasticity = 1.5
    if cohort in {"main", "all"}:
        for block in blocks:
            for scenario in conditions:
                for r in realizations:
                    episodes.append({
                        "cohort": "main",
                        "block_id": block["block_id"],
                        "store_id": block["store_id"],
                        "product_id": block["product_id"],
                        "window_id": block["window_id"],
                        "scenario": scenario,
                        "history": "full",
                        "elasticity": 1.5,
                        "realization": r,
                        "policy": "llm_with_fallback",
                    })

    # 2. History cohort: 18 diagnostic blocks x 4 conditions x 2 additional histories x 3 realizations = 432 branches
    # history in ["frozen", "none"], elasticity = 1.5
    if cohort in {"history", "all"}:
        diag_blocks = [b for b in blocks if b["diagnostic_subset"]]
        for block in diag_blocks:
            for scenario in conditions:
                for h in ["frozen", "none"]:
                    for r in realizations:
                        episodes.append({
                            "cohort": "history",
                            "block_id": block["block_id"],
                            "store_id": block["store_id"],
                            "product_id": block["product_id"],
                            "window_id": block["window_id"],
                            "scenario": scenario,
                            "history": h,
                            "elasticity": 1.5,
                            "realization": r,
                            "policy": "llm_with_fallback",
                        })

    # 3. Elasticity cohort: 18 diagnostic blocks x 4 conditions x 2 additional elasticities x 3 realizations = 432 branches
    # elasticity in [0.75, 2.25], history = "full"
    if cohort in {"elasticity", "all"}:
        diag_blocks = [b for b in blocks if b["diagnostic_subset"]]
        for e in [0.75, 2.25]:
            for block in diag_blocks:
                for scenario in conditions:
                    for r in realizations:
                        episodes.append({
                            "cohort": "elasticity",
                            "block_id": block["block_id"],
                            "store_id": block["store_id"],
                            "product_id": block["product_id"],
                            "window_id": block["window_id"],
                            "scenario": scenario,
                            "history": "full",
                            "elasticity": e,
                            "realization": r,
                            "policy": "llm_with_fallback",
                        })

    return {
        "study_id": protocol["study_id"],
        "task_id": TASK,
        "cohort": cohort,
        "sampling_sha256": sampling["manifest_sha256"],
        "model": protocol["model"]["requested_id"],
        "episodes": episodes,
        "decisions": len(episodes) * 14,
        "max_attempts": len(episodes) * 28,
        "approved": False,
        "model_execution": "user_manually_only",
    }


def baseline_plan(cohort: str = "all", root: Path = ROOT) -> dict:
    """Generate canonical deterministic baseline evaluation plans.

    Main: 36 blocks x 4 conditions x 2 policies ('adaptive', 'fixed') = 288 branches.
    Elasticity: 18 diagnostic blocks x 4 conditions x 2 elasticities (0.75, 2.25) x 2 policies = 288 branches.
    Total: 576 baseline branches.
    """
    if cohort not in {"main", "elasticity", "all"}:
        raise ValueError(f"Unknown baseline cohort: {cohort}")
    protocol = read_json(root / PROTOCOL)
    sampling = read_json(root / MANIFEST)
    conditions = protocol["branching"]["conditions"]
    policies = ["adaptive", "fixed"]

    episodes = []
    blocks = sampling["evaluation_blocks"]

    if cohort in {"main", "all"}:
        for block in blocks:
            for scenario in conditions:
                for policy in policies:
                    episodes.append({
                        "cohort": "baseline_main",
                        "block_id": block["block_id"],
                        "store_id": block["store_id"],
                        "product_id": block["product_id"],
                        "window_id": block["window_id"],
                        "scenario": scenario,
                        "history": "full",
                        "elasticity": 1.5,
                        "realization": 0,
                        "policy": policy,
                    })

    if cohort in {"elasticity", "all"}:
        diag_blocks = [b for b in blocks if b["diagnostic_subset"]]
        for e in [0.75, 2.25]:
            for block in diag_blocks:
                for scenario in conditions:
                    for policy in policies:
                        episodes.append({
                            "cohort": "baseline_elasticity",
                            "block_id": block["block_id"],
                            "store_id": block["store_id"],
                            "product_id": block["product_id"],
                            "window_id": block["window_id"],
                            "scenario": scenario,
                            "history": "full",
                            "elasticity": e,
                            "realization": 0,
                            "policy": policy,
                        })

    return {
        "study_id": protocol["study_id"],
        "task_id": "report2:baselines",
        "cohort": cohort,
        "sampling_sha256": sampling["manifest_sha256"],
        "episodes": episodes,
        "decisions": len(episodes) * 14,
        "max_attempts": 0,
        "approved": True,
        "model_execution": "none_deterministic_only",
    }


def episode_identity(plan: dict, episode: dict) -> str:
    """Canonical unique run identifier for a production episode."""
    return canonical_hash({"plan": canonical_hash({k: plan[k] for k in ("study_id", "task_id", "cohort", "sampling_sha256")}),
                           "episode": episode})


def authorization_template(plan: dict, allowed_indices: list[int] | None = None) -> dict:
    indices = allowed_indices if allowed_indices is not None else list(range(len(plan["episodes"])))
    return {
        "approved": False,
        "execution_mode": "user_manually_only",
        "plan_sha256": canonical_hash(plan),
        "allowed_branch_indices": indices,
        "max_decisions": 14 * len(indices),
        "max_attempts": 28 * len(indices),
        "budget_sha256": None,
        "approval_reference": None,
        "qualification": f"Manual production execution for {plan['cohort']} cohort ({len(indices)} branches).",
    }


def validate_authorization(auth: dict, budget: dict, plan: dict, index: int | None = None) -> None:
    if (auth.get("approved") is not True or auth.get("execution_mode") != "user_manually_only"
            or not auth.get("approval_reference") or auth.get("plan_sha256") != canonical_hash(plan)):
        raise ValueError("A reviewed manual production authorization bound to the current plan is required.")
    indices = auth.get("allowed_branch_indices", [])
    if (not indices or any(type(i) is not int or not 0 <= i < len(plan["episodes"]) for i in indices)
            or len(set(indices)) != len(indices)
            or (index is not None and index not in indices)
            or auth.get("max_decisions") != 14 * len(indices)
            or auth.get("max_attempts") != 28 * len(indices)):
        raise ValueError("Production branch subset or decision/attempt ceiling differs from authorization.")
    if (budget.get("approved") is not True or auth.get("budget_sha256") != fingerprint(budget)
            or plan["task_id"] not in budget.get("allowed_tasks", [])
            or "evaluation" not in budget.get("allowed_purposes", [])
            or budget.get("rates_verified") is not True or not budget.get("rates_source")
            or budget.get("rates_verified_at_utc", "")[:10] < "2026-10-31"):
        raise ValueError("The bound cumulative allowance must authorize this production task and verified rates.")
    if (budget.get("cap_usd", 0) <= 0 or budget.get("scope_caps_usd", {}).get("kaggle", 0) <= 0
            or MODEL not in budget.get("rates", {})):
        raise ValueError("A positive monetary allocation and explicit model tariff are required.")


def validate_transition(old: dict, new: dict, before: dict, credit_limit: float | Decimal) -> None:
    allowed_changes = {"max_attempts", "scope_caps_usd", "approval_reference", "approved_at_utc",
                       "rates_source", "rates_verified_at_utc", "pricing_version", "qualification",
                       "allowed_tasks"}
    if any(old.get(k) != new.get(k) for k in set(old) | set(new) if k not in allowed_changes):
        raise ValueError("Production activation cannot change identity, global cap, tariff values or unapproved fields.")
    limit = Decimal(str(credit_limit))
    if not limit.is_finite() or limit <= 0:
        raise ValueError("Incremental credit limit must be positive.")
    if new.get("approved") is not True or not new.get("approval_reference") or new["approval_reference"] == old.get("approval_reference"):
        raise ValueError("Manual activation requires a distinct explicit approval reference.")
    if TASK not in new.get("allowed_tasks", []):
        raise ValueError("Production task must be added to allowed_tasks.")
    expected_scope = Decimal(before["scope_exposure_nanos"].get("kaggle", 0)) / SCALE + limit
    if Decimal(str(new["scope_caps_usd"]["kaggle"])) != expected_scope:
        raise ValueError("Kaggle scope cap must equal prior Kaggle exposure plus approved incremental limit.")
    if sum(Decimal(str(v)) for v in new["scope_caps_usd"].values()) > Decimal(str(old["cap_usd"])):
        raise ValueError("Sum of scope caps exceeds the unchanged cumulative 20-credit cap.")


def build_production_proposal(snapshot: dict, ledger_path: str | Path, cohort: str = "main",
                              *, incremental_credit_limit: float = 6.0, root: Path = ROOT) -> dict:
    """Build an unactivated proposal for production model execution."""
    ledger_path = Path(ledger_path).resolve()
    old, before = current_allowance(ledger_path)
    expected_name = f"{old['budget_id']}.sqlite"
    if ledger_path.name != expected_name:
        raise ValueError("Use the existing ledger path derived from its unchanged budget identity.")
    rate = validate_snapshot(snapshot, old)
    plan = production_plan(cohort, root)
    limit = Decimal(str(incremental_credit_limit))
    if not limit.is_finite() or limit <= 0 or limit > Decimal("17.55"):
        raise ValueError(f"Incremental limit {incremental_credit_limit} exceeds available headroom or is invalid.")

    # Check that prior Kaggle exposure + limit does not exceed global cap remaining
    prior_kaggle = Decimal(before["scope_exposure_nanos"].get("kaggle", 0)) / SCALE
    new_kaggle_cap = float(prior_kaggle + limit)
    other_scopes = sum(Decimal(str(v)) for k, v in old["scope_caps_usd"].items() if k != "kaggle")
    if prior_kaggle + limit + other_scopes > Decimal(str(old["cap_usd"])):
        raise ValueError("Proposed allocation exceeds global 20-credit cap.")

    new = copy.deepcopy(old)
    new.update(
        approval_reference="manual activation pending; not an approval",
        approved_at_utc=None,
        rates_source="https://api.shopaikey.com/pricing",
        rates_verified_at_utc=snapshot["checked_at_utc"],
        pricing_version=snapshot["pricing_version"],
        max_attempts=before["attempts"] + plan["max_attempts"],
        qualification=f"Production {cohort} cohort execution ({len(plan['episodes'])} branches); historical charges and holds retained.",
    )
    if TASK not in new["allowed_tasks"]:
        new["allowed_tasks"] = list(dict.fromkeys([*old["allowed_tasks"], TASK]))
    new["scope_caps_usd"]["kaggle"] = new_kaggle_cap
    validate_transition(old, new, before, incremental_credit_limit)

    rel_ledger = ledger_path.relative_to(root.resolve()).as_posix() if ledger_path.is_relative_to(root.resolve()) else str(ledger_path)
    proposal = {
        "schema_version": 1,
        "stage": "4_production",
        "cohort": cohort,
        "status": "prepared_awaiting_manual_activation_and_model_run",
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_calls_made": 0,
        "plan_sha256": canonical_hash(plan),
        "sampling_sha256": plan["sampling_sha256"],
        "source_sha256": code_hashes(root),
        "gateway_snapshot_sha256": canonical_hash(snapshot),
        "ledger_relative_path": rel_ledger,
        "before": before,
        "old_allowance_sha256": fingerprint(old),
        "old_allowance": old,
        "prospective_allowance": new,
        "incremental_credit_limit": incremental_credit_limit,
        "allowed_branch_indices": list(range(len(plan["episodes"]))),
        "planned_branches": len(plan["episodes"]),
        "planned_decisions": plan["decisions"],
        "next_gate": f"User manually activates the exact cap and executes {cohort} cohort in separate processes",
    }
    proposal["proposal_sha256"] = canonical_hash(proposal)
    return proposal


def verify_production_proposal(proposal: dict, snapshot: dict, root: Path = ROOT,
                               *, require_unmodified_ledger: bool = True,
                               require_fresh_snapshot: bool = True) -> None:
    expected_hash = canonical_hash({k: v for k, v in proposal.items() if k != "proposal_sha256"})
    if proposal["proposal_sha256"] != expected_hash:
        raise ValueError("Proposal checksum mismatch.")
    plan = production_plan(proposal["cohort"], root)
    if proposal["plan_sha256"] != canonical_hash(plan):
        raise ValueError("Canonical plan changed.")
    if canonical_hash(snapshot) != proposal["gateway_snapshot_sha256"]:
        raise ValueError("Snapshot changed.")
    validate_snapshot(snapshot, proposal["old_allowance"],
                      now=None if require_fresh_snapshot else datetime.fromisoformat(snapshot["checked_at_utc"]))
    if require_unmodified_ledger:
        rel = Path(proposal["ledger_relative_path"])
        ledger_path = rel if rel.is_absolute() else root / rel
        old, state = current_allowance(ledger_path)
        if fingerprint(old) != proposal["old_allowance_sha256"] or state != proposal["before"]:
            raise ValueError("Cumulative ledger changed after proposal creation; prepare a fresh handoff.")


def activate_production(proposal: dict, snapshot: dict, directory: Path,
                        approve_credit_limit: float | Decimal, root: Path = ROOT) -> dict:
    """Manual-only activation. Backs up ledger, journals amendment, and generates authorized budget/auth."""
    verify_production_proposal(proposal, snapshot, root)
    if Decimal(str(approve_credit_limit)) != Decimal(str(proposal["incremental_credit_limit"])):
        raise ValueError("Approved credit limit differs from the proposal.")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rel = Path(proposal["ledger_relative_path"])
    ledger_path = rel if rel.is_absolute() else root / rel
    backup = directory / "ledger_before_activation.sqlite"
    if backup.exists() or (directory / "approved_budget.json").exists() or (directory / "approved_authorization.json").exists():
        raise ValueError("Activation artifacts already exist; inspect prior activation rather than overwrite.")

    with closing(connect_readonly(ledger_path)) as src, closing(sqlite3.connect(backup)) as dst:
        src.backup(dst)

    now = datetime.now(timezone.utc).isoformat()
    new = copy.deepcopy(proposal["prospective_allowance"])
    new.update(
        approved=True,
        approval_reference=f"User manually activated report2 {proposal['cohort']} cohort with {approve_credit_limit} credit limit at {now}",
        approved_at_utc=now,
    )
    validate_transition(proposal["old_allowance"], new, proposal["before"], approve_credit_limit)

    plan = production_plan(proposal["cohort"], root)
    auth = authorization_template(plan, proposal["allowed_branch_indices"])
    auth.update(approved=True, approval_reference=new["approval_reference"], budget_sha256=fingerprint(new))

    with closing(sqlite3.connect(ledger_path)) as db:
        with db:
            db.execute("BEGIN IMMEDIATE")
            cur_fp = db.execute("SELECT fingerprint FROM config").fetchone()[0]
            if cur_fp != proposal["old_allowance_sha256"] or ledger_state(db) != proposal["before"]:
                raise ValueError("Ledger state changed during activation; transaction rolled back.")
            db.execute("INSERT INTO allowance_amendments VALUES (?,?,?)",
                       (now, json.dumps(proposal["old_allowance"]), json.dumps(new)))
            db.execute("UPDATE config SET fingerprint=?", (fingerprint(new),))
            if ledger_state(db)["attempts_sha256"] != proposal["before"]["attempts_sha256"]:
                raise ValueError("Attempts changed during amendment; transaction rolled back.")

    receipt = {
        "status": "production_activated_awaiting_manual_models",
        "cohort": proposal["cohort"],
        "model_calls_made": 0,
        "proposal_sha256": proposal["proposal_sha256"],
        "budget_sha256": fingerprint(new),
        "authorization_sha256": canonical_hash(auth),
        "activated_at_utc": now,
        "incremental_credit_limit": float(approve_credit_limit),
        "max_attempts": new["max_attempts"],
    }
    (directory / "approved_budget.json").write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
    (directory / "approved_authorization.json").write_text(json.dumps(auth, indent=2) + "\n", encoding="utf-8")
    (directory / "activation_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def json_lines(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def reconcile_production_requests(directory: Path, rows: list[dict], run_id: str, *, complete: bool = True) -> dict:
    """Reconcile unique physical attempt events against SQLite ledger rows."""
    attempt_path = Path(directory) / "api_attempts.jsonl"
    if not attempt_path.exists():
        return {"model_attempts": 0, "known_credits": 0.0, "unknown_charge_reserved_credits": 0.0,
                "serial_api_seconds": 0.0, "failed_requests": []}
    events = json_lines(attempt_path)
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
                       or e.get("purpose") != "evaluation" for e in (begin, event))
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


def audit_production(batch_dir: Path, ledger_path: Path, cohort: str = "main",
                     output_dir: Path | None = None, root: Path = ROOT) -> dict:
    """Offline completeness audit and reconciliation for a production batch."""
    import shutil
    from src.experiments.report2 import validate_branch
    from src.experiments.report2_production import get_evaluation_block, prepare_production_case, get_or_create_prefix

    batch_dir = Path(batch_dir)
    plan = production_plan(cohort, root)
    output = Path(output_dir) if output_dir is not None else batch_dir / ("audit_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    output.mkdir(parents=True, exist_ok=True)

    _, state, rows, _ = read_ledger(ledger_path)
    known = {episode_identity(plan, ep): (i, ep) for i, ep in enumerate(plan["episodes"])}
    claims_dir = batch_dir / "claims"
    claims = {}
    if claims_dir.exists():
        for p in claims_dir.glob("*.json"):
            if p.stem in known:
                claims[p.stem] = p

    records = []
    for key, claim_file in sorted(claims.items(), key=lambda x: known[x[0]][0]):
        index, episode = known[key]
        claim_data = read_json(claim_file)
        if claim_data.get("status") != "validated_complete":
            continue
        run_dir = batch_dir / "branches" / key
        block = get_evaluation_block(episode["block_id"], root)
        prepared = prepare_production_case(block, episode["elasticity"], batch_dir=batch_dir, root=root)
        prefix = get_or_create_prefix(block, episode["elasticity"], batch_dir=batch_dir, root=root)

        copied = output / "validation_copies" / key
        shutil.copytree(run_dir, copied)
        validate_branch(prepared, prefix, copied, output / "replays" / key)

        summary = read_json(run_dir / "summary.json")
        paid = [r for r in rows if r["run_id"] == key]
        accounting = reconcile_production_requests(batch_dir / "requests" / key, paid, key, complete=True)
        records.append({
            "branch_index": index,
            "identity": key,
            **episode,
            **accounting,
            **{k: summary[k] for k in ("completed_decisions", "first_pass_valid", "repair_attempts",
                                       "successful_repairs", "fallback_days", "post_split_contribution", "fill_rate")},
        })

    totals = {k: sum(r[k] for r in records) for k in ("completed_decisions", "model_attempts", "known_credits",
              "serial_api_seconds", "first_pass_valid", "repair_attempts", "successful_repairs", "fallback_days")}

    result = {
        "status": "production_audited_complete" if len(records) == len(plan["episodes"]) else "production_audited_incomplete",
        "cohort": cohort,
        "completed_branches": len(records),
        "planned_branches": len(plan["episodes"]),
        "totals": totals,
        "project_exposure_credits": state["exposure_nanos"] / SCALE,
        "remaining_project_credits": 20.0 - state["exposure_nanos"] / SCALE,
        "branches": records,
    }
    (output / "production_audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (batch_dir / "production_audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def prepare_production_recovery(batch_dir: Path, handoff_dir: Path, snapshot: dict,
                                *, cohort: str = "main", ledger_path: str | Path | None = None,
                                root: Path = ROOT) -> dict:
    """Inspect interrupted production branch and prepare a reviewed recovery proposal."""
    batch_dir, handoff_dir = Path(batch_dir), Path(handoff_dir)
    handoff_dir.mkdir(parents=True, exist_ok=False)
    plan = production_plan(cohort, root)
    known = {episode_identity(plan, ep): (i, ep) for i, ep in enumerate(plan["episodes"])}

    claims_dir = batch_dir / "claims"
    if not claims_dir.exists():
        raise ValueError("No claims directory found in batch.")

    interrupted_key = None
    interrupted_index = None
    for claim_path in sorted(claims_dir.glob("*.json")):
        claim = read_json(claim_path)
        if claim.get("status") != "validated_complete":
            interrupted_key = claim_path.stem
            interrupted_index = known[interrupted_key][0]
            break

    if interrupted_key is None:
        raise ValueError("No interrupted or incomplete claim found in batch.")

    if ledger_path is None:
        budget_file = handoff_dir.parent / "approved_budget.json"
        if not budget_file.exists():
            budget_file = root / "results/report2/milestone3/recovery2_final/approved_budget.json"
        budget = read_json(budget_file) if budget_file.exists() else current_allowance(root / "results/budgets/stage2_pilot_v1.sqlite")[0]
        ledger_path = root / "results/budgets" / f"{budget['budget_id']}.sqlite"
    else:
        ledger_path = Path(ledger_path)
        budget = current_allowance(ledger_path)[0]

    fp, state, rows, holds = read_ledger(ledger_path)

    req_dir = batch_dir / "requests" / interrupted_key
    paid = [r for r in rows if r["run_id"] == interrupted_key]
    accounting = reconcile_production_requests(req_dir, paid, interrupted_key, complete=False) if (req_dir / "api_attempts.jsonl").exists() else {"failed_requests": [], "unknown_charge_reserved_credits": 0.0, "model_attempts": 0, "known_credits": 0.0}

    failed = accounting.get("failed_requests", [])
    if failed:
        uncertain_attempt = next((r for r in rows if r["id"] == failed[0]["attempt_id"]), None)
        held_credits = uncertain_attempt["reserved_nanos"] / SCALE if uncertain_attempt else 0.0
    else:
        uncertain_attempt = None
        held_credits = 0.0

    proposal = {
        "schema_version": 1,
        "stage": "4_production_recovery",
        "cohort": cohort,
        "status": "ready_for_user_manual_recovery",
        "interrupted_index": interrupted_index,
        "interrupted_identity": interrupted_key,
        "failed_attempt": uncertain_attempt,
        "held_credits": held_credits,
        "accounting": accounting,
        "canonical_artifact_sha256": file_hashes(batch_dir),
        "source_sha256": code_hashes(root),
        "before": state,
        "old_budget": budget,
        "ledger_relative_path": ledger_path.relative_to(root.resolve()).as_posix() if ledger_path.is_relative_to(root.resolve()) else str(ledger_path),
        "recovery_branch_indices": list(range(interrupted_index, len(plan["episodes"]))),
    }
    proposal["proposal_sha256"] = canonical_hash(proposal)
    (handoff_dir / "recovery_proposal.json").write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")
    return proposal


def activate_production_recovery(proposal: dict, handoff_dir: Path, batch_dir: Path,
                                 approve_held_credits: float | str, root: Path = ROOT) -> dict:
    """Activate production recovery: move interrupted evidence to archive, record hold in ledger."""
    handoff_dir, batch_dir = Path(handoff_dir), Path(batch_dir)
    archive = handoff_dir / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    key = proposal["interrupted_identity"]

    now = datetime.now(timezone.utc).isoformat()
    rel = Path(proposal["ledger_relative_path"])
    ledger_path = rel if rel.is_absolute() else root / rel

    with closing(connect_readonly(ledger_path)) as src, closing(sqlite3.connect(handoff_dir / "ledger_before_recovery.sqlite")) as dst:
        src.backup(dst)

    if proposal.get("failed_attempt"):
        hold = [
            proposal["failed_attempt"]["id"],
            f"User manual reviewed production restart; retain full reserve at {now}",
            now,
            "Reviewed production timeout: retain entire reservation with no fabricated tokens or zero charge.",
        ]
        with closing(sqlite3.connect(ledger_path)) as db:
            with db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO bounded_holds VALUES (?,?,?,?)", hold)

    for item in [f"branches/{key}", f"requests/{key}", f"claims/{key}.json"]:
        src = batch_dir / item
        if src.exists():
            dst = archive / item
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    receipt = {
        "status": "production_recovery_activated",
        "cohort": proposal["cohort"],
        "interrupted_index": proposal["interrupted_index"],
        "interrupted_identity": key,
        "activated_at_utc": now,
        "approved_held_credits": float(approve_held_credits),
    }
    (handoff_dir / "recovery_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt

