"""Manual development-pilot handoff. Default planning never reads credentials or calls a model."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def budget_hash(budget):
    # Match the cumulative ledger's exact allowance fingerprint convention.
    return hashlib.sha256(json.dumps(budget, sort_keys=True).encode()).hexdigest()


def authorization_template(plan):
    from src.research.report2 import canonical_hash
    return {"approved": False, "execution_mode": "user_manually_only",
            "plan_sha256": canonical_hash(plan), "allowed_branch_indices": [0],
            "max_decisions": 14, "max_attempts": 28, "budget_sha256": None,
            "approval_reference": None,
            "qualification": "First development branch only; verify current tariffs and a monetary cap before manual execution"}


def validate_authorization(auth, budget, plan, index):
    from src.research.report2 import canonical_hash
    if (auth.get("approved") is not True or auth.get("execution_mode") != "user_manually_only"
            or not auth.get("approval_reference") or auth.get("plan_sha256") != canonical_hash(plan)):
        raise ValueError("A reviewed manual pilot authorization bound to the current plan is required.")
    indices = auth.get("allowed_branch_indices", [])
    if (not indices or any(type(i) is not int or not 0 <= i < len(plan["episodes"]) for i in indices)
            or len(set(indices)) != len(indices) or index not in indices
            or auth.get("max_decisions") != 14 * len(indices) or auth.get("max_attempts") != 28 * len(indices)):
        raise ValueError("Pilot branch subset or decision/attempt ceiling differs from its authorization.")
    if (budget.get("approved") is not True or auth.get("budget_sha256") != budget_hash(budget)
            or plan["task_id"] not in budget.get("allowed_tasks", [])
            or "pilot" not in budget.get("allowed_purposes", [])
            or budget.get("rates_verified") is not True or not budget.get("rates_source")
            or budget.get("rates_verified_at_utc", "")[:10] < "2026-10-31"):
        raise ValueError("The bound cumulative allowance must authorize this task and current verified rates.")
    if (budget.get("cap_usd", 0) <= 0 or budget.get("scope_caps_usd", {}).get("kaggle", 0) <= 0
            or "gpt-4.1-mini-2025-04-14" not in budget.get("rates", {})):
        raise ValueError("A positive monetary allocation and explicit model tariff are required.")


def check_prior_claim(batch, path):
    from src.experiments.report2 import evidence_hashes
    from src.research.report2 import read_json
    saved = read_json(path)
    if saved.get("status") != "validated_complete":
        raise ValueError("An incomplete or interrupted claimed branch needs evidence review; automatic paid retry is blocked.")
    run = batch / "branches" / path.stem
    requests = batch / "requests" / path.stem
    request_hashes = {p.relative_to(requests).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in requests.rglob("*") if p.is_file()}
    if (saved["evidence_sha256"] != evidence_hashes(run)
            or saved["request_artifact_sha256"] != request_hashes
            or read_json(run / "run_manifest.json")["status"] != "validated_complete"):
        raise ValueError("Previously completed branch evidence changed; review before further paid calls.")


def main():
    from src.research.report2 import PROTOCOL, canonical_hash, read_json
    from src.research.report2_runtime import verify_implementation
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--write-handoff", type=Path, help="Fresh local directory under results/report2.")
    mode.add_argument("--execute-model", action="store_true", help="For the user to run manually AFTER review and a budget handoff.")
    parser.add_argument("--branch-index", type=int)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--budget", type=Path)
    args = parser.parse_args()
    verify_implementation(ROOT)
    from src.experiments.report2 import development_plan
    plan = development_plan(ROOT)
    if args.plan or args.write_handoff:
        if args.authorization or args.budget or args.branch_index is not None:
            parser.error("Planning does not accept execution inputs.")
        if args.write_handoff:
            folder = args.write_handoff.resolve()
            if not folder.is_relative_to(ROOT / "results/report2"):
                parser.error("Handoffs must stay under ignored results/report2.")
            folder.mkdir(parents=True, exist_ok=False)
            (folder / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            (folder / "authorization.template.json").write_text(json.dumps(authorization_template(plan), indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"model_calls_made": 0, "plan": plan}, indent=2))
        return 0
    if args.branch_index is None or not args.authorization or not args.budget:
        parser.error("Manual execution requires --branch-index, --authorization and --budget.")
    auth, allowance = read_json(args.authorization), read_json(args.budget)
    validate_authorization(auth, allowance, plan, args.branch_index)
    # Everything above is offline. Authorization errors occur before credentials.
    from src.experiments.kaggle_protocol import execution_lock, require_existing_ledger, write
    require_existing_ledger(allowance)
    protocol = read_json(ROOT / PROTOCOL)
    batch = ROOT / "results/report2/manual_development"
    batch.mkdir(parents=True, exist_ok=True)
    with execution_lock(batch):
        registry = batch / "plan.json"
        if registry.exists() and read_json(registry) != plan:
            raise ValueError("Manual batch plan changed; do not replace an existing cohort.")
        if not registry.exists():
            write(registry, plan)
        for claim in (batch / "claims").glob("*.json") if (batch / "claims").exists() else []:
            check_prior_claim(batch, claim)
        episode = plan["episodes"][args.branch_index]
        identity = canonical_hash({"plan": canonical_hash(plan), "episode": episode})
        claim_path = batch / "claims" / f"{identity}.json"
        if claim_path.exists():
            raise ValueError("This logical branch already ran; validate its saved evidence instead of reissuing model calls.")
        from src.experiments.report2_fixtures import prepare_case
        from src.experiments.report2 import create_prefix, run_branch, validate_branch, evidence_hashes
        case = next(c for c in protocol["sampling"]["development_cases"] if c["id"] == episode["case_id"])
        group = batch / "cases" / case["id"]
        prepared = group / "prepared/inputs"
        if not prepared.exists():
            prepared = prepare_case(case, group / "prepared")
        prefix_path = group / "warmup/prefix.json"
        prefix = read_json(prefix_path) if prefix_path.exists() else create_prefix(prepared, group / "warmup")
        attempts = sum(json.loads(line).get("event") == "started"
                       for path in (batch / "requests").glob("*/api_attempts.jsonl")
                       for line in path.read_text().splitlines()) if (batch / "requests").exists() else 0
        if attempts + 28 > auth["max_attempts"]:
            raise ValueError("Too few authorized attempt slots remain for another complete branch.")
        claim_path.parent.mkdir(exist_ok=True)
        claim = {"status": "claimed_before_client_creation", "episode": episode,
                 "authorization_sha256": canonical_hash(auth), "budget_sha256": budget_hash(allowance)}
        with claim_path.open("x", encoding="utf-8") as stream:
            json.dump(claim, stream, indent=2)
        run = batch / "branches" / identity
        request_dir = batch / "requests" / identity
        ledger, counts = None, None
        try:
            from src.benchmarks.common import credentials, settings, install_gateway_clients
            from src.benchmarks.budget import load_budget
            from src.agents.llm import LLMPolicy
            _, base = credentials()
            ledger = load_budget(args.budget, run_id=identity, scope="kaggle", base_url=base, purpose="pilot")
            config = {**settings(), "max_output_tokens": protocol["model"]["max_output_tokens"],
                      "max_api_calls_per_task": 28, "_purpose": "pilot", "_run_id": identity,
                      "_request_context": {"task_id": plan["task_id"], "episode_id": identity}}
            counts = install_gateway_clients(request_dir, config, budget=ledger)
            import openai
            with openai.OpenAI() as client:
                run_branch(prepared, prefix, run, scenario=episode["scenario"], history=episode["history"],
                           policy="llm_with_fallback", realization=0,
                           decide=LLMPolicy(client, protocol["model"]), manual_model_execution=True)
            summary = read_json(run / "summary.json")
            summary["model_calls_made"] = counts["attempts"]
            write(run / "summary.json", summary)
            manifest = read_json(run / "run_manifest.json")
            manifest["evidence_sha256"] = evidence_hashes(run)
            write(run / "run_manifest.json", manifest)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            validate_branch(prepared, prefix, run, batch / "replays" / f"{identity}_{stamp}")
            claim["status"] = "validated_complete"
            claim["evidence_sha256"] = evidence_hashes(run)
            print(json.dumps({"status": "validated_complete", "branch_index": args.branch_index,
                              "next_gate": "Inspect reliability, request costs and latency before another manual branch"}, indent=2))
        finally:
            if ledger:
                write(request_dir / "budget_summary.json", ledger.summary())
            if counts is not None:
                write(request_dir / "usage_totals.json", counts)
            if claim["status"] == "validated_complete":
                claim["request_artifact_sha256"] = {p.relative_to(request_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                                    for p in request_dir.rglob("*") if p.is_file()}
            write(claim_path, claim)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
