"""Matched-prefix retail branches with audited replay and isolated simulator RNGs.

Replay deliberately excludes opaque native UUIDs and log timestamps from economic
state comparisons. Policies receive only the explicitly treated observation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

from src.agents.baselines import choose_actions
from src.agents.llm import decode_action, validate_actions
from src.envs.kaggle_retailbench import KaggleRetailEnvironment, SCENARIOS
from src.experiments.kaggle import apply_actions
from src.experiments.kaggle_protocol import write
from src.research.report2 import ROOT, PROTOCOL, MANIFEST, canonical_hash, read_json

IMPLEMENTATION = "configs/report2/implementation_manifest.json"
TASK = "report2:development"


def rng_state():
    py, np_state = random.getstate(), np.random.get_state()
    return {"python": [py[0], list(py[1]), py[2]],
            "numpy": [np_state[0], np_state[1].tolist(), int(np_state[2]), int(np_state[3]), float(np_state[4])]}


def set_rng(state):
    py, n = state["python"], state["numpy"]
    random.setstate((py[0], tuple(py[1]), py[2]))
    np.random.set_state((n[0], np.array(n[1], dtype=np.uint32), n[2], n[3], n[4]))


@contextmanager
def simulator_rng(env=None):
    """SDK or fixture randomness cannot advance a simulator's random stream."""
    caller = rng_state()
    try:
        if env is None:
            random.seed(42)
            np.random.seed(42)
        else:
            set_rng(env._report2_rng)
        yield
    finally:
        if env is not None:
            env._report2_rng = rng_state()
        set_rng(caller)


def new_environment(prepared, run):
    with simulator_rng():
        env = KaggleRetailEnvironment(prepared, run, "control")
        env._report2_rng = rng_state()
    return env


def advance(env, observation, actions):
    with simulator_rng(env):
        apply_actions(env, observation, actions)


def item_state(items):
    """Run-length encode equal merchandise attributes, preserving FIFO order."""
    result = []
    for item in items:
        attributes = {"sku_id": item.sku.sku_id, "begin_time": item.begin_time.isoformat(),
                      "expired_time": item.expired_time.isoformat(), "unit_cost": item.buy_price,
                      "quality_score": item.quality_score, "supplier_id": item.supplier_id}
        if result and result[-1]["attributes"] == attributes:
            result[-1]["quantity"] += 1
        else:
            result.append({"attributes": attributes, "quantity": 1})
    return result


def economic_state(env):
    """All transition-relevant mutable state in this bounded, no-tool policy path."""
    return {"date": env.current_date.isoformat(), "funds": float(env.funds),
            "skus": {sku: {"price": obj.price, "sales": obj.sales,
                           "today_demand": obj.today_demand} for sku, obj in env.skus_id_map.items()},
            "inventory": {sku: item_state(items) for sku, items in env.inventory.items_by_sku.items()},
            "waiting_inventory": item_state(env.inventory.waiting_items),
            "orders": [{"created_at": o.created_at.isoformat(), "delivery_days": o.delivery_time,
                        "expected_delivery_date": o.expected_delivery_date.isoformat(),
                        "supplier": o.customer_id, "cost": o.cost,
                        "quantities": {sku.sku_id: q for sku, q in o.ordered_sku.items()},
                        "items": item_state(o.items)} for o in env.order_manager.get_current_orders()],
            "history": copy.deepcopy(env._history), "ledger": copy.deepcopy(env.ledger),
            "notes": copy.deepcopy(env.notes), "rng": copy.deepcopy(env._report2_rng)}


def assets(env):
    return (env.funds + env.inventory.compute_net_worth(env.current_date)
            + sum(o.cost for o in env.order_manager.get_current_orders()))


def prepared_hash(prepared):
    return canonical_hash(read_json(Path(prepared) / "artifact_checksums.json"))


def create_prefix(prepared, run):
    """Save seven adaptive decisions and a complete economic-state fingerprint."""
    env = new_environment(prepared, run)
    decisions = []
    for _ in range(7):
        observation = env.observe()
        actions = choose_actions(observation, "adaptive")
        decisions.append({"date": observation["date"], "observation_sha256": canonical_hash(observation),
                          "actions": actions})
        advance(env, observation, actions)
    state = economic_state(env)
    prefix = {"schema_version": 1, "prepared_sha256": prepared_hash(prepared),
              "decisions": decisions, "state": state, "state_sha256": canonical_hash(state),
              "restoration": "Seven-day deterministic replay; opaque UUIDs and log timestamps are excluded",
              "model_calls_made": 0}
    prefix["prefix_sha256"] = canonical_hash(prefix)
    write(Path(run) / "prefix.json", prefix)
    return prefix


