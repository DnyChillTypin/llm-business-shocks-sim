"""Synthetic exact-request replay checks; never use or authorize a real gateway."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.benchmarks.common import settings
from src.benchmarks.errors import DecisionFailure
from src.benchmarks.gateway import request_context, CONTEXT
from src.benchmarks.icbe_recovery import key, probe_native_prefix, replay_create, request_digest
from src.benchmarks.worker import load_icbe


def response(model):
    return {"id": "synthetic_observed", "object": "chat.completion", "created": 1, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "DECISION: OPTION B"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}


class ICBEReplayTests(unittest.TestCase):
    def test_replay_uses_only_identical_observed_request_without_new_transport(self):
        config = settings()
        request = {"model": config["icbe_models"][0], "max_tokens": 4096, "temperature": .7,
                   "messages": [{"role": "user", "content": "synthetic exact state"}]}
        record = {"request_digest": request_digest(request, config), "response": response(request["model"])}
        original = AsyncMock()
        reused = []
        create = replay_create(original, {"decisions": {"ordered_pair_00:0001:A": record}}, config,
                               on_replay=lambda logical, value: reused.append(logical))
        with request_context(case_id="ordered_pair_00", round=1, actor="A"):
            observed = asyncio.run(create(**request))
            self.assertEqual(observed.id, "synthetic_observed")
            changed = {**request, "messages": [{"role": "user", "content": "changed history"}]}
            with self.assertRaises(DecisionFailure):
                asyncio.run(create(**changed))
        original.assert_not_called()
        self.assertEqual(reused, ["ordered_pair_00:0001:A"])

    def test_missing_logical_choice_makes_one_new_request(self):
        config = settings()
        request = {"model": config["icbe_models"][0], "max_tokens": 4096, "temperature": .7, "messages": []}
        original = AsyncMock(return_value="synthetic transport result")
        create = replay_create(original, {"decisions": {}}, config, on_replay=lambda *args: self.fail("Unexpected replay"))
        with request_context(case_id="ordered_pair_00", round=1, actor="A"):
            self.assertEqual(asyncio.run(create(**request)), "synthetic transport result")
        original.assert_awaited_once_with(**request)

    def test_actual_native_simulator_reconstructs_the_same_prefix_without_api_calls(self):
        class Stop(BaseException):
            pass
        captured = {}
        async def capture(**kwargs):
            captured[key(CONTEXT.get())] = kwargs
            raise Stop()
        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=capture)))
        config = settings()
        with patch("openai.AsyncOpenAI", return_value=fake):
            module = load_icbe()
        module.MODELS, module.NUM_ROUNDS = config["icbe_models"], config["icbe_rounds"]
        async def first_round():
            await asyncio.gather(module.scoped_decision(module.MODELS[0], 1, [], 1, "A"),
                                 module.scoped_decision(module.MODELS[1], 1, [], 1, "B"))
        with self.assertRaises(Stop):
            asyncio.run(first_round())
        self.assertEqual(len(captured), 2)
        recipe = {"decisions": {logical: {"request_digest": request_digest(request, config), "response": response(request["model"])}
                                for logical, request in captured.items()}}
        result = probe_native_prefix(recipe)
        self.assertEqual(result["paid_api_calls"], 0)
        self.assertEqual(result["verified_native_prefix_decisions"], 2)
