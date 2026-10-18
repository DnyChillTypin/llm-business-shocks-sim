"""Clearly labeled validation-only fixtures, with no credential or SDK access."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from src.agents.baselines import choose_actions
from src.agents.llm import LLMPolicy
from src.experiments.kaggle import append, run_episode
from src.experiments.kaggle_protocol import episode_id, write
from src.research.design import canonical_hash


def run_validation_fixture(study, prepared, run, series, scenario, policy):
    if policy not in {"fixed", "adaptive", "scripted_fixture"}:
        raise ValueError("Validation fixtures cannot invoke a genuine model policy.")
    prepared, run = Path(prepared), Path(run)
    source = json.loads((prepared / "manifest.json").read_text())
    if source["test_start"] != study["kaggle"]["windows"]["validation_pilot"]["start"]:
        raise ValueError("Offline fixtures must not consume the primary evaluation window.")
    run.mkdir(parents=True, exist_ok=False)
    episode = dict(series=series, scenario=scenario, policy=policy, window="validation_pilot", purpose="offline_validation")
    manifest = {**episode, "episode_id": episode_id(episode), "status": "running", "expected_days": 21,
        "primary_evaluation": False, "agent_kind": "scripted" if policy == "scripted_fixture" else "baseline",
        "study_sha256": canonical_hash(study),
        "prepared_checksums_sha256": hashlib.sha256((prepared / "artifact_checksums.json").read_bytes()).hexdigest()}
    write(run / "run_manifest.json", manifest)
    decide = None
    if policy == "scripted_fixture":
        def create(**kwargs):
            observation = json.loads(kwargs["messages"][1]["content"])
            day = int(observation["date"][-2:]) - 1  # Validation begins on April 2.
            repaired = len(kwargs["messages"]) > 2
            invalid = (day == 2 and not repaired) or day == 3
            text = "deliberately invalid fixture JSON" if invalid else json.dumps(choose_actions(observation, "adaptive"))
            append(run / "fixture_requests.jsonl", {"date": observation["date"], "request": kwargs, "response": text,
                "kind": "scripted_not_a_model_response"})
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=text))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        decide = LLMPolicy(client, study["kaggle"]["model"])
    try:
        frame, summary = run_episode(prepared, run, scenario=scenario, policy=policy, decide=decide)
        manifest.update(status="execution_finished_requires_artifact_review", completed_days=summary["days"])
        return frame, summary
    except BaseException as exc:
        manifest.update(status="incomplete", failure_category=type(exc).__name__)
        raise
    finally:
        write(run / "run_manifest.json", manifest)
