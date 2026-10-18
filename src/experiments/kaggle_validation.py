"""Independent saved-action replay and provenance checks; no network client."""
import hashlib
import json
import math
import re
import sqlite3
import tempfile
from collections import defaultdict
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.agents.baselines import choose_actions
from src.agents.llm import LLMPolicy, serialize_observation, validate_actions
from src.benchmarks.common import ROOT
from src.data.kaggle import prepare_dataset
from src.envs.kaggle_retailbench import KaggleRetailEnvironment
from src.experiments.kaggle import apply_actions
from src.experiments.kaggle_protocol import read, episode_id, episode_evidence_digest
from src.research.design import canonical_hash


def lines(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines()]


def _same_frame(left, right):
    try:
        pd.testing.assert_frame_equal(left.reset_index(drop=True), right[left.columns].reset_index(drop=True),
                                      check_dtype=False, atol=1e-6, rtol=0)
        return True
    except (AssertionError, KeyError):
        return False


def _report(report, checks):
    report["checks"] = {k: bool(v) for k, v in checks.items()}
    report["status"] = "validated_complete" if checks and all(checks.values()) else "requires_review"
    return report


def validate_run(run):
    """Never reissue saved requests or infer a missing model decision."""
    run = Path(run)
    checks, report = {}, {"status": "requires_review", "checks": {}, "run_id": run.name}
    try:
        study = read(ROOT / "configs/study.json")
        design = study["kaggle"]
        manifest, summary = read(run / "run_manifest.json"), read(run / "summary.json")
        observations, actions = lines(run / "observations.jsonl"), lines(run / "actions.jsonl")
        frame = pd.read_csv(run / "daily_results.csv")
        kind = manifest.get("agent_kind", "genuine_llm" if manifest["policy"] == "llm_with_fallback" else "baseline")
        window, purpose, policy = manifest["window"], manifest["purpose"], manifest["policy"]
        valid_provenance = ((purpose == "pilot" and window == "validation_pilot" and kind in {"baseline", "genuine_llm"})
            or (purpose == "offline_validation" and window == "validation_pilot" and kind in {"baseline", "scripted"})
            or (purpose == "evaluation" and window == "primary_evaluation" and kind in {"baseline", "genuine_llm"}))
        checks["provenance"] = valid_provenance and manifest["primary_evaluation"] == (purpose == "evaluation")
        checks["policy_kind"] = ((kind == "baseline" and policy in {"fixed", "adaptive"})
            or (kind == "genuine_llm" and policy == "llm_with_fallback")
            or (kind == "scripted" and policy == "scripted_fixture"))
        checks["frozen_series_and_study"] = (manifest["series"] in design["selection"]["selected_series"]
            and manifest["study_sha256"] == canonical_hash(study) and manifest["episode_id"] == episode_id(manifest))
        checks["execution_finished"] = manifest["status"] in {"validated_complete", "execution_finished_requires_artifact_review"}
        expected_days = pd.date_range(design["windows"][window]["start"], periods=21).strftime("%Y-%m-%d").tolist()
        days = [r["date"] for r in observations]
        checks["full_21_days"] = (days == expected_days == [r["date"] for r in actions]
            and len(frame) == 21 and frame["date"].tolist() == expected_days
            and manifest["expected_days"] == summary["days"] == 21)
        checks["observation_hashes"] = all(r["sha256"] == hashlib.sha256(serialize_observation(r["observation"]).encode()).hexdigest() for r in observations)
        checks["strictly_past_history"] = all(h["date"] < r["date"] for r in observations for p in r["observation"]["products"].values() for h in p["history"])
        checks["no_hidden_scenario_label"] = all("scenario" not in r["observation"] and "future_demand" not in r["observation"] for r in observations)
        checks["correct_scenario_policy"] = (summary["scenario"] == manifest["scenario"] and summary["policy"] == policy
            and frame["scenario"].eq(manifest["scenario"]).all() and frame["policy"].eq(policy).all()
            and all(a["policy"] == policy for a in actions))
        report.update(scenario=manifest["scenario"], purpose=purpose, agent_kind=kind, summary=summary,
            qualification="Synthetic adaptation; scripted fixtures are not model outcomes; primary provenance is distinct from validation.")
        if not all(checks.values()):
            return _report(report, checks)
        events = lines(run / "api_attempts.jsonl") if (run / "api_attempts.jsonl").exists() else []
        starts = [e for e in events if e["event"] == "started"]
        finishes = [e for e in events if e["event"] == "finished"]
        by_day = defaultdict(list)
        if kind == "genuine_llm":
            budget = read(run / "budget_summary.json")
            checks["attempts_complete"] = (len(starts) == len({e["attempt_id"] for e in starts}) == len(finishes)
                and {e["attempt_id"] for e in starts} == {e["attempt_id"] for e in finishes})
            checks["usage_known_for_this_run"] = all(e["status"] == "completed" and e.get("cost_usd") is not None for e in finishes)
            checks["no_blocking_charge"] = budget["pending_attempts"] == budget.get("blocking_uncertain_attempts", budget["uncertain_attempts"]) == 0
            checks["repairs_accounted"] = len(starts) == 21 + sum(a["repair_attempted"] for a in actions)
            checks["request_response_provenance"] = True
            checks["cumulative_ledger_charge_match"] = True
            finished = {e["attempt_id"]: e for e in finishes}
            identity = manifest.get("budget_id", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
                raise ValueError("Missing valid cumulative ledger identity.")
            ledger_path = ROOT / "results/budgets" / (identity + ".sqlite")
            with closing(sqlite3.connect(ledger_path.resolve().as_uri() + "?mode=ro", uri=True)) as ledger:
                settled = {s["attempt_id"]: ledger.execute("SELECT status,actual_nanos,model,run_id FROM attempts WHERE id=?", (s["attempt_id"],)).fetchone() for s in starts}
            for start in starts:
                path = run / "attempts" / start["attempt_id"]
                request, response = read(path / "request.json"), read(path / "response.json")
                digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                finish = finished[start["attempt_id"]]
                checks["request_response_provenance"] &= (digest == start["request_sha256"] == finish["request_sha256"]
                    and response["id"] == finish["response_id"] and response["usage"] == finish["usage"]
                    and response["model"] == finish["returned_model"] and start["context"]["episode_id"] == manifest["episode_id"]
                    and start["purpose"] == purpose and start["provider"] == study["gateway"]["provider"])
                row = settled[start["attempt_id"]]
                checks["cumulative_ledger_charge_match"] &= (row is not None and row[0] == "settled"
                    and row[1] == int(Decimal(str(finish["cost_usd"])) * Decimal(1000000000))
                    and row[2] == request["model"] and row[3] == run.name)
                by_day[start["context"]["case_id"]].append((request, response))
            checks["exact_decision_dates"] = set(by_day) == set(days)
        else:
            checks["no_paid_fixture_attempts"] = not events and not (run / "budget_summary.json").exists()
        if not all(checks.values()):
            return _report(report, checks)
        # Reprepare from frozen raw data, not a possibly altered saved episode CSV.
        with tempfile.TemporaryDirectory(dir=ROOT / ".cache") as temporary:
            temporary = Path(temporary)
            prepared = temporary / "inputs"
            selected = manifest["series"]
            prepared_manifest = prepare_dataset(ROOT / study["dataset"]["path"], prepared, store_id=selected["store_id"],
                            product_ids=[selected["product_id"]], episode_start=design["windows"][window]["start"])
            checks["frozen_raw_dataset"] = prepared_manifest["raw_sha256"] == study["dataset"]["sha256"]
            env = KaggleRetailEnvironment(prepared, temporary / "replay", manifest["scenario"])
            initial_net_worth = env.funds + env.inventory.compute_net_worth(env.current_date)
            checks.update(exact_shared_observation_sent=True, all_actions_valid=True,
                saved_observations_match_replay=True, saved_policy_decisions_match_replay=True,
                private_demand_hidden_every_day=True, scenario_hidden_except_current_leadtime=True)
            replay_flags = []
            for observation_record, action in zip(observations, actions):
                observation = env.observe()
                original_demand = env._episode["Demand"].copy()
                env._episode.loc[:, "Demand"] = 1000000
                checks["private_demand_hidden_every_day"] &= env.observe() == observation
                env._episode.loc[:, "Demand"] = original_demand
                original_scenario = env.scenario
                for hidden_scenario in design["scenarios"]:
                    env.scenario = hidden_scenario
                    alternate = env.observe()
                    expected_lead = design["assumptions"]["disrupted_lead_days"] if hidden_scenario == "delivery_disruption" and env._active_shock(env.current_date) else design["assumptions"]["lead_days"]
                    checks["scenario_hidden_except_current_leadtime"] &= (alternate["lead_days"] == expected_lead
                        and {k: v for k, v in alternate.items() if k != "lead_days"} == {k: v for k, v in observation.items() if k != "lead_days"})
                env.scenario = original_scenario
                checks["saved_observations_match_replay"] &= observation_record["observation"] == observation
                try:
                    validate_actions(action["actions"], observation)
                except (ValueError, TypeError, KeyError):
                    checks["all_actions_valid"] = False
                    raise
                if kind == "baseline":
                    expected_action = choose_actions(observation, policy)
                    detail = dict(source=policy, fallback_used=False, repair_attempted=False, invalid_responses=0)
                else:
                    observed_responses = iter(by_day[action["date"]] if kind == "genuine_llm" else action["responses"])
                    def create(**kwargs):
                        item = next(observed_responses)
                        if kind == "genuine_llm":
                            request, response = item
                            if kwargs != request:
                                checks["exact_shared_observation_sent"] = False
                                raise ValueError("Saved request differs from the frozen policy and replay observation.")
                            choices = [SimpleNamespace(finish_reason=c.get("finish_reason"), message=SimpleNamespace(**c["message"])) for c in response["choices"]]
                        else:
                            choices = [SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=item))]
                        return SimpleNamespace(choices=choices)
                    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
                    expected_action, detail = LLMPolicy(client, design["model"])(observation)
                    if next(observed_responses, None) is not None:
                        raise ValueError("Unused saved response; repair accounting differs.")
                checks["saved_policy_decisions_match_replay"] &= expected_action == action["actions"] and all(action[k] == v for k, v in detail.items())
                replay_flags.append(detail)
                apply_actions(env, observation, action["actions"])
            replayed = pd.DataFrame(env.ledger)
            checks["saved_daily_ledger_matches_replay"] = _same_frame(replayed, frame)
            final_net_worth = env.funds + env.inventory.compute_net_worth(env.current_date) + sum(o.cost for o in env.order_manager.get_current_orders())
            checks["cash_reconciles"] = math.isclose(env.funds, summary["final_funds"], abs_tol=1e-6, rel_tol=0)
            checks["contribution_reconciles"] = (math.isclose(float(replayed["contribution"].sum()), summary["contribution"], abs_tol=1e-6, rel_tol=0)
                and math.isclose(final_net_worth - initial_net_worth, summary["net_worth_change"], abs_tol=1e-6, rel_tol=0)
                and math.isclose(final_net_worth - initial_net_worth, summary["contribution"], abs_tol=1e-6, rel_tol=0))
            checks["repair_fallback_exports"] = True
            for flag in ("repair_attempted", "fallback_used", "invalid_responses"):
                values = [r[flag] for r in replay_flags]
                count_key = {"repair_attempted": "repair_days", "fallback_used": "fallback_days", "invalid_responses": "invalid_responses"}[flag]
                checks["repair_fallback_exports"] &= values == frame[flag].tolist() and sum(values) == summary[count_key]
            checks["summary_service_inventory"] = (summary["decision_opportunities"] == 21 and summary["products"] == 1
                and math.isclose(summary["revenue"], float(replayed["revenue"].sum()), abs_tol=1e-6, rel_tol=0)
                and math.isclose(summary["fill_rate"], float(replayed["sales"].sum() / replayed["demand"].sum()) if replayed["demand"].sum() else 1, abs_tol=1e-9, rel_tol=0)
                and summary["stockout_sku_days"] == int((replayed["lost_sales"] > 0).sum())
                and math.isclose(summary["mean_closing_inventory"], float(replayed["closing_inventory"].mean()), abs_tol=1e-6, rel_tol=0))
        report.update(api_attempts=len(starts), estimated_gateway_credit_usd=sum(e.get("cost_usd") or 0 for e in finishes),
            initial_observation_sha256=observations[0]["sha256"], prepared_checksums_sha256=manifest.get("prepared_checksums_sha256"),
            base_demand_sha256=hashlib.sha256(frame[["date", "sku_id", "base_demand"]].to_csv(index=False).encode()).hexdigest())
        report["evidence_sha256"] = episode_evidence_digest(run)
    except (ValueError, KeyError, OSError, sqlite3.Error, TypeError, AssertionError, StopIteration, IndexError) as exc:
        checks["complete_readable_replay_evidence"] = False
        report["error_type"] = type(exc).__name__
    return _report(report, checks)
