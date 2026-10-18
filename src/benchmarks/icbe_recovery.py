"""Exact-request replay of observed ICBE decisions; no invented model output."""
import contextlib
import hashlib
import io
import json
import re
import tempfile
from pathlib import Path

from .common import ROOT, settings
from .errors import DecisionFailure
from .gateway import CONTEXT
from src.research.design import canonical_hash, text_hash


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def key(context):
    return f"{context['case_id']}:{int(context['round']):04d}:{context['actor']}"


def request_digest(request, config):
    if (set(request) != {"model", "messages", "temperature", "max_tokens"}
            or request["max_tokens"] != config["max_output_tokens"] or request["temperature"] != .7):
        raise ValueError("ICBE request shape or generation settings changed; inspect before replay or payment.")
    return hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def build_replay(source_runs):
    config = settings()
    pairs = [(a, b) for a in config["icbe_models"] for b in config["icbe_models"] if a != b]
    folders = [Path(p).resolve() for p in source_runs]
    for folder in folders:
        if not folder.is_relative_to(ROOT / "results/benchmarks/icbe"):
            raise ValueError("ICBE replay sources must stay inside local ICBE evidence.")
    folders.sort(key=lambda p: read(p / "run_manifest.json")["started_at_utc"])
    decisions = {}
    for folder in folders:
        manifest, prior, identity = (read(folder / name) for name in ("run_manifest.json", "run_config.json", "runtime_identity.json"))
        if (manifest["task"] != "icbe" or manifest["purpose"] != "evaluation" or manifest["expected_units"] != 6
                or manifest["configured_horizon"] != config["icbe_rounds"] or any(prior.get(k) != v for k, v in config.items())
                or identity["study_manifest_sha256"] != text_hash(ROOT / "docs/results/study_design_manifest.json")
                or identity.get("provider") != "ShopAIKey" or identity.get("base_url") != "https://api.shopaikey.com/v1"
                or identity["source_pins"] != read(ROOT / "configs/sources.json")):
            raise ValueError("ICBE replay source differs from frozen models, settings, horizons or sources.")
        events = [json.loads(line) for line in (folder / "api_attempts.jsonl").read_text().splitlines()]
        starts = {e["attempt_id"]: e for e in events if e["event"] == "started"}
        parses = {e["attempt_id"]: e for e in events if e["event"] == "parse_checked"}
        if any(e["parse_status"] != "valid" for e in parses.values()):
            raise ValueError("An invalid model decision requires separate methodological review; do not resample it through recovery.")
        for finish in [e for e in events if e["event"] == "finished" and e["status"] == "completed"]:
            start, parse = starts[finish["attempt_id"]], parses.get(finish["attempt_id"])
            if not parse or parse["parse_status"] != "valid" or finish.get("cost_usd") is None:
                raise ValueError("Observed ICBE response lacks validated parsing or known usage.")
            ctx = start["context"]
            if not re.fullmatch(r"ordered_pair_0[0-5]", ctx["case_id"]) or ctx["actor"] not in {"A", "B"} or not 1 <= ctx["round"] <= config["icbe_rounds"]:
                raise ValueError("ICBE response has invalid frozen logical-choice identity.")
            logical = key(ctx)
            if logical in decisions:
                continue  # First observed valid response, never the most favorable score.
            path = folder / "attempts" / finish["attempt_id"]
            request, response = read(path / "request.json"), read(path / "response.json")
            digest = request_digest(request, config)
            expected = pairs[int(ctx["case_id"].rsplit("_", 1)[1])][0 if ctx["actor"] == "A" else 1]
            if digest != start["request_sha256"] or digest != finish["request_sha256"] or request["model"] != expected:
                raise ValueError("ICBE request or ordered-pair model provenance changed.")
            if response.get("id") != finish.get("response_id") or response.get("usage") != finish.get("usage"):
                raise ValueError("ICBE raw response identity/usage differs from the durable journal.")
            choice = response["choices"][0]
            content = choice["message"].get("content")
            moves = re.findall(r"\bDECISION:\s*OPTION\s+([AB])\b", (content or "").upper())
            if not moves or len(set(moves)) != 1 or choice.get("finish_reason") in {"length", "content_filter"} or choice["message"].get("tool_calls"):
                raise ValueError("Cached ICBE response is not an unambiguous complete native decision.")
            decisions[logical] = {"context": {k: ctx[k] for k in ("case_id", "round", "actor")},
                "request_digest": digest, "request": request, "response": response,
                "move": "COOPERATE" if moves[0] == "A" else "EXPLOIT", "source_folder": str(folder),
                "attempt_id": finish["attempt_id"], "raw_request_digest": text_hash(path / "request.json"),
                "raw_response_digest": text_hash(path / "response.json")}
    return {"version": 1, "selection_rule": "first observed validated response per frozen logical choice, exact request replay only",
            "source_runs": [str(p) for p in folders], "decisions": decisions}


def verify_replay(path):
    stored = read(path)
    derived = build_replay(stored["source_runs"])
    if canonical_hash(stored) != canonical_hash(derived):
        raise ValueError("ICBE replay manifest differs from re-audited original artifacts.")
    return derived


def replay_create(original, recipe, config, *, on_replay):
    """Run the native request builder, then reuse only an identical observed request."""
    from openai.types.chat import ChatCompletion

    async def create(**kwargs):
        context = CONTEXT.get()
        logical = key(context)
        try:
            digest = request_digest(kwargs, config)
        except ValueError:
            raise DecisionFailure("Native ICBE request settings changed; stopped before transport.") from None
        cached = recipe["decisions"].get(logical)
        if cached:
            if digest != cached["request_digest"]:
                raise DecisionFailure("Native history/prompt differs from the observed ICBE response; replay stopped before transport.")
            on_replay(logical, cached)
            return ChatCompletion.model_validate(cached["response"])
        return await original(**kwargs)

    return create


def probe_native_prefix(recipe):
    """Replay through the actual native simulator, stopping before any new API call."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch
    from .worker import load_icbe

    class Boundary(BaseException):
        pass

    async def stop(**kwargs):
        raise Boundary()

    seen = set()
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=stop)))
    with patch("openai.AsyncOpenAI", return_value=fake), contextlib.redirect_stdout(io.StringIO()), tempfile.TemporaryDirectory(dir=ROOT / ".cache") as directory, contextlib.chdir(directory):
        module = load_icbe()
        config = settings()
        module.MODELS, module.NUM_ROUNDS = config["icbe_models"], config["icbe_rounds"]
        module.ROUND_DELAY_SECONDS = 0  # Offline probe only; paid native delay is unchanged.
        module.client.chat.completions.create = replay_create(stop, recipe, config, on_replay=lambda logical, record: seen.add(logical))
        try:
            asyncio.run(module.main())
        except Boundary:
            pass
    if seen != set(recipe["decisions"]):
        raise ValueError("Cached decisions do not form a consistent prefix of the native histories; no paid continuation authorized.")
    return {"status": "passed", "verified_native_prefix_decisions": len(seen), "paid_api_calls": 0}
