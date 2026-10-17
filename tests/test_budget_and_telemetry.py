import asyncio
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
import openai

from budget_fixture import ledger, manifest
from src.benchmarks.budget import BudgetLedger
from src.benchmarks.common import install_gateway_clients, settings
from src.benchmarks.errors import BudgetStop, DecisionFailure, GatewayFailure
from src.benchmarks.gateway import request_context


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_unapproved_allowance_cannot_create_a_paid_session(self):
        config = manifest()
        config["approved"] = False
        with self.assertRaises(BudgetStop):
            BudgetLedger(config, self.folder / "budget.sqlite", run_id="r")

    def test_atomic_reservations_cannot_spend_the_same_remainder(self):
        # Each request reserves $0.06; only one fits the $0.10 allowance.
        budget = ledger(self.folder, cap=0.1)
        barrier = threading.Barrier(2)
        def reserve(i):
            barrier.wait()
            try:
                budget.reserve(str(i), "test", 60000, 0)
                return True
            except BudgetStop:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(reserve, range(2)))
        self.assertEqual(sum(result), 1)
        self.assertAlmostEqual(budget.summary()["exposure_usd"], 0.06)

    def test_spend_persists_across_runs_and_manifest_changes_are_rejected(self):
        first = ledger(self.folder, attempts=1)
        first.reserve("a", "test", 100, 20)
        first.settle("a", input_tokens=100, output_tokens=20)
        second = ledger(self.folder, attempts=1, run_id="next")
        with self.assertRaises(BudgetStop):
            second.reserve("b", "test", 1, 1)
        changed = manifest(attempts=2)
        with self.assertRaises(BudgetStop):
            BudgetLedger(changed, self.folder / "budget.sqlite", run_id="changed")

    def test_missing_usage_retains_reservation_and_blocks_next_call(self):
        budget = ledger(self.folder)
        budget.reserve("a", "test", 1000, 100)
        budget.settle("a")
        summary = budget.summary()
        self.assertGreater(summary["unresolved_reserved_usd"], 0)
        self.assertEqual(summary["uncertain_attempts"], 1)
        with self.assertRaises(BudgetStop):
            budget.reserve("b", "test", 1, 1)

    def test_previous_crashed_run_reservation_blocks_a_new_run(self):
        first = ledger(self.folder)
        first.reserve("unfinished", "test", 1000, 100)
        second = ledger(self.folder, run_id="other")
        with self.assertRaises(BudgetStop):
            second.reserve("new", "test", 1, 1)

    def test_token_envelope_breach_is_recorded_and_not_called_free(self):
        budget = ledger(self.folder)
        budget.reserve("a", "test", 10, 10)
        budget.settle("a", input_tokens=100, output_tokens=1)
        self.assertEqual(budget.summary()["uncertain_attempts"], 1)
        self.assertGreater(budget.summary()["known_cost_usd"], 0)
        with self.assertRaises(BudgetStop):
            budget.reserve("b", "test", 1, 1)


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.original = openai.OpenAI, openai.AsyncOpenAI
        self.config = {**settings(), "max_api_calls_per_task": 5, "_purpose": "pilot", "_run_id": "mock-run"}
        self.credentials = patch("src.benchmarks.common.credentials", return_value=("private-test-key", "https://gateway.example/v1"))
        self.credentials.start()
        self.environment = patch.dict("os.environ")
        self.environment.start()
        self.budget = ledger(self.folder)

    def tearDown(self):
        openai.OpenAI, openai.AsyncOpenAI = self.original
        self.credentials.stop()
        self.environment.stop()
        self.temp.cleanup()

    def response(self, content='{"final_answer":"42"}', *, usage=True):
        payload = {"id": "mock-response", "object": "chat.completion", "created": 0, "model": "returned-test",
                   "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}
        if usage:
            payload["usage"] = {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}
        return httpx.Response(200, json=payload)

    def events(self):
        return [json.loads(line) for line in (self.folder / "api_attempts.jsonl").read_text().splitlines()]

    def test_start_is_durable_before_transport_and_key_is_redacted(self):
        def handler(request):
            self.assertEqual(self.events()[0]["event"], "started")
            self.assertEqual(self.budget.summary()["pending_attempts"], 1)
            return self.response()
        install_gateway_clients(self.folder, self.config, budget=self.budget)
        client = openai.OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        with request_context(case_id="sample-1", validation_kind="reasoning"):
            client.chat.completions.create(model="test", messages=[{"role": "user", "content": "private-test-key"}])
        self.assertEqual([e["event"] for e in self.events()], ["started", "finished", "parse_checked"])
        end = self.events()[1]
        self.assertEqual(end["returned_model"], "returned-test")
        self.assertGreaterEqual(end["latency_seconds"], 0)
        self.assertEqual(end["usage"]["prompt_tokens"], 4)
        for p in self.folder.rglob("*.json*"):
            self.assertNotIn("private-test-key", p.read_text())

    def test_missing_usage_stops_even_when_text_is_valid(self):
        install_gateway_clients(self.folder, self.config, budget=self.budget)
        client = openai.OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(lambda r: self.response(usage=False))))
        with self.assertRaises(BudgetStop):
            client.chat.completions.create(model="test", messages=[])
        self.assertEqual(self.budget.summary()["uncertain_attempts"], 1)

    def test_invalid_decision_cannot_reach_native_fallback(self):
        install_gateway_clients(self.folder, self.config, budget=self.budget)
        client = openai.OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(lambda r: self.response('{}'))))
        with request_context(validation_kind="beer"):
            with self.assertRaises(DecisionFailure):
                client.chat.completions.create(model="test", messages=[], response_format={"type": "json_object"})
        self.assertEqual(self.events()[-1]["parse_status"], "invalid")
        self.assertGreater(self.budget.summary()["known_cost_usd"], 0)

    def test_stream_retains_early_model_and_usage_not_only_last_chunk(self):
        chunks = [
            {"id": "s", "object": "chat.completion.chunk", "created": 0, "model": "early-model", "choices": [{"index": 0, "delta": {"content": "READY"}, "finish_reason": None}]},
            {"id": "s", "object": "chat.completion.chunk", "created": 0, "model": "", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            {"id": "s", "object": "chat.completion.chunk", "created": 0, "model": "", "choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}},
            {"id": "s", "object": "chat.completion.chunk", "created": 0, "model": "", "choices": []},
        ]
        body = ''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n'
        install_gateway_clients(self.folder, self.config, budget=self.budget)
        transport = httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body))
        client = openai.OpenAI(http_client=httpx.Client(transport=transport))
        result = list(client.chat.completions.create(model="test", messages=[], stream=True))
        self.assertEqual(len(result), 4)
        finished = next(e for e in self.events() if e["event"] == "finished")
        self.assertEqual(finished["returned_model"], "early-model")
        self.assertEqual(finished["usage"]["prompt_tokens"], 2)

    def test_async_failure_has_a_final_event_and_holds_the_charge_reserve(self):
        install_gateway_clients(self.folder, self.config, budget=self.budget)
        transport = httpx.MockTransport(lambda r: httpx.Response(429, json={"error": {"message": "private-test-key"}}))
        async def call():
            async with openai.AsyncOpenAI(http_client=httpx.AsyncClient(transport=transport)) as client:
                await client.chat.completions.create(model="test", messages=[])
        with self.assertRaises(GatewayFailure):
            asyncio.run(call())
        self.assertEqual(self.events()[-1]["status"], "failed")
        self.assertGreater(self.budget.summary()["unresolved_reserved_usd"], 0)

    def test_absent_budget_cannot_send_a_completion(self):
        install_gateway_clients(self.folder, self.config)
        transport = httpx.MockTransport(lambda r: self.fail("Unapproved request reached the transport"))
        with self.assertRaises(BudgetStop):
            openai.OpenAI(http_client=httpx.Client(transport=transport)).chat.completions.create(model="test", messages=[])
