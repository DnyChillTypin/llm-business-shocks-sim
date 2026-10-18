"""Extract only analysis fields from saved primary evidence; no client construction."""
import json

import pandas as pd

from src.benchmarks.common import ROOT
from src.experiments.kaggle_protocol import read, primary_matrix, episode_evidence_digest


def extract_primary(study):
    matrix = primary_matrix(study)
    planned = {e["episode_id"]: i for i, e in enumerate(matrix["episodes"])}
    actions, attempts, sources = [], [], []
    seen = set()
    for path in (ROOT / "results/runs/kaggle_retailbench").glob("*/run_manifest.json"):
        m = read(path)
        if m.get("episode_id") not in planned:
            continue
        index = planned[m["episode_id"]]
        if index in seen or m["status"] != "validated_complete":
            raise ValueError("Duplicate or incomplete primary cohort; inspect before analysis.")
        seen.add(index)
        run = path.parent
        v = read(run / "validation.json")
        if v["status"] != "validated_complete" or not all(v["checks"].values()) or v["evidence_sha256"] != episode_evidence_digest(run):
            raise ValueError("Primary evidence is not bound to its passing saved replay.")
        sources.append(dict(matrix_index=index, private_folder=str(run), evidence_sha256=v["evidence_sha256"]))
        lines = lambda name: [json.loads(s) for s in (run / name).read_text(encoding="utf-8").splitlines()]
        observed = {r["date"]: r["observation"] for r in lines("observations.jsonl")}
        meta = dict(matrix_index=index, store_id=m["series"]["store_id"], product_id=m["series"]["product_id"], scenario=m["scenario"], policy=m["policy"])
        for record in lines("actions.jsonl"):
            obs = observed[record["date"]]
            sku = m["series"]["product_id"]
            p, a = obs["products"][sku], record["actions"][sku]
            actions.append({**meta, "date": record["date"], "order_quantity": a["order_quantity"], "price_multiplier": a["price_multiplier"],
                "observed_funds": obs["funds"], "observed_inventory": p["inventory"], "observed_on_order": p["on_order"],
                "unit_cost": p["unit_cost"], "reference_price": p["reference_price"], "lead_days": obs["lead_days"]})
        if m["policy"] == "llm_with_fallback":
            for event in lines("api_attempts.jsonl"):
                if event["event"] != "finished":
                    continue
                logical = event["logical_request_id"]
                if not (logical.endswith(":repair:0") or logical.endswith(":repair:1")):
                    raise ValueError("Unknown logical request role; do not guess primary/repair accounting.")
                attempts.append({**meta, "date": event["context"]["case_id"],
                    "request_kind": "primary" if logical.endswith(":repair:0") else "repair",
                    "input_tokens": event["usage"]["prompt_tokens"], "output_tokens": event["usage"]["completion_tokens"],
                    "latency_seconds": event["latency_seconds"], "cost_credits": event["cost_usd"], "model": event["returned_model"]})
    if seen != set(range(36)):
        raise ValueError("Missing primary episodes.")
    return pd.DataFrame(actions), pd.DataFrame(attempts), sources
