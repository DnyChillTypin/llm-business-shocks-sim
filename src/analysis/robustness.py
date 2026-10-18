"""Isolated deterministic baseline sensitivity and independent saved-action replay."""
import copy
import hashlib
import json
import math
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from src.agents.baselines import choose_actions
from src.analysis.metrics import episode_financials
from src.experiments.kaggle_protocol import read, write


def isolated_inputs(source, target, elasticity):
    source, target = Path(source).resolve(), Path(target).resolve()
    if elasticity not in (.75, 2.25) or target == source or target.is_relative_to(source):
        raise ValueError("Only the two declared overrides in independent directories are permitted.")
    manifest = read(source / "manifest.json")
    if manifest["settings"]["elasticity"] != 1.5:
        raise ValueError("Sensitivity must start from the unchanged primary assumption.")
    shutil.copytree(source, target)
    changed = copy.deepcopy(manifest)
    changed["settings"]["elasticity"] = elasticity
    write(target / "manifest.json", changed)
    write(target / "artifact_checksums.json", {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(target.rglob("*")) if p.is_file() and p.name != "artifact_checksums.json"})
    return target


def validate_baseline(run, prepared, *, elasticity, scenario, policy, cache):
    if policy not in ("fixed", "adaptive") or elasticity not in (.75, 1.5, 2.25):
        raise ValueError("This validator cannot validate LLM sensitivity or undeclared assumptions.")
    from src.envs.kaggle_retailbench import KaggleRetailEnvironment
    from src.experiments.kaggle import apply_actions
    run, prepared = Path(run), Path(prepared)
    if (run / "api_attempts.jsonl").exists() or (run / "budget_summary.json").exists():
        raise ValueError("A free baseline cohort must contain no model requests or budget client.")
    source = read(prepared / "manifest.json")
    if source["settings"]["elasticity"] != elasticity:
        raise ValueError("Prepared sensitivity assumption does not match its declared cohort.")
    actions = [json.loads(s) for s in (run / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
    observations = [json.loads(s) for s in (run / "observations.jsonl").read_text(encoding="utf-8").splitlines()]
    daily, summary = pd.read_csv(run / "daily_results.csv"), read(run / "summary.json")
    if len(actions) != 21 or len(observations) != 21 or len(daily) != 21:
        raise ValueError("Sensitivity episodes must retain the complete horizon.")
    enriched = []
    with tempfile.TemporaryDirectory(dir=cache) as temporary:
        env = KaggleRetailEnvironment(prepared, Path(temporary) / "replay", scenario)
        for i, (action, record) in enumerate(zip(actions, observations), 1):
            obs = env.observe()
            if obs != record["observation"] or action["date"] != record["date"] or action["actions"] != choose_actions(obs, policy):
                raise ValueError("Sensitivity observations or baseline choices differ on independent replay.")
            if action["fallback_used"] or action["repair_attempted"] or action["invalid_responses"]:
                raise ValueError("A deterministic baseline cannot contain model fallback/repair flags.")
            sku = next(iter(obs["products"]))
            p, a = obs["products"][sku], action["actions"][sku]
            enriched.append(dict(episode_day=i, order_quantity=a["order_quantity"], price_multiplier=a["price_multiplier"],
                observed_funds=obs["funds"], observed_inventory=p["inventory"], observed_on_order=p["on_order"], unit_cost=p["unit_cost"]))
            apply_actions(env, obs, action["actions"])
        replayed = pd.DataFrame(env.ledger)
        pd.testing.assert_frame_equal(replayed.reset_index(drop=True), daily[replayed.columns].reset_index(drop=True), check_dtype=False, atol=1e-6, rtol=0)
        if not env.done or not math.isclose(env.funds, summary["final_funds"], abs_tol=1e-6, rel_tol=0):
            raise ValueError("Sensitivity horizon or final cash does not reconcile.")
    full = pd.concat([daily.reset_index(drop=True), pd.DataFrame(enriched)], axis=1)
    metrics = episode_financials(full, summary["final_funds"])
    if not math.isclose(metrics["contribution"], summary["contribution"], abs_tol=1e-6, rel_tol=0):
        raise ValueError("Sensitivity summary contribution differs from replay.")
    return dict(status="validated_complete", days=21, independent_replay=True,
                baseline_choices_match=True, accounting_reconciled=True, model_calls=0,
                base_demand_sha256=hashlib.sha256(daily[["date", "sku_id", "base_demand"]].to_csv(index=False).encode()).hexdigest())
