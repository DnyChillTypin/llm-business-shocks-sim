"""Development-only preparation and explicit scripted completions; never a model."""
import json
from pathlib import Path
from types import SimpleNamespace

from src.agents.baselines import choose_actions
from src.agents.llm import LLMPolicy
from src.data.kaggle import prepare_dataset
from src.research.report2 import ROOT, PROTOCOL, read_json


def prepare_case(case, output, elasticity=1.5):
    protocol = read_json(ROOT / PROTOCOL)
    if case not in protocol["sampling"]["development_cases"]:
        raise ValueError("Milestone 2 fixtures may use only the frozen development cases.")
    if elasticity not in [1.5, 0.75, 2.25]:
        raise ValueError("Undeclared elasticity setting.")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    settings = read_json(ROOT / "configs/kaggle_retailbench.json")
    settings["elasticity"] = elasticity
    config = output / "settings.json"
    config.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    prepared = output / "inputs"
    prepare_dataset(ROOT / protocol["dataset"]["path"], prepared, config_path=config,
                    store_id=case["store_id"], product_ids=[case["product_id"]], episode_start=case["start"])
    return prepared


def scripted_policy(settings):
    """Force one repaired day and one fallback day, then valid adaptive actions."""
    calls = []
    dates = []

    def create(**kwargs):
        observation = json.loads(kwargs["messages"][1]["content"])
        if observation["date"] not in dates:
            dates.append(observation["date"])
        day = dates.index(observation["date"])
        repaired = len(kwargs["messages"]) > 2
        invalid = (day == 0 and not repaired) or day == 1
        text = "invalid scripted fixture JSON" if invalid else json.dumps(choose_actions(observation, "adaptive"))
        calls.append({"kind": "scripted_not_model", "date": observation["date"], "repair": repaired})
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=text))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return LLMPolicy(client, settings), calls