def restore_prefix(prepared, prefix, run, scenario):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown shock branch.")
    unsigned = {k: v for k, v in prefix.items() if k != "prefix_sha256"}
    if (canonical_hash(unsigned) != prefix["prefix_sha256"]
            or canonical_hash(prefix["state"]) != prefix["state_sha256"]
            or prepared_hash(prepared) != prefix["prepared_sha256"]
            or len(prefix["decisions"]) != 7):
        raise ValueError("Prefix or prepared inputs changed.")
    env = new_environment(prepared, run)
    for saved in prefix["decisions"]:
        observation = env.observe()
        if (saved["date"] != observation["date"]
                or saved["observation_sha256"] != canonical_hash(observation)
                or saved["actions"] != choose_actions(observation, "adaptive")):
            raise ValueError("Warm-up replay does not match the frozen adaptive prefix.")
        advance(env, observation, saved["actions"])
    state = economic_state(env)
    if state != prefix["state"]:
        raise ValueError("Restored cash, stock, pipeline, history, accounting or RNG differs.")
    if (env.current_date - env.start_date).days != 7:
        raise ValueError("Restoration must end immediately before day 8.")
    # Activate the branch only AFTER the common latent state has been audited.
    # Current delivery lead time may legitimately differ in the day-8 observation.
    env.scenario = scenario
    write(Path(run) / "prefix_audit.json", {"status": "passed", "prefix_sha256": prefix["prefix_sha256"],
          "restored_state_sha256": canonical_hash(state), "scenario": scenario,
          "comparison_time": "Before scenario activation immediately before day 8"})
    return env


def treat_history(observation, variant, frozen):
    if variant not in {"full", "frozen", "none"}:
        raise ValueError("Unknown history treatment.")
    result = copy.deepcopy(observation)
    for sku, product in result["products"].items():
        history = product["history"] if variant == "full" else (frozen[sku] if variant == "frozen" else [])
        if any(row["date"] >= result["date"] for row in history):
            raise ValueError("An observation contains future or current-day completed history.")
        product["history"] = copy.deepcopy(history)
    return result


def branch_descriptor(prepared, prefix, *, scenario, history, policy, realization=0):
    return {"study_id": "business_shocks_report2_v1", "prepared_sha256": prepared_hash(prepared),
            "prefix_sha256": prefix["prefix_sha256"], "scenario": scenario, "history": history,
            "policy": policy, "realization": realization}


def append(path, value):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def validate_decision(record, observation, policy):
    validate_actions(record["actions"], observation)
    if policy in {"fixed", "adaptive"}:
        if (record["source"] != policy or record["repair_attempted"] or record["fallback_used"]
                or record["invalid_responses"] != 0):
            raise ValueError("Baseline intervention flags changed.")
        return
    responses = record.get("responses", [])
    repair, fallback = record["repair_attempted"], record["fallback_used"]
    expected_invalid = 2 if fallback else int(repair)
    if (len(responses) not in {1, 2} or repair != (len(responses) == 2)
            or (fallback and not repair) or record["invalid_responses"] != expected_invalid
            or len(record.get("validation_errors", [])) != expected_invalid
            or record["source"] != ("adaptive_fallback" if fallback else "llm")):
        raise ValueError("Repair/fallback provenance or response denominators changed.")
    expected = choose_actions(observation, "adaptive") if fallback else decode_action(responses[-1], observation)
    if record["actions"] != expected:
        raise ValueError("Final action differs from its response or treated-observation fallback.")


def evidence_hashes(run):
    return {name: hashlib.sha256((Path(run) / name).read_bytes()).hexdigest()
            for name in ("observations.jsonl", "actions.jsonl", "daily_results.csv", "summary.json", "prefix_audit.json")}


