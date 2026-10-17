"""Shared configuration and gateway clients; never persist credentials in results."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = [
    *[f"retail:{kind}" for kind in ("dynamic_middle", "dynamic_hard", "still_middle", "still_hard")],
    *[f"firm:{name}" for name in ("FinCode", "CodeFinQA", "CodeTAT-QA", "SEC-NUM", "TAT-QA", "ConvFinQA", "FinKnow", "FormulaEval", "finer", "formula", "factset")],
    "firm:consulting", "firm:beergame", "firm:edt", "icbe",
]


def settings():
    return json.loads((ROOT / "configs/benchmarks.json").read_text(encoding="utf-8"))


def credentials():
    from dotenv import dotenv_values
    values = dotenv_values(ROOT / ".env")
    key = values.get("SHOPAIKEY_API_KEY") or os.getenv("SHOPAIKEY_API_KEY")
    base = values.get("SHOPAIKEY_BASE_URL") or os.getenv("SHOPAIKEY_BASE_URL")
    if not key or not base:
        raise RuntimeError("Set SHOPAIKEY_API_KEY and SHOPAIKEY_BASE_URL in the ignored project .env.")
    if not base.startswith("https://"):
        raise RuntimeError("The gateway endpoint must use HTTPS.")
    return key, base.rstrip("/")


def verify_sources():
    pins = json.loads((ROOT / "configs/sources.json").read_text(encoding="utf-8"))
    vendors = {"RetailBench": pins["retailbench"], "FirmBench": pins["reference_repositories"]["FirmBench"],
               "icbe-2026-strategic-behavior": pins["reference_repositories"]["ICBE"]}
    for name, pin in vendors.items():
        path = ROOT / "vendor" / name
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=path, text=True).strip()
        if head != pin["commit"] or dirty:
            raise RuntimeError(f"{name} must be at the unchanged commit recorded in configs/sources.json.")


# Re-export fatal exceptions for existing launchers and integration tests.
from .errors import CallLimitReached, GatewayFailure, BudgetStop, DecisionFailure


def install_gateway_clients(output: Path, config: dict, *, offline=False, budget=None):
    """Install isolated worker clients; offline calls block, paid calls need a ledger."""
    from .gateway import install_clients
    return install_clients(output, config, credential_loader=credentials, offline=offline, budget=budget)
