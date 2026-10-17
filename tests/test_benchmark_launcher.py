"""Gateway routing, output limits, and failures must not corrupt benchmark results."""
import json
import asyncio
import os
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import openai

from src.benchmarks.common import CallLimitReached, GatewayFailure, install_gateway_clients, settings


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.original_sync, self.original_async = openai.OpenAI, openai.AsyncOpenAI
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.config = {**settings(), "max_output_tokens": 40, "max_api_calls_per_task": 1}
        self.credentials = patch("src.benchmarks.common.credentials", return_value=("private-test-key", "https://gateway.example/v1"))
        self.credentials.start()
        self.environment = patch.dict(os.environ)
        self.environment.start()

    def tearDown(self):
        openai.OpenAI, openai.AsyncOpenAI = self.original_sync, self.original_async
        self.credentials.stop()
        self.environment.stop()
        self.temp.cleanup()

    def test_routing_caps_and_usage(self):
        def handler(request):
            self.assertEqual(str(request.url), "https://gateway.example/v1/chat/completions")
            body = json.loads(request.content)
            self.assertEqual(body["max_tokens"], 40)
            self.assertNotIn("max_completion_tokens", body)
            self.assertNotIn("reasoning_effort", body)
            return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0, "model": "gpt-4.1-mini",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ready"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}})
        counts = install_gateway_clients(self.output, self.config)
        client = openai.OpenAI(api_key="vendor-key", base_url="https://wrong.example", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        params = {"model": "gpt-4.1-mini", "messages": [{"role": "user", "content": "ready"}], "max_completion_tokens": 500, "reasoning_effort": "low"}
        self.assertEqual(client.chat.completions.create(**params).choices[0].message.content, "ready")
        self.assertEqual(counts["input_tokens"], 4)
        with self.assertRaises(CallLimitReached):
            client.chat.completions.create(**params)
        self.assertNotIn("private-test-key", (self.output / "api_usage.jsonl").read_text())

    def test_offline_blocks_calls(self):
        install_gateway_clients(self.output, self.config, offline=True)
        with self.assertRaises(CallLimitReached):
            openai.OpenAI().chat.completions.create(model="test", messages=[])

    def test_api_failure_cannot_be_silently_scored(self):
        install_gateway_clients(self.output, self.config)
        transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": {"message": "private-test-key", "type": "auth"}}))
        client = openai.OpenAI(http_client=httpx.Client(transport=transport))
        with self.assertRaises(GatewayFailure) as caught:
            client.chat.completions.create(model="test", messages=[])
        self.assertNotIn("private-test-key", str(caught.exception))

    def test_async_gateway_for_icbe(self):
        counts = install_gateway_clients(self.output, self.config)
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 0,
            "model": "test", "choices": [{"index": 0, "message": {"role": "assistant", "content": "DECISION: OPTION A"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}}))
        async def call():
            async with openai.AsyncOpenAI(http_client=httpx.AsyncClient(transport=transport)) as client:
                return await client.chat.completions.create(model="test", messages=[])
        self.assertEqual(asyncio.run(call()).choices[0].message.content, "DECISION: OPTION A")
        self.assertEqual(counts["completed"], 1)

    def test_icbe_parse_failure_does_not_become_cooperation(self):
        install_gateway_clients(self.output, self.config, offline=True)
        from src.benchmarks.worker import load_icbe
        module = load_icbe()
        create = AsyncMock(return_value=types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="No decision"))]))
        module.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        with self.assertRaises(ValueError):
            asyncio.run(module.get_decision("test", 1, []))


class FormulaWorkerTests(unittest.TestCase):
    def test_numeric_program_and_import_restriction(self):
        from src.benchmarks.formula_exec import exec_python_windows
        self.assertEqual(exec_python_windows("import math\nmath.sqrt(1764)")["return_val"], 42)
        self.assertEqual(exec_python_windows("import os\n42")["failure_reason"], "ImportError")

    def test_infinite_program_times_out(self):
        from src.benchmarks.formula_exec import exec_python_windows
        self.assertEqual(exec_python_windows("while True: pass\n42", timeout=0.01)["failure_reason"], "timeout")


if __name__ == "__main__":
    unittest.main()