def run_branch(prepared, prefix, run, *, scenario, history="full", policy="adaptive",
               realization=0, decide=None, manual_model_execution=False):
    """Finish a fresh branch; reuse requires independent validation, never overwrite."""
    if policy not in {"fixed", "adaptive", "scripted_fixture", "llm_with_fallback"}:
        raise ValueError("Unknown report 2 policy.")
    if history not in {"full", "frozen", "none"}:
        raise ValueError("Unknown history treatment.")
    if policy in {"fixed", "adaptive"} and (decide is not None or history != "full"):
        raise ValueError("Standalone reference baselines must keep full history and native rules.")
    if policy == "llm_with_fallback" and (not manual_model_execution or decide is None):
        raise ValueError("A model branch requires the manual runner and its approved budget handoff.")
    if policy == "scripted_fixture" and decide is None:
        raise ValueError("A fixture requires an explicitly scripted decision function.")
    run = Path(run)
    run.mkdir(parents=True, exist_ok=False)
    descriptor = branch_descriptor(prepared, prefix, scenario=scenario, history=history,
                                   policy=policy, realization=realization)
    manifest = {**descriptor, "branch_id": canonical_hash(descriptor), "status": "running",
                "expected_response_decisions": 14, "agent_kind": "genuine_llm" if policy == "llm_with_fallback" else policy}
    write(run / "run_manifest.json", manifest)
    try:
        env = restore_prefix(prepared, prefix, run, scenario)
        initial_assets = assets(env)
        frozen = {sku: copy.deepcopy(rows[-14:]) for sku, rows in env._history.items()}
        records = []
        while not env.done:
            observation = treat_history(env.observe(), history, frozen)
            append(run / "observations.jsonl", {"observation": observation, "sha256": canonical_hash(observation)})
            started = time.monotonic()
            if decide is None:
                actions = choose_actions(observation, policy)
                details = {"source": policy, "fallback_used": False, "repair_attempted": False, "invalid_responses": 0}
            else:
                actions, details = decide(copy.deepcopy(observation))
            record = {"date": observation["date"], "actions": actions, **details,
                      "decision_seconds": time.monotonic() - started}
            validate_decision(record, observation, policy)
            append(run / "actions.jsonl", record)
            advance(env, observation, actions)
            records.append(record)
        response = pd.DataFrame(env.ledger[7:])
        if len(records) != 14 or response["date"].nunique() != 14:
            raise ValueError("A response branch must cover exactly days 8-21.")
        contribution = float(response["contribution"].sum())
        if not math.isclose(assets(env) - initial_assets, contribution, abs_tol=1e-6, rel_tol=0):
            raise ValueError("Post-split cash, inventory and pipeline accounting did not reconcile.")
        response.to_csv(run / "daily_results.csv", index=False)
        first_pass = sum(not r["repair_attempted"] and not r["fallback_used"] for r in records)
        repairs = sum(r["repair_attempted"] for r in records)
        summary = {"status": "complete_requires_replay", "scheduled_decisions": 14,
                   "completed_decisions": len(records), "post_split_contribution": contribution,
                   "fill_rate": float(response["sales"].sum() / response["demand"].sum()) if response["demand"].sum() else 1.0,
                   "mean_closing_inventory": float(response["closing_inventory"].mean()),
                   "first_pass_valid": first_pass if decide is not None else None,
                   "repair_attempts": repairs, "successful_repairs": sum(r["repair_attempted"] and not r["fallback_used"] for r in records),
                   "fallback_days": sum(r["fallback_used"] for r in records),
                   "invalid_responses": sum(r["invalid_responses"] for r in records),
                   "initial_assets_at_split": initial_assets, "terminal_assets": assets(env),
                   "final_funds": float(env.funds), "accounting_reconciled": True,
                   "model_responses": sum(len(r.get("responses", [])) for r in records) if policy == "llm_with_fallback" else 0,
                   "model_calls_made": 0 if policy != "llm_with_fallback" else None}
        write(run / "summary.json", summary)
        manifest.update(status="complete_requires_replay", evidence_sha256=evidence_hashes(run))
        return summary
    except BaseException as exc:
        manifest.update(status="incomplete", failure_category=type(exc).__name__)
        raise
    finally:
        write(run / "run_manifest.json", manifest)


