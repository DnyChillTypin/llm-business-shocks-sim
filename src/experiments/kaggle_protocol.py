"""Frozen episode identities and fail-closed Kaggle execution gates; no transport."""
import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path

from src.benchmarks.common import ROOT
from src.research.design import canonical_hash

PRIMARY_TASK = "kaggle:primary_matrix"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def episode_id(episode):
    # Preserve exactly the identity introduced with the genuine Stage 2 pilots.
    descriptor = {k: episode[k] for k in ("series", "scenario", "policy", "window", "purpose")}
    return canonical_hash({**descriptor, "frozen_design_sha256": canonical_hash(read(ROOT / "docs/results/study_design_manifest.json"))})


def primary_matrix(study):
    design = study["kaggle"]
    episodes = []
    for series in design["selection"]["selected_series"]:
        for scenario in design["scenarios"]:
            for policy in design["policy_ids"]:
                item = dict(series=series, scenario=scenario, policy=policy, window="primary_evaluation", purpose="evaluation")
                episodes.append({**item, "episode_id": episode_id(item)})
    return {"study_id": study["study_id"], "study_sha256": canonical_hash(study),
            "horizon": design["horizon_days"], "episodes": episodes}


def authorization_template(matrix):
    return {"approved": False, "purpose": "evaluation", "task_id": PRIMARY_TASK,
            "matrix_sha256": canonical_hash(matrix), "study_sha256": matrix["study_sha256"],
            "episode_ids": [e["episode_id"] for e in matrix["episodes"] if e["policy"] == "llm_with_fallback"],
            "budget_id": None, "max_episodes": 12, "max_primary_decisions": 252, "max_attempts": 504,
            "qualification": "Template only; no paid authorization. Use the existing cumulative budget ledger and scope."}


def require_primary_authorization(authorization, allowance, matrix):
    expected = authorization_template(matrix)
    if authorization.get("approved") is not True or allowance.get("approved") is not True:
        raise ValueError("Primary execution needs an explicitly approved run manifest and allowance.")
    for field in ("purpose", "task_id", "matrix_sha256", "study_sha256", "episode_ids",
                  "max_episodes", "max_primary_decisions", "max_attempts"):
        if authorization.get(field) != expected[field]:
            raise ValueError("Primary run authorization differs from the frozen matrix or attempt ceiling.")
    if (not authorization.get("budget_id") or authorization["budget_id"] != allowance.get("budget_id")
            or "evaluation" not in allowance.get("allowed_purposes", [])
            or PRIMARY_TASK not in allowance.get("allowed_tasks", [])
            or PRIMARY_TASK not in allowance.get("evaluation_tasks", [])
            or allowance.get("scope_caps_usd", {}).get("kaggle", 0) <= 0):
        raise ValueError("The cumulative allowance does not authorize the primary Kaggle task and scope.")


