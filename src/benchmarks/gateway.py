"""Gateway adapters with durable attempt events, raw artifacts and budget reserves."""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from .budget import utc_now
from .errors import BudgetStop, CallLimitReached, DecisionFailure, GatewayFailure

CONTEXT = contextvars.ContextVar("benchmark_api_context", default={})


@contextmanager
def request_context(**values):
    token = CONTEXT.set({**CONTEXT.get(), **values})
    try:
        yield
    finally:
        CONTEXT.reset(token)


def dump(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return None


def fatal_accounting(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            raise BudgetStop("Attempt logging/accounting failed; paid execution stopped for reconciliation.") from None
    return guarded


class AttemptLog:
    def __init__(self, output: Path, config: dict, *, key, base, offline=False, budget=None):
        self.output, self.config = Path(output), config
        self.key, self.base, self.offline, self.budget = key, base, offline, budget
        self.output.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.repeats = {}
        self.counts = {"attempts": 0, "completed": 0, "failed": 0,
                       "input_tokens": 0, "output_tokens": 0, "missing_usage_responses": 0}

    def clean(self, value):
        if isinstance(value, str):
            return value.replace(self.key, "[REDACTED]") if self.key else value
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if isinstance(value, dict):
            return {k: ("[REDACTED]" if k.lower() in {"api_key", "authorization", "x-api-key"}
                        else self.clean(v)) for k, v in value.items()}
        return value

    @fatal_accounting
    def event(self, value):
        with self.lock:
            with (self.output / "api_attempts.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(self.clean(value), ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    @fatal_accounting
    def start(self, kwargs):
        if self.offline:
            raise CallLimitReached("Offline verification attempted a paid completion.")
        if self.budget is None:
            raise BudgetStop("No approved shared budget ledger; completion was not sent.")
        params = dict(kwargs)
        limit = params.pop("max_completion_tokens", params.get("max_tokens", self.config["max_output_tokens"]))
        params["max_tokens"] = min(int(limit), self.config["max_output_tokens"])
        if params["max_tokens"] < 1:
            raise BudgetStop("Output limit must be positive.")
        params["timeout"] = self.config["request_timeout_seconds"]
        if str(params.get("model", "")).startswith(("gpt-4.1", "gpt-4o")):
            params.pop("reasoning_effort", None)
            if "extra_body" in params:
                params["extra_body"] = {k: v for k, v in params["extra_body"].items() if k != "enable_thinking"}
        if params.get("stream"):
            params["stream_options"] = {**params.get("stream_options", {}), "include_usage": True}
        safe = self.clean({k: v for k, v in params.items() if k not in {"extra_headers", "timeout"}})
        encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True).encode("utf-8")
        prompt_hash = hashlib.sha256(encoded).hexdigest()
        # A conservative envelope, not a claim about the undisclosed tokenizer.
        # It includes serialized tool schemas and a declared protocol allowance.
        input_bound = len(encoded) + self.budget.manifest.get("protocol_token_allowance", 4096)
        with self.lock:
            if self.counts["attempts"] >= self.config["max_api_calls_per_task"]:
                raise CallLimitReached("Per-task attempt ceiling reached; run is incomplete.")
            context = {**self.config.get("_request_context", {}), **CONTEXT.get()}
            logical_id = context.get("logical_request_id") or prompt_hash
            retry_key = (logical_id, prompt_hash)
            retry_index = self.repeats.get(retry_key, 0)
            attempt_id = uuid.uuid4().hex
            reserve = self.budget.reserve(attempt_id, params["model"], input_bound, params["max_tokens"])
            self.repeats[retry_key] = retry_index + 1
            self.counts["attempts"] += 1
            folder = self.output / "attempts" / attempt_id
            folder.mkdir(parents=True)
            (folder / "request.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
            record = {"event": "started", "attempt_id": attempt_id, "attempt_index": self.counts["attempts"],
                      "logical_request_id": logical_id, "retry_index": retry_index,
                      "retry_index_source": "same logical ID and request hash in this process; SDK retries disabled",
                      "provider": "ShopAIKey", "base_url": self.base,
                      "requested_model": params["model"], "purpose": self.config.get("_purpose", "unknown"),
                      "run_id": self.config.get("_run_id", self.output.name), "context": context,
                      "request_sha256": prompt_hash, "started_at_utc": utc_now(),
                      "input_token_bound": input_bound, "output_token_bound": params["max_tokens"],
                      "reserved_cost_usd": reserve, "currency": self.budget.manifest["currency"]}
            self.event(record)
        return params, {"record": record, "folder": folder, "started": time.perf_counter(), "finished": False}

    @fatal_accounting
    def finish(self, state, *, response=None, error=None, chunks=None):
        if state["finished"]:
            return
        state["finished"] = True
        raw = dump(response)
        if raw is not None:
            (state["folder"] / "response.json").write_text(json.dumps(self.clean(raw), ensure_ascii=False, indent=2), encoding="utf-8")
        if chunks is not None:
            (state["folder"] / "stream_chunks.json").write_text(json.dumps(self.clean(chunks), ensure_ascii=False), encoding="utf-8")
        usage = raw.get("usage") if raw else None
        valid_usage = (isinstance(usage, dict) and type(usage.get("prompt_tokens")) is int
                       and type(usage.get("completion_tokens")) is int
                       and usage["prompt_tokens"] >= 0 and usage["completion_tokens"] >= 0)
        with self.lock:
            self.counts["completed"] += int(error is None)
            self.counts["failed"] += int(error is not None)
            self.counts["missing_usage_responses"] += int(not valid_usage)
            if valid_usage:
                self.counts["input_tokens"] += usage["prompt_tokens"]
                self.counts["output_tokens"] += usage["completion_tokens"]
            cost = self.budget.settle(state["record"]["attempt_id"],
                                      input_tokens=usage["prompt_tokens"] if valid_usage and not error else None,
                                      output_tokens=usage["completion_tokens"] if valid_usage and not error else None,
                                      uncertain_reason=error)
            record = {**state["record"], "event": "finished", "finished_at_utc": utc_now(),
                      "latency_seconds": time.perf_counter() - state["started"],
                      "status": "failed" if error else "completed", "failure_category": error,
                      "returned_model": raw.get("model") if raw else None,
                      "response_id": raw.get("id") if raw else None,
                      "usage": usage, "cost_usd": cost, "cost_source": self.budget.manifest["rates_source"],
                      "cost_kind": "observed tokens times applicable uncached gateway rates; upper estimate, not independently verified billing",
                      "provider_cost_fields": {k: v for k, v in (raw or {}).items() if "cost" in k.lower()},
                      "parse_status": "not_checked", "finish_reasons":
                      [c.get("finish_reason") for c in (raw or {}).get("choices", [])], **self.counts}
            self.event(record)
            with (self.output / "api_usage.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(self.clean(record), ensure_ascii=False) + "\n")
            (self.output / "budget_summary.json").write_text(json.dumps(self.budget.summary(), indent=2), encoding="utf-8")
        if not valid_usage and not error:
            raise BudgetStop("Completion usage is missing; reservation retained and subsequent calls blocked.")
        if self.budget.summary()["uncertain_attempts"] and not error:
            raise BudgetStop("Reported usage exceeded the declared envelope; review charging before more calls.")

    @fatal_accounting
    def validate(self, state, raw):
        choices = raw.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content")
        tool_calls = message.get("tool_calls")
        reason = choices[0].get("finish_reason") if choices else None
        problem = None
        parsed = None
        if reason in ("length", "content_filter"):
            problem = "truncated_or_filtered_completion"
        elif not choices or (not content and not tool_calls):
            problem = "empty_completion"
        elif tool_calls:
            try:
                for call in tool_calls:
                    if not isinstance(json.loads(call["function"]["arguments"]), dict):
                        raise ValueError()
            except (KeyError, ValueError, TypeError):
                problem = "invalid_tool_arguments"
        request = json.loads((state["folder"] / "request.json").read_text(encoding="utf-8"))
        kind = state["record"]["context"].get("validation_kind")
        if not problem and kind == "icbe" and not any(token in (content or "").upper() for token in ("OPTION A", "OPTION B")):
            problem = "unparseable_icbe_decision"
        requires_json = request.get("response_format", {}).get("type") in ("json_object", "json_schema") or kind in {"edt", "reasoning", "candidate", "judge", "beer"}
        if not problem and requires_json:
            try:
                parsed = json.loads(content or "")
                if not isinstance(parsed, dict):
                    raise ValueError()
                if kind == "reasoning" and ("final_answer" not in parsed or parsed["final_answer"] is None):
                    raise ValueError()
                if kind == "candidate" and (not isinstance(parsed.get("reply"), str) or not parsed["reply"].strip()):
                    raise ValueError()
                if kind == "judge" and any(type(parsed.get(k)) not in (int, float) or not 0 <= parsed[k] <= 10
                                             for k in ("structure", "quant", "business_sense", "communication", "overall")):
                    raise ValueError()
                if kind == "beer" and (type(parsed.get("order_qty")) is not int or not 0 <= parsed["order_qty"] <= 5000):
                    raise ValueError()
                if kind == "edt" and not {"C", "R", "P"}.issubset(parsed):
                    raise ValueError()
            except (ValueError, TypeError):
                problem = "invalid_json_or_required_decision_fields"
        self.event({"event": "parse_checked", "attempt_id": state["record"]["attempt_id"],
                    "parse_status": "invalid" if problem else "valid", "validation_kind": kind,
                    "failure_category": problem})
        if problem:
            raise DecisionFailure(problem)


def install_clients(output, config, *, credential_loader, offline=False, budget=None):
    import openai
    key, base = ("offline-check-only", "https://offline.invalid/v1") if offline else credential_loader()
    os.environ.update(OPENAI_API_KEY=key, OPENAI_URL=base, OPENAI_BASE_URL=base,
                      OPENAI_AGENTS_DISABLE_TRACING="1", PYTHONIOENCODING="utf-8")
    log = AttemptLog(output, config, key=key, base=base, offline=offline, budget=budget)
    original_sync, original_async = openai.OpenAI, openai.AsyncOpenAI

    def prepare_client(kwargs):
        kwargs = dict(kwargs)
        for name in ("api_key", "base_url", "max_retries", "timeout"):
            kwargs.pop(name, None)
        return dict(kwargs, api_key=key, base_url=base, max_retries=0, timeout=config["request_timeout_seconds"])

    def merge_chunks(chunks):
        model, usage, response_id = None, None, None
        choices = {}
        for chunk in chunks:
            model = chunk.get("model") or model
            usage = chunk.get("usage") or usage
            response_id = chunk.get("id") or response_id
            for choice in chunk.get("choices", []):
                target = choices.setdefault(choice.get("index", 0), {"message": {"content": "", "tool_calls": []}, "finish_reason": None})
                delta = choice.get("delta", {})
                target["message"]["content"] += delta.get("content") or ""
                target["finish_reason"] = choice.get("finish_reason") or target["finish_reason"]
                for call in delta.get("tool_calls") or []:
                    index = call.get("index", 0)
                    tools = target["message"]["tool_calls"]
                    while len(tools) <= index:
                        tools.append({"function": {"name": "", "arguments": ""}})
                    for key in ("name", "arguments"):
                        tools[index]["function"][key] += (call.get("function") or {}).get(key) or ""
        return {"id": response_id, "model": model, "usage": usage, "choices": list(choices.values())}

    class SyncClient(original_sync):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **prepare_client(kwargs))
            create = self.chat.completions.create

            def wrapped(**kwargs):
                params, state = log.start(kwargs)
                try:
                    response = create(**params)
                except Exception as exc:
                    log.finish(state, error=f"api_{type(exc).__name__}_http_{getattr(exc, 'status_code', 'unknown')}")
                    raise GatewayFailure("Gateway request failed; inspect sanitized attempt metadata.") from None
                if not params.get("stream"):
                    log.finish(state, response=response)
                    log.validate(state, dump(response) or {})
                    return response

                def iterate():
                    chunks = []
                    try:
                        for chunk in response:
                            chunks.append(dump(chunk) or {})
                            yield chunk
                        merged = merge_chunks(chunks)
                        log.finish(state, response=merged, chunks=chunks)
                        log.validate(state, merged)
                    except (DecisionFailure, BudgetStop):
                        raise
                    except BaseException as exc:
                        log.finish(state, error=f"stream_{type(exc).__name__}", chunks=chunks)
                        if isinstance(exc, GeneratorExit):
                            raise
                        raise GatewayFailure("Gateway stream failed; partial output is not a decision.") from None
                    finally:
                        try:
                            response.close()
                        except Exception:
                            raise GatewayFailure("Gateway stream close failed; review attempt accounting.") from None
                return iterate()
            self.chat.completions.create = wrapped

    class AsyncClient(original_async):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **prepare_client(kwargs))
            create = self.chat.completions.create

            async def wrapped(**kwargs):
                params, state = log.start(kwargs)
                try:
                    response = await create(**params)
                except BaseException as exc:
                    log.finish(state, error=f"api_{type(exc).__name__}_http_{getattr(exc, 'status_code', 'unknown')}")
                    raise GatewayFailure("Gateway async request failed; inspect sanitized attempt metadata.") from None
                if not params.get("stream"):
                    log.finish(state, response=response)
                    log.validate(state, dump(response) or {})
                    return response

                async def iterate():
                    chunks = []
                    try:
                        async for chunk in response:
                            chunks.append(dump(chunk) or {})
                            yield chunk
                        merged = merge_chunks(chunks)
                        log.finish(state, response=merged, chunks=chunks)
                        log.validate(state, merged)
                    except (DecisionFailure, BudgetStop):
                        raise
                    except BaseException as exc:
                        log.finish(state, error=f"stream_{type(exc).__name__}", chunks=chunks)
                        raise GatewayFailure("Gateway async stream failed; partial output is not a decision.") from None
                    finally:
                        try:
                            await response.close()
                        except Exception:
                            raise GatewayFailure("Gateway async stream close failed; review attempt accounting.") from None
                return iterate()
            self.chat.completions.create = wrapped

    openai.OpenAI, openai.AsyncOpenAI = SyncClient, AsyncClient
    return log.counts