def validate_branch(prepared, prefix, run, replay_dir):
    """Independent saved-action replay; never reissues a decision or request."""
    run = Path(run)
    manifest = read_json(run / "run_manifest.json")
    expected = branch_descriptor(prepared, prefix, **{k: manifest[k] for k in ("scenario", "history", "policy", "realization")})
    if (manifest["branch_id"] != canonical_hash(expected)
            or any(manifest.get(k) != v for k, v in expected.items())
            or manifest["status"] not in {"complete_requires_replay", "validated_complete"}
            or manifest["evidence_sha256"] != evidence_hashes(run)):
        raise ValueError("Branch identity, completeness or bound evidence changed.")
    env = restore_prefix(prepared, prefix, replay_dir, manifest["scenario"])
    initial_assets = assets(env)
    frozen = {sku: copy.deepcopy(rows[-14:]) for sku, rows in env._history.items()}
    observations = [json.loads(line) for line in (run / "observations.jsonl").read_text().splitlines()]
    actions = [json.loads(line) for line in (run / "actions.jsonl").read_text().splitlines()]
    if len(observations) != 14 or len(actions) != 14:
        raise ValueError("Missing or duplicate response decisions.")
    for stored, action in zip(observations, actions):
        current = treat_history(env.observe(), manifest["history"], frozen)
        if (current != stored["observation"] or canonical_hash(current) != stored["sha256"]
                or action["date"] != current["date"]):
            raise ValueError("Saved observation differs from an independent state reconstruction.")
        if manifest["policy"] in {"fixed", "adaptive"}:
            if action["actions"] != choose_actions(current, manifest["policy"]):
                raise ValueError("Saved baseline differs from its defined rule.")
        if action["fallback_used"] and action["actions"] != choose_actions(current, "adaptive"):
            raise ValueError("Fallback differs from adaptive on the treated observation.")
        validate_decision(action, current, manifest["policy"])
        advance(env, current, action["actions"])
    actual = pd.DataFrame(env.ledger[7:])
    saved = pd.read_csv(run / "daily_results.csv")
    pd.testing.assert_frame_equal(actual, saved, check_exact=False, rtol=1e-12, atol=1e-7)
    summary = read_json(run / "summary.json")
    if (not env.done or not math.isclose(assets(env) - initial_assets, float(actual["contribution"].sum()), abs_tol=1e-6, rel_tol=0)
            or not math.isclose(summary["post_split_contribution"], float(actual["contribution"].sum()), abs_tol=1e-6, rel_tol=0)
            or not math.isclose(summary["final_funds"], env.funds, abs_tol=1e-6, rel_tol=0)):
        raise ValueError("Independent response accounting differs from saved results.")
    expected_counts = {
        "scheduled_decisions": 14, "completed_decisions": 14,
        "first_pass_valid": (sum(not r["repair_attempted"] and not r["fallback_used"] for r in actions)
                             if manifest["policy"] not in {"fixed", "adaptive"} else None),
        "repair_attempts": sum(r["repair_attempted"] for r in actions),
        "successful_repairs": sum(r["repair_attempted"] and not r["fallback_used"] for r in actions),
        "fallback_days": sum(r["fallback_used"] for r in actions),
        "invalid_responses": sum(r["invalid_responses"] for r in actions),
    }
    if any(summary.get(k) != v for k, v in expected_counts.items()):
        raise ValueError("Summary reliability denominators differ from saved decisions.")
    numeric = {"fill_rate": float(actual["sales"].sum() / actual["demand"].sum()) if actual["demand"].sum() else 1.0,
               "mean_closing_inventory": float(actual["closing_inventory"].mean()),
               "initial_assets_at_split": initial_assets, "terminal_assets": assets(env)}
    if (not summary.get("accounting_reconciled")
            or any(not math.isclose(summary[k], value, abs_tol=1e-6, rel_tol=0) for k, value in numeric.items())):
        raise ValueError("Saved service, inventory or terminal accounting differs from replay.")
    if manifest["policy"] == "llm_with_fallback":
        responses = sum(len(r["responses"]) for r in actions)
        if summary["model_calls_made"] != responses or summary["model_responses"] != responses:
            raise ValueError("Complete model responses and gateway attempts do not reconcile.")
    summary["status"] = "validated_complete"
    write(run / "summary.json", summary)
    manifest["evidence_sha256"] = evidence_hashes(run)
    write(run / "validation.json", {"status": "validated_complete", "model_calls_made": 0,
          "branch_id": manifest["branch_id"], "evidence_sha256": manifest["evidence_sha256"]})
    manifest["status"] = "validated_complete"
    write(run / "run_manifest.json", manifest)
    return {"status": "validated_complete", "branch_id": manifest["branch_id"], "model_calls_made": 0}


def development_plan(root=ROOT):
    protocol = read_json(root / PROTOCOL)
    sampling = read_json(root / MANIFEST)
    implementation = read_json(root / IMPLEMENTATION)
    episodes = [{"case_id": case["id"], "scenario": scenario, "history": history, "realization": 0}
                for case in sampling["development_cases"]
                for scenario in protocol["branching"]["conditions"]
                for history in protocol["policies"]["history_variants"]]
    return {"study_id": protocol["study_id"], "task_id": TASK, "cohort": "development",
            "sampling_sha256": sampling["manifest_sha256"], "implementation_sha256": implementation["implementation_sha256"],
            "episodes": episodes, "decisions": len(episodes) * 14, "max_attempts": len(episodes) * 28,
            "approved": False, "model_execution": "user_manually_only"}