def text_digest(path):
    return hashlib.sha256(Path(path).read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def require_existing_ledger(allowance, directory=None):
    identity = allowance.get("budget_id", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
        raise ValueError("Invalid cumulative budget identity.")
    path = (Path(directory) if directory else ROOT / "results/budgets") / (identity + ".sqlite")
    if not path.is_file():
        raise ValueError("Primary evaluation must carry forward an existing ledger, not create a fresh allowance.")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0:
            raise ValueError("Primary evaluation cannot reset pilot spending to an empty ledger.")


def failure_evidence_digest(path):
    path = Path(path)
    names = ("run_manifest.json", "actions.jsonl", "observations.jsonl", "api_attempts.jsonl")
    return canonical_hash({name: text_digest(path / name) if (path / name).exists() else None for name in names})


def episode_evidence_digest(path):
    path = Path(path)
    manifest = read(path / "run_manifest.json")
    names = ("actions.jsonl", "observations.jsonl", "daily_results.csv", "summary.json", "api_attempts.jsonl")
    files = {name: text_digest(path / name) if (path / name).exists() else None for name in names}
    for name in sorted((path / "attempts").glob("*/*.json")):
        files[name.relative_to(path).as_posix()] = text_digest(name)
    descriptor = {k: manifest.get(k) for k in ("episode_id", "series", "scenario", "policy", "window", "purpose",
                  "study_sha256", "expected_days", "agent_kind", "primary_evaluation", "budget_id")}
    return canonical_hash({"descriptor": descriptor, "files": files})


def require_matching_baselines(root, episode):
    matching = {}
    for folder, manifest in prior_runs(root):
        if (manifest.get("purpose") == "evaluation" and manifest.get("window") == "primary_evaluation"
                and manifest.get("series") == episode["series"] and manifest.get("scenario") == episode["scenario"]
                and manifest.get("policy") in {"fixed", "adaptive"} and manifest.get("status") == "validated_complete"):
            path = folder / "validation.json"
            validation = read(path) if path.exists() else {}
            if (validation.get("status") == "validated_complete" and all(validation.get("checks", {}).values())
                    and validation.get("evidence_sha256") == episode_evidence_digest(folder)
                    and manifest.get("episode_id") == episode_id(manifest)):
                if manifest["policy"] in matching:
                    raise ValueError("Multiple completed baseline realizations for one primary identity.")
                matching[manifest["policy"]] = validation
    if set(matching) != {"fixed", "adaptive"}:
        raise ValueError("Run and validate the matched primary baselines before spending on this LLM episode.")
    if (matching["fixed"]["initial_observation_sha256"] != matching["adaptive"]["initial_observation_sha256"]
            or matching["fixed"]["base_demand_sha256"] != matching["adaptive"]["base_demand_sha256"]):
        raise ValueError("Primary baseline initial conditions or exogenous paths do not match.")


def prior_runs(root):
    return [(p.parent, read(p)) for p in sorted(Path(root).glob("*/run_manifest.json"))]


def require_episode_available(root, identity, *, retry_failed=False):
    previous = [(p, m) for p, m in prior_runs(root) if m.get("episode_id") == identity]
    for path, manifest in previous:
        if manifest.get("status") != "incomplete":
            raise ValueError("Episode already completed or has an active/unreviewed attempt; no duplicate execution.")
        if not retry_failed:
            raise ValueError("Interrupted episodes require an inspected fresh-episode retry, never partial resume.")
        review_path = path / "failure_review.json"
        review = read(review_path) if review_path.exists() else {}
        if (review.get("status") != "reviewed" or review.get("decision") != "restart_complete_episode"
                or review.get("run_manifest_sha256") != text_digest(path / "run_manifest.json")
                or review.get("evidence_sha256") != failure_evidence_digest(path)):
            raise ValueError("Failed episode needs a review bound to its unchanged saved manifest.")
    return [p.name for p, _ in previous]


def require_fallback_reviews(root):
    for path, manifest in prior_runs(root):
        if manifest.get("purpose") == "evaluation" and manifest.get("policy") == "llm_with_fallback" and manifest.get("status") != "validated_complete":
            review_path = path / "failure_review.json"
            review = read(review_path) if review_path.exists() else {}
            if (manifest.get("status") != "incomplete" or review.get("status") != "reviewed"
                    or review.get("decision") not in {"restart_complete_episode", "retain_incomplete_episode"}
                    or review.get("evidence_sha256") != failure_evidence_digest(path)):
                raise ValueError("An interrupted primary episode needs evidence-bound review before any next paid episode.")
        if not manifest.get("fallback_review_required"):
            continue
        review_path, actions = path / "quality_review.json", path / "actions.jsonl"
        review = read(review_path) if review_path.exists() else {}
        if (not actions.exists() or review.get("status") != "reviewed"
                or review.get("decision") != "retain_frozen_operational_policy"
                or review.get("actions_sha256") != text_digest(actions)):
            raise ValueError("Fallback exceeded 5%; resolve the evidence-bound quality review before the next paid episode.")


def remaining_primary_attempts(root, matrix):
    identities = {e["episode_id"] for e in matrix["episodes"] if e["policy"] == "llm_with_fallback"}
    used = 0
    for path, manifest in prior_runs(root):
        if manifest.get("episode_id") in identities:
            journal = path / "api_attempts.jsonl"
            if journal.exists():
                # An incomplete line or malformed record stops execution rather than understating spending.
                used += sum(json.loads(line)["event"] == "started" for line in journal.read_text().splitlines())
    return max(0, 504 - used)


@contextmanager
def execution_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".kaggle_execution.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError("Another execution owns the Kaggle lock. Inspect stale process state before removing it.") from None
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def save_matrix_registry(root, matrix):
    path = Path(root) / ("matrix_" + canonical_hash(matrix) + ".json")
    if path.exists() and read(path).get("plan") != matrix:
        raise ValueError("Immutable primary matrix plan changed.")
    observed = {}
    ids = {e["episode_id"] for e in matrix["episodes"]}
    for folder, manifest in prior_runs(root):
        if manifest.get("episode_id") in ids:
            observed.setdefault(manifest["episode_id"], []).append({"folder": folder.name, "status": manifest["status"]})
    write(path, {"plan": matrix, "observed_attempts": observed})
    return path
