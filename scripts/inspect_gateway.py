"""Read-only model access, sanitized balance and public gateway tariff snapshot.

No completion requests. Never print full usage responses, request URLs containing
the key, exception text, key labels or account metadata.
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.benchmarks.common import credentials, settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--history", action="store_true", help="Include sanitized recent request-cost rows from the provider's public history interface.")
    args = parser.parse_args()
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).disabled = True
    key, base = credentials()
    if base != "https://api.shopaikey.com/v1":
        raise SystemExit("This inspector is restricted to the configured ShopAIKey host.")
    config = settings()
    models = list(dict.fromkeys([config["primary_model"], config["judge_model"], *config["icbe_models"]]))
    result = {"provider": "ShopAIKey", "base_url": base, "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "paid_api_calls": 0, "currency": "USD_gateway_credit",
              "sources": ["https://shopaikey.com/en", "https://api.shopaikey.com/pricing"],
              "balance_endpoint": "https://api.shopaikey.com/usage (credential query omitted)",
              "balance_precision": "Provider returned values; do not assume fine-grained billing precision.",
              "rates_include_group_ratio": "Use the model input/completion fields as displayed by the provider; do not multiply group ratio twice."}
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.get("https://api.shopaikey.com/usage", params={"apiKey": key})
            response.raise_for_status()
            usage = response.json()
            pricing = client.get("https://api.shopaikey.com/pricing")
            pricing.raise_for_status()
            catalog = pricing.json()
            groups = {g.strip() for g in (usage.get("group_name") or "").split(",")}
            matches = [g for g in catalog["groups"] if g["name"] in groups or g.get("label") in groups]
            if not matches:
                raise ValueError("Cannot identify an applicable public tariff group.")
            result["groups"] = [{k: g[k] for k in ("name", "label", "ratio")} for g in matches]
            result["balance"] = {k: v for k, v in usage.items() if k in {"total", "used", "balance", "remaining"}
                                  and type(v) in (int, float)}
            result["pricing_version"] = catalog.get("pricing_version")
            rates = {}
            for model in models:
                rows = [r for g in matches for r in g["models"] if r["name"] == model]
                if not rows or any(r.get("quotaType", 0) != 0 for r in rows):
                    raise ValueError("One configured model lacks an applicable token tariff.")
                rates[model] = {"input_per_million": max(r["input"] for r in rows),
                                "output_per_million": max(r["completion"] for r in rows),
                                "per_request": 0, "rate_rule": "maximum across key-accessible groups; uncached upper estimate"}
            result["rates"] = rates
            response = client.get(base + "/models", headers={"Authorization": "Bearer " + key})
            response.raise_for_status()
            available = {m["id"] for m in response.json()["data"]}
            result["missing_models"] = [m for m in models if m not in available]
            result["rates_verified"] = not result["missing_models"]
            if args.history:
                response = client.post("https://api.shopaikey.com/usage/histories",
                                       headers={"x-api-key": key}, json={"page": 1, "page_size": 100})
                response.raise_for_status()
                history = response.json()
                if history.get("success") is not True:
                    raise ValueError("History endpoint did not return success.")
                data = history["data"]
                allowed = {"created_at", "model_name", "prompt_tokens", "completion_tokens", "cost", "type"}
                result["history"] = {"source": "https://api.shopaikey.com/usage/histories", "total": data.get("total"),
                    "stats": {k: v for k, v in (data.get("stats") or {}).items() if type(v) in (int, float)},
                    "items": [{k: v for k, v in row.items() if k in allowed} for row in data.get("items", [])],
                    "qualification": "Provider account history; absent entries do not prove an unlogged failed request was unbilled."}
    except Exception as exc:
        # str(exc) may contain the credential-bearing /usage URL.
        result = {"status": "failed", "error_type": type(exc).__name__, "paid_api_calls": 0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return int(result.get("status") == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
