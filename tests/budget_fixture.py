"""Synthetic allowances for mocked transports; never authorize a real gateway."""
from pathlib import Path

from src.benchmarks.budget import BudgetLedger


def manifest(cap=1, attempts=100):
    return {"budget_id": "mock_only", "approved": True, "approval_reference": "offline mock-transport test",
            "currency": "USD_gateway_credit", "rates_verified": True,
            "rates_source": "https://gateway.example/mock-pricing", "base_url": "https://gateway.example/v1",
            "cap_usd": cap, "scope_caps_usd": {"native": cap}, "max_attempts": attempts,
            "max_input_tokens_bound": 100000, "max_output_tokens": 4096, "protocol_token_allowance": 4096,
            "allowed_purposes": ["pilot"],
            "rates": {m: {"input_per_million": 1, "output_per_million": 2}
                      for m in ["test", "gpt-4.1-mini", "gpt-4.1-mini-2025-04-14", "gpt-4o-mini-2024-07-18", "deepseek-v3.2"]}}


def ledger(directory, *, cap=1, attempts=100, run_id="mock-run"):
    return BudgetLedger(manifest(cap, attempts), Path(directory) / "budget.sqlite", run_id=run_id)
