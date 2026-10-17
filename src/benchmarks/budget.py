"""Transactional, fail-closed allowance ledger for initially sequential paid jobs.

Limits are conditional on the verified gateway tariff and token ceilings being
honored. Unknown charges retain the full reservation and block subsequent calls.
USD-formatted gateway credit is distinct from the cash paid to buy that credit.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from .errors import BudgetStop

SCALE = Decimal(1_000_000_000)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def nanos(value) -> int:
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("Amounts must be finite and nonnegative.")
    return int((number * SCALE).to_integral_value(rounding=ROUND_CEILING))


class BudgetLedger:
    def __init__(self, manifest: dict, ledger_path: Path, *, run_id: str, scope="native"):
        self.manifest = manifest
        self.path, self.run_id, self.scope = Path(ledger_path), run_id, scope
        if manifest.get("approved") is not True or not manifest.get("approval_reference"):
            raise BudgetStop("A recorded user-approved pilot/evaluation allowance is required.")
        if manifest.get("currency") != "USD_gateway_credit":
            raise BudgetStop("The allowance must identify the gateway-credit accounting unit.")
        if manifest.get("rates_verified") is not True or not manifest.get("rates_source"):
            raise BudgetStop("Applicable gateway rates and their source must be verified before paid calls.")
        self.cap = nanos(manifest["cap_usd"])
        self.max_attempts = manifest["max_attempts"]
        if self.cap <= 0 or type(self.max_attempts) is not int or self.max_attempts <= 0:
            raise BudgetStop("Allowance and attempt limits must be positive.")
        if scope not in manifest["scope_caps_usd"]:
            raise BudgetStop("This experiment scope has no allocation.")
        self.scope_cap = nanos(manifest["scope_caps_usd"][scope])
        if sum(nanos(v) for v in manifest["scope_caps_usd"].values()) > self.cap:
            raise BudgetStop("Scope allocations exceed the total allowance.")
        if not manifest.get("rates"):
            raise BudgetStop("No applicable model rates are recorded.")
        for rate in manifest["rates"].values():
            for name in ("input_per_million", "output_per_million"):
                nanos(rate[name])
            nanos(rate.get("per_request", 0))
        self.fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS config (fingerprint TEXT NOT NULL)")
            prior = db.execute("SELECT fingerprint FROM config").fetchone()
            if prior and prior[0] != self.fingerprint:
                raise BudgetStop("This ledger belongs to another immutable allowance; do not reset spending.")
            if not prior:
                db.execute("INSERT INTO config VALUES (?)", (self.fingerprint,))
            db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY, run_id TEXT, scope TEXT, model TEXT,
                reserved_nanos INTEGER, actual_nanos INTEGER, status TEXT,
                input_bound INTEGER, output_bound INTEGER, started_at TEXT,
                finished_at TEXT, uncertainty_reason TEXT)""")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level="IMMEDIATE")
        try:
            with db:
                yield db
        finally:
            db.close()

    def cost(self, model, input_tokens, output_tokens) -> int:
        if model not in self.manifest["rates"]:
            raise BudgetStop("Requested model has no approved gateway rate.")
        rate = self.manifest["rates"][model]
        amount = ((Decimal(input_tokens) * Decimal(str(rate["input_per_million"])) +
                   Decimal(output_tokens) * Decimal(str(rate["output_per_million"]))) / Decimal(1_000_000)
                  + Decimal(str(rate.get("per_request", 0))))
        return nanos(amount)

    def reserve(self, attempt_id, model, input_bound, output_bound):
        if any(type(n) is not int or n < 0 for n in (input_bound, output_bound)):
            raise BudgetStop("Token reservation bounds must be nonnegative integers.")
        if input_bound > self.manifest["max_input_tokens_bound"]:
            raise BudgetStop("Request exceeds the approved conservative input-token envelope.")
        if output_bound > self.manifest["max_output_tokens"]:
            raise BudgetStop("Request exceeds the approved output-token ceiling.")
        reserve = self.cost(model, input_bound, output_bound)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM attempts WHERE status='uncertain' LIMIT 1").fetchone():
                raise BudgetStop("Unresolved usage/charges block further paid calls; reconcile the ledger.")
            if db.execute("SELECT 1 FROM attempts WHERE status='pending' AND run_id != ? LIMIT 1",
                          (self.run_id,)).fetchone():
                raise BudgetStop("Another run has an outstanding reservation; paid jobs are sequential.")
            charged = "CASE WHEN status='settled' THEN actual_nanos ELSE MAX(reserved_nanos,COALESCE(actual_nanos,0)) END"
            count, exposure = db.execute(f"SELECT COUNT(*), COALESCE(SUM({charged}),0) FROM attempts").fetchone()
            scoped = db.execute(f"SELECT COALESCE(SUM({charged}),0) FROM attempts WHERE scope=?",
                                (self.scope,)).fetchone()[0]
            if count >= self.max_attempts:
                raise BudgetStop("Aggregate approved attempt ceiling reached.")
            if exposure + reserve > self.cap or scoped + reserve > self.scope_cap:
                raise BudgetStop("Conservative next-call reserve cannot fit the remaining allowance/allocation.")
            db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,NULL,'pending',?,?,?,NULL,NULL)",
                       (attempt_id, self.run_id, self.scope, model, reserve, input_bound, output_bound, utc_now()))
        return reserve / float(SCALE)

    def settle(self, attempt_id, *, input_tokens=None, output_tokens=None, uncertain_reason=None):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT model,input_bound,output_bound,status FROM attempts WHERE id=?", (attempt_id,)).fetchone()
            if not row or row[3] != "pending":
                raise BudgetStop("Attempt is missing or already settled; accounting cannot be overwritten.")
            actual = None
            if (type(input_tokens) is int and input_tokens >= 0 and
                    type(output_tokens) is int and output_tokens >= 0):
                actual = self.cost(row[0], input_tokens, output_tokens)
                if input_tokens > row[1] or output_tokens > row[2]:
                    uncertain_reason = "reported_tokens_exceed_reserved_envelope"
            else:
                uncertain_reason = uncertain_reason or "missing_usage"
            db.execute("UPDATE attempts SET actual_nanos=?,status=?,finished_at=?,uncertainty_reason=? WHERE id=?",
                       (actual, "uncertain" if uncertain_reason else "settled", utc_now(), uncertain_reason, attempt_id))
        return None if actual is None else actual / float(SCALE)

    def summary(self):
        with self._connect() as db:
            rows = db.execute("SELECT status,reserved_nanos,actual_nanos FROM attempts").fetchall()
        known = sum(r[2] for r in rows if r[2] is not None)
        held = sum(max(0, r[1] - (r[2] or 0)) for r in rows if r[0] != "settled")
        return {"budget_id": self.manifest["budget_id"], "currency": self.manifest["currency"],
                "attempts": len(rows), "known_cost_usd": known / float(SCALE),
                "unresolved_reserved_usd": held / float(SCALE),
                "exposure_usd": (known + held) / float(SCALE),
                "pending_attempts": sum(r[0] == "pending" for r in rows),
                "uncertain_attempts": sum(r[0] == "uncertain" for r in rows),
                "cap_usd": self.cap / float(SCALE), "allowance_sha256": self.fingerprint,
                "cost_basis": "Token-derived uncached tariff upper estimate; provider billing is not independently verified.",
                "limit_qualification": "Conditional on applicable tariff and gateway honoring token limits; not a provider-side quota."}


def load_budget(path: Path, *, run_id, scope, base_url, purpose):
    manifest = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if manifest.get("base_url", "").rstrip("/") != base_url.rstrip("/"):
        raise BudgetStop("Budget endpoint differs from the configured credential endpoint.")
    if purpose not in manifest.get("allowed_purposes", []):
        raise BudgetStop("This allowance does not authorize the requested run purpose.")
    # The ledger location is derived from the manifest ID, never a caller-selected
    # fresh filename that could accidentally reset an existing allowance.
    budget_id = manifest.get("budget_id", "")
    if not budget_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in budget_id):
        raise BudgetStop("Budget ID must be a nonempty safe identifier.")
    from .common import ROOT
    return BudgetLedger(manifest, ROOT / "results/budgets" / f"{budget_id}.sqlite", run_id=run_id, scope=scope)
