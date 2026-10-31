"""Production experiment execution engine for Report 2.

Handles case preparation, immutable prefix caching, deterministic baseline execution (576 branches),
and isolated subprocess model branch execution with durable claims and budget reconciliation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from src.data.kaggle import prepare_dataset
from src.experiments.kaggle_protocol import execution_lock, require_existing_ledger, write
from src.experiments.report2 import (
    ROOT, PROTOCOL, MANIFEST, IMPLEMENTATION,
    canonical_hash, read_json, create_prefix, restore_prefix,
    run_branch, validate_branch, evidence_hashes, branch_descriptor
)
from src.research.report2_production import (
    TASK, MODEL, SCALE,
    production_plan, baseline_plan, episode_identity,
    validate_authorization, fingerprint
)


def get_evaluation_block(block_id: str, root: Path = ROOT) -> dict:
    sampling = read_json(root / MANIFEST)
    for b in sampling["evaluation_blocks"]:
        if b["block_id"] == block_id:
            return b
    raise ValueError(f"Unknown evaluation block: {block_id}")


def prepare_production_case(block: dict, elasticity: float = 1.5,
                            batch_dir: Path | None = None, root: Path = ROOT) -> Path:
    """Prepare isolated case inputs with per-case/elasticity settings. Never edit shared configs in place."""
    protocol = read_json(root / PROTOCOL)
    if elasticity not in [1.5, 0.75, 2.25]:
        raise ValueError(f"Undeclared elasticity setting: {elasticity}")
    batch_dir = Path(batch_dir) if batch_dir is not None else root / "results/report2/production"
    block_dir = batch_dir / "cases" / block["block_id"] / f"elasticity_{elasticity}"
    prepared = block_dir / "inputs"
    if prepared.exists() and (prepared / "artifact_checksums.json").exists():
        return prepared

    block_dir.mkdir(parents=True, exist_ok=True)
    settings = read_json(root / "configs/kaggle_retailbench.json")
    settings["elasticity"] = elasticity
    config = block_dir / "settings.json"
    config.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    raw_path = root / protocol["dataset"]["path"]
    prepare_dataset(
        raw_path,
        prepared,
        config_path=config,
        store_id=block["store_id"],
        product_ids=[block["product_id"]],
        episode_start=block["start"],
    )
    return prepared


def get_or_create_prefix(block: dict, elasticity: float = 1.5,
                         batch_dir: Path | None = None, root: Path = ROOT) -> dict:
    """Save and cache an immutable prefix per block and elasticity."""
    batch_dir = Path(batch_dir) if batch_dir is not None else root / "results/report2/production"
    warmup_dir = batch_dir / "cases" / block["block_id"] / f"elasticity_{elasticity}" / "warmup"
    prefix_path = warmup_dir / "prefix.json"
    if prefix_path.exists():
        return read_json(prefix_path)

    prepared = prepare_production_case(block, elasticity, batch_dir=batch_dir, root=root)
    warmup_dir.mkdir(parents=True, exist_ok=True)
    prefix = create_prefix(prepared, warmup_dir)
    return prefix


def check_prior_claim(batch_dir: Path, path: Path) -> None:
    saved = read_json(path)
    if saved.get("status") != "validated_complete":
        raise ValueError("An incomplete or interrupted claimed branch needs evidence review; automatic paid retry is blocked.")
    run = batch_dir / "branches" / path.stem
    requests = batch_dir / "requests" / path.stem
    if not run.exists():
        raise ValueError(f"Branch directory missing for validated claim: {path.stem}")
    manifest = read_json(run / "run_manifest.json")
    if manifest.get("status") != "validated_complete":
        raise ValueError(f"Run manifest status not validated_complete for {path.stem}")
    if saved.get("evidence_sha256") != evidence_hashes(run):
        raise ValueError(f"Previously completed branch evidence changed for {path.stem}")
    if requests.exists():
        request_hashes = {p.relative_to(requests).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in requests.rglob("*") if p.is_file()}
        if saved.get("request_artifact_sha256") and saved["request_artifact_sha256"] != request_hashes:
            raise ValueError(f"Request artifacts changed for {path.stem}")


def run_baseline_branch(episode: dict, batch_dir: Path, root: Path = ROOT) -> dict:
    """Execute a single deterministic baseline branch (free, offline, 0 model calls)."""
    block = get_evaluation_block(episode["block_id"], root)
    elasticity = episode["elasticity"]
    prepared = prepare_production_case(block, elasticity, batch_dir=batch_dir, root=root)
    prefix = get_or_create_prefix(block, elasticity, batch_dir=batch_dir, root=root)

    b_plan = baseline_plan(root=root)
    identity = episode_identity(b_plan, episode)
    run_dir = batch_dir / "baselines" / "branches" / identity
    claim_path = batch_dir / "baselines" / "claims" / f"{identity}.json"

    if claim_path.exists() and run_dir.exists():
        saved = read_json(claim_path)
        if saved.get("status") == "validated_complete":
            return {"status": "validated_complete", "identity": identity, "skipped_existing": True}

    claim_path.parent.mkdir(parents=True, exist_ok=True)
    claim = {"status": "running", "episode": episode, "policy": episode["policy"]}
    write(claim_path, claim)

    if run_dir.exists():
        shutil.rmtree(run_dir)

    run_branch(
        prepared,
        prefix,
        run_dir,
        scenario=episode["scenario"],
        history=episode["history"],
        policy=episode["policy"],
        realization=episode["realization"],
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    replay_dir = batch_dir / "baselines" / "replays" / f"{identity}_{stamp}"
    validate_branch(prepared, prefix, run_dir, replay_dir)

    claim["status"] = "validated_complete"
    claim["evidence_sha256"] = evidence_hashes(run_dir)
    write(claim_path, claim)
    return {"status": "validated_complete", "identity": identity, "skipped_existing": False}


def run_all_baselines(batch_dir: Path | None = None, cohort: str = "all", root: Path = ROOT) -> dict:
    """Execute all 576 deterministic baseline branches offline."""
    batch_dir = Path(batch_dir) if batch_dir is not None else root / "results/report2/production"
    b_plan = baseline_plan(cohort=cohort, root=root)
    episodes = b_plan["episodes"]
    completed = 0
    skipped = 0

    with execution_lock(batch_dir / "baselines"):
        for i, ep in enumerate(episodes):
            res = run_baseline_branch(ep, batch_dir, root=root)
            if res.get("skipped_existing"):
                skipped += 1
            else:
                completed += 1

    return {
        "status": "baselines_complete",
        "cohort": cohort,
        "total_baseline_branches": len(episodes),
        "newly_executed": completed,
        "skipped_already_complete": skipped,
        "model_calls_made": 0,
    }


def run_production_model_branch(index: int, auth_path: Path, budget_path: Path,
                                batch_dir: Path | None = None, root: Path = ROOT) -> int:
    """Subprocess runner for one production model branch.

    Durable claim is created before client creation.
    Stop on any transport/budget error without automated retry.
    """
    auth = read_json(Path(auth_path))
    allowance = read_json(Path(budget_path))
    protocol = read_json(root / PROTOCOL)

    # Determine cohort from auth or proposal
    cohort = auth.get("cohort", "main")
    plan = production_plan(cohort, root)
    validate_authorization(auth, allowance, plan, index)
    require_existing_ledger(allowance)

    batch_dir = Path(batch_dir) if batch_dir is not None else root / "results/report2/production"
    batch_dir.mkdir(parents=True, exist_ok=True)

    with execution_lock(batch_dir):
        # Validate all prior claims in batch
        claims_dir = batch_dir / "claims"
        if claims_dir.exists():
            for claim_file in sorted(claims_dir.glob("*.json")):
                check_prior_claim(batch_dir, claim_file)

        episode = plan["episodes"][index]
        identity = episode_identity(plan, episode)
        claim_path = batch_dir / "claims" / f"{identity}.json"

        if claim_path.exists():
            saved = read_json(claim_path)
            if saved.get("status") == "validated_complete":
                print(json.dumps({"status": "already_validated_complete", "branch_index": index, "identity": identity}), flush=True)
                return 0
            raise ValueError("This logical branch already ran or is interrupted; validate saved evidence instead of reissuing model calls.")

        block = get_evaluation_block(episode["block_id"], root)
        elasticity = episode["elasticity"]
        prepared = prepare_production_case(block, elasticity, batch_dir=batch_dir, root=root)
        prefix = get_or_create_prefix(block, elasticity, batch_dir=batch_dir, root=root)

        claim_path.parent.mkdir(parents=True, exist_ok=True)
        claim = {
            "status": "claimed_before_client_creation",
            "branch_index": index,
            "episode": episode,
            "authorization_sha256": canonical_hash(auth),
            "budget_sha256": fingerprint(allowance),
        }
        with claim_path.open("x", encoding="utf-8") as stream:
            json.dump(claim, stream, indent=2)

        run_dir = batch_dir / "branches" / identity
        request_dir = batch_dir / "requests" / identity
        ledger = None
        counts = None

        try:
            from src.benchmarks.common import credentials, settings, install_gateway_clients
            from src.benchmarks.budget import load_budget
            from src.agents.llm import LLMPolicy
            import openai

            _, base = credentials()
            ledger = load_budget(Path(budget_path), run_id=identity, scope="kaggle", base_url=base, purpose="evaluation")
            config = {
                **settings(),
                "max_output_tokens": protocol["model"]["max_output_tokens"],
                "max_api_calls_per_task": 28,
                "_purpose": "evaluation",
                "_run_id": identity,
                "_request_context": {"task_id": plan["task_id"], "episode_id": identity},
            }
            counts = install_gateway_clients(request_dir, config, budget=ledger)

            with openai.OpenAI() as client:
                run_branch(
                    prepared,
                    prefix,
                    run_dir,
                    scenario=episode["scenario"],
                    history=episode["history"],
                    policy="llm_with_fallback",
                    realization=episode["realization"],
                    decide=LLMPolicy(client, protocol["model"]),
                    manual_model_execution=True,
                )

            summary = read_json(run_dir / "summary.json")
            summary["model_calls_made"] = counts["attempts"]
            write(run_dir / "summary.json", summary)

            manifest = read_json(run_dir / "run_manifest.json")
            manifest["evidence_sha256"] = evidence_hashes(run_dir)
            write(run_dir / "run_manifest.json", manifest)

            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            validate_branch(prepared, prefix, run_dir, batch_dir / "replays" / f"{identity}_{stamp}")

            claim["status"] = "validated_complete"
            claim["evidence_sha256"] = evidence_hashes(run_dir)
            print(json.dumps({"status": "validated_complete", "branch_index": index, "identity": identity}, indent=2), flush=True)
        finally:
            if ledger:
                write(request_dir / "budget_summary.json", ledger.summary())
            if counts is not None:
                write(request_dir / "usage_totals.json", counts)
            if claim.get("status") == "validated_complete":
                claim["request_artifact_sha256"] = {
                    p.relative_to(request_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in request_dir.rglob("*") if p.is_file()
                }
            write(claim_path, claim)
    return 0


def active_production_state(plan: dict, batch_dir: Path, ledger_path: Path, root: Path = ROOT) -> tuple[list[int], dict, int]:
    """Check currently completed branches and total physical attempts."""
    from src.research.report2_production import read_ledger
    _, state, rows, _ = read_ledger(ledger_path)
    known = {episode_identity(plan, ep): i for i, ep in enumerate(plan["episodes"])}
    claims = {}
    claims_dir = batch_dir / "claims"
    if claims_dir.exists():
        for p in claims_dir.glob("*.json"):
            if p.stem in known:
                claims[p.stem] = p
            else:
                raise ValueError(f"Unexpected claim appeared: {p.stem}")

    completed = []
    for key, claim_path in claims.items():
        check_prior_claim(batch_dir, claim_path)
        index = known[key]
        completed.append(index)

    completed.sort()
    return completed, state, state["attempts"]


def run_pending_production(plan: dict, batch_dir: Path, auth_path: Path, budget_path: Path,
                           runner, *, manual: bool = False, root: Path = ROOT) -> tuple[dict, int]:
    """Serial execution of pending production branches with one fresh subprocess per branch."""
    if not manual:
        raise ValueError("Models require explicit user manual execution.")
    budget = read_json(Path(budget_path))
    ledger_path = root / "results/budgets" / f"{budget['budget_id']}.sqlite"
    launched = 0

    for index in range(len(plan["episodes"])):
        completed, state, total_attempts = active_production_state(plan, batch_dir, ledger_path, root=root)
        if index in completed:
            continue
        if state["attempts"] + 28 > budget["max_attempts"]:
            raise ValueError(f"Too few attempt slots remain in budget ceiling ({state['attempts']} / {budget['max_attempts']}).")

        print(json.dumps({
            "branch_index": index,
            "completed_before_launch": len(completed),
            "total_planned_branches": len(plan["episodes"]),
            "physical_attempts_so_far": total_attempts,
        }), flush=True)

        code = runner(index, Path(auth_path), Path(budget_path))
        launched += 1
        if code:
            return {
                "status": "stopped_requires_review",
                "failed_branch_index": index,
                "new_branches_launched": launched,
                "next_gate": "Preserve new evidence; do not automatically retry",
            }, code

        new_completed, _, _ = active_production_state(plan, batch_dir, ledger_path, root=root)
        if index not in new_completed:
            raise ValueError(f"Branch {index} finished without a verified completed claim.")

    return {
        "status": "production_execution_complete_requires_audit",
        "completed_branches": len(plan["episodes"]),
        "new_branches_launched": launched,
    }, 0

