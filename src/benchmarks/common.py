"""Shared configuration and gateway clients; never persist credentials in results."""
from __future__ import annotations

import json
import os
import threading
import subprocess
from datetime import datetime, timezone
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


class CallLimitReached(BaseException):
    """Abort rather than let vendor retry loops turn a limit into a fallback answer."""


class GatewayFailure(BaseException):
    """Stop a native run on API failure instead of scoring a fabricated decision."""


def install_gateway_clients(output: Path, config: dict, *, offline=False):
    """Override native client construction only inside the worker process.

    Force the configured gateway (including Consulting's hard-coded endpoint),
    cap outputs, bound request retries/time, and record token usage without keys.
    Offline checks cannot make paid calls even if a vendor tries to do so.
    """
    import openai
    key, base = ("offline-check-only", "https://offline.invalid/v1") if offline else credentials()
    os.environ.update(OPENAI_API_KEY=key, OPENAI_URL=base, OPENAI_BASE_URL=base,
                      OPENAI_AGENTS_DISABLE_TRACING="1", PYTHONIOENCODING="utf-8")
    original_sync, original_async = openai.OpenAI, openai.AsyncOpenAI
    lock = threading.Lock()
    counts = {"attempts": 0, "completed": 0, "input_tokens": 0, "output_tokens": 0, "missing_usage_responses": 0}

    def prepare(kwargs):
        if offline:
            raise CallLimitReached("Offline readiness checks attempted an API call.")
        with lock:
            if counts["attempts"] >= config["max_api_calls_per_task"]:
                raise CallLimitReached("Configured API call limit reached; run is incomplete.")
            counts["attempts"] += 1
        kwargs = dict(kwargs)
        limit = kwargs.pop("max_completion_tokens", kwargs.get("max_tokens", config["max_output_tokens"]))
        kwargs["max_tokens"] = min(int(limit), config["max_output_tokens"])
        kwargs["timeout"] = config["request_timeout_seconds"]
        if str(kwargs.get("model", "")).startswith(("gpt-4.1", "gpt-4o")):
            kwargs.pop("reasoning_effort", None)  # Native Consulting sends this to every model.
            if "extra_body" in kwargs:
                kwargs["extra_body"] = {k: v for k, v in kwargs["extra_body"].items() if k != "enable_thinking"}
        return kwargs

    def record(response, kwargs):
        usage = getattr(response, "usage", None)
        with lock:
            counts["completed"] += 1
            counts["missing_usage_responses"] += int(usage is None)
            counts["input_tokens"] += int(getattr(usage, "prompt_tokens", 0) or 0)
            counts["output_tokens"] += int(getattr(usage, "completion_tokens", 0) or 0)
            payload = {"time": datetime.now(timezone.utc).isoformat(), "requested_model": kwargs["model"],
                       "returned_model": getattr(response, "model", None), **counts}
            with (output / "api_usage.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload) + "\n")
        return response

    class SyncClient(original_sync):
        def __init__(self, *args, **kwargs):
            for name in ("api_key", "base_url", "max_retries", "timeout"):
                kwargs.pop(name, None)
            super().__init__(*args, api_key=key, base_url=base, max_retries=0,
                             timeout=config["request_timeout_seconds"], **kwargs)
            create = self.chat.completions.create

            def wrapped(**params):
                params = prepare(params)
                try:
                    response = create(**params)
                except openai.APIError as exc:
                    raise GatewayFailure(f"Gateway API error HTTP {getattr(exc, 'status_code', 'connection')}") from None
                if not params.get("stream"):
                    return record(response, params)

                def chunks():
                    last = None
                    try:
                        for chunk in response:
                            last = chunk
                            yield chunk
                        record(last, params)
                    except openai.APIError as exc:
                        raise GatewayFailure(f"Gateway stream error HTTP {getattr(exc, 'status_code', 'connection')}") from None
                    finally:
                        response.close()
                return chunks()
            self.chat.completions.create = wrapped

    class AsyncClient(original_async):
        def __init__(self, *args, **kwargs):
            for name in ("api_key", "base_url", "max_retries", "timeout"):
                kwargs.pop(name, None)
            super().__init__(*args, api_key=key, base_url=base, max_retries=0,
                             timeout=config["request_timeout_seconds"], **kwargs)
            create = self.chat.completions.create

            async def wrapped(**params):
                params = prepare(params)
                try:
                    response = await create(**params)
                except openai.APIError as exc:
                    raise GatewayFailure(f"Gateway API error HTTP {getattr(exc, 'status_code', 'connection')}") from None
                if not params.get("stream"):
                    return record(response, params)

                async def chunks():
                    last = None
                    try:
                        async for chunk in response:
                            last = chunk
                            yield chunk
                        record(last, params)
                    finally:
                        await response.close()
                return chunks()
            self.chat.completions.create = wrapped

    openai.OpenAI, openai.AsyncOpenAI = SyncClient, AsyncClient
    return counts
