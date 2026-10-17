"""Bounded native-run plans; dry-run needs no credentials or API access."""
import csv
import json
from pathlib import Path

from .common import ROOT, TASKS, settings


def run_plan(task, *, config_path=None, purpose=None, case_limit=None):
    if task not in TASKS:
        raise ValueError("Unknown native task.")
    base = settings()
    specification = (config_path if isinstance(config_path, dict) else
                     json.loads(Path(config_path).read_text(encoding="utf-8")) if config_path else {})
    purpose = purpose or specification.get("purpose", "evaluation")
    if purpose not in ("pilot", "evaluation"):
        raise ValueError("Purpose must be pilot or evaluation.")
    overrides = specification.get("settings", {})
    if any(k not in base for k in overrides):
        raise ValueError("Unknown benchmark setting override.")
    if purpose == "pilot" and any(k not in {"retail_days", "icbe_rounds", "max_api_calls_per_task",
                                           "max_output_tokens", "request_timeout_seconds"} for k in overrides):
        raise ValueError("Pilot overrides may bound diagnostic work, not silently substitute models or methods.")
    config = {**base, **overrides}
    if purpose == "evaluation" and any(config[k] != v for k, v in base.items()):
        raise ValueError("Evaluation must retain the frozen native settings; record a design amendment first.")
    case_limit = case_limit if case_limit is not None else specification.get("case_limit")
    if purpose == "pilot":
        case_limit = 1 if case_limit is None else case_limit
        if type(case_limit) is not int or case_limit != 1:
            raise ValueError("The initial native pilot uses exactly one case/scenario for case-based tasks.")
    elif case_limit is not None:
        raise ValueError("Do not silently reduce evaluation coverage with a case limit.")
    for name in ("retail_days", "retail_strategy_turns", "retail_execution_turns", "consulting_cases",
                 "consulting_turns", "icbe_rounds", "max_api_calls_per_task", "max_output_tokens", "workers"):
        if type(config[name]) is not int or config[name] < 1:
            raise ValueError(f"{name} must be a positive integer.")
    if config["workers"] != 1:
        raise ValueError("Start with one native worker; budget/logging validation precedes parallel expansion.")
    if purpose == "pilot" and (config["retail_days"] > 1 or config["icbe_rounds"] > 2):
        raise ValueError("Initial pilots are bounded to one Retail day and two ICBE rounds.")
    with (ROOT / "docs/results/native_case_manifest.csv").open(encoding="utf-8") as stream:
        cases = list(csv.DictReader(stream))
    selected = [r for r in cases if r["task"] == task]
    if case_limit is not None:
        selected = selected[:case_limit]
    count = len(selected)
    horizon = None
    if task.startswith("retail:"):
        count, horizon = 1, config["retail_days"]
    elif task == "firm:beergame":
        count, horizon = (1 if purpose == "pilot" else 2), 25
    elif task == "firm:edt":
        count, horizon = 1, 96
    elif task == "icbe":
        count, horizon = 6, config["icbe_rounds"]
    return {"task": task, "purpose": purpose, "settings": config, "case_limit": case_limit,
            "selected_case_ids": [c["case_id"] for c in selected],
            "expected_units": count, "configured_horizon": horizon,
            "pilot_qualification": "Diagnostic subset only; no full native evaluation claim." if purpose == "pilot" else None,
            "paid_calls_authorized_by_plan": False}
