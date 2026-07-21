"""Tests for capture proxies, tool_wrapper, and async_recorder."""

import asyncio

import pytest

from tardis.capture.tool_wrapper import tool_traced
from tardis.models import StepType

# ---------------------------------------------------------------------------
# tool_traced decorator
# ---------------------------------------------------------------------------


class TestToolTraced:
    def test_records_successful_call(self):
        recorded = []

        class FakeRecorder:
            def log(self, step_type, **kwargs):
                recorded.append((step_type, kwargs))

        @tool_traced(FakeRecorder(), "my_tool")
        def my_func(x, y):
            return x + y

        result = my_func(2, 3)
        assert result == 5
        assert len(recorded) == 1
        assert recorded[0][0] == StepType.tool_call
        assert recorded[0][1]["input"]["name"] == "my_tool"

    def test_records_error(self):
        recorded = []

        class FakeRecorder:
            def log(self, step_type, **kwargs):
                recorded.append((step_type, kwargs))

        @tool_traced(FakeRecorder(), "fail_tool")
        def failing_func():
            raise ValueError("oops")

        with pytest.raises(ValueError, match="oops"):
            failing_func()
        assert len(recorded) == 1
        assert recorded[0][0] == StepType.error
        assert "oops" in recorded[0][1]["output"]["error"]

    def test_preserves_function_name(self):
        class FakeRecorder:
            def log(self, step_type, **kwargs):
                pass

        @tool_traced(FakeRecorder(), "tool")
        def documented_func():
            """My docstring."""
            pass

        assert documented_func.__name__ == "documented_func"
        assert documented_func.__doc__ == "My docstring."


# ---------------------------------------------------------------------------
# LLM Proxies — TardisChatCompletions (OpenAI-style)
# ---------------------------------------------------------------------------


class TestLLMProxy:
    def test_wrap_chat_completions(self):
        recorded = []

        class FakeRecorder:
            def log(self, step_type, **kwargs):
                recorded.append((step_type, kwargs))

        class FakeUsage:
            prompt_tokens = 10
            completion_tokens = 20
            total_tokens = 30

        class FakeResponse:
            usage = FakeUsage()

            def model_dump(self):
                return {"choices": [{"message": {"content": "hi"}}]}

        class FakeCompletions:
            def create(self, *args, **kwargs):
                return FakeResponse()

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        from tardis.capture.llm_proxy import TardisClient

        wrapped = TardisClient(FakeClient(), FakeRecorder())
        result = wrapped.chat.completions.create(model="gpt-4o", messages=[])
        assert hasattr(result, "usage")
        assert len(recorded) == 1
        assert recorded[0][0] == StepType.llm_call
        assert recorded[0][1]["metadata"]["cost_usd"] > 0

    def test_wrap_chat_completions_error(self):
        recorded = []

        class FakeRecorder:
            def log(self, step_type, **kwargs):
                recorded.append((step_type, kwargs))

        class FakeCompletions:
            def create(self, *args, **kwargs):
                raise RuntimeError("API error")

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        from tardis.capture.llm_proxy import TardisClient

        wrapped = TardisClient(FakeClient(), FakeRecorder())
        with pytest.raises(RuntimeError, match="API error"):
            wrapped.chat.completions.create(model="gpt-4o", messages=[])
        assert len(recorded) == 1
        assert recorded[0][0] == StepType.error

    def test_proxy_passthrough_attrs(self):
        class FakeRecorder:
            def log(self, step_type, **kwargs):
                pass

        class FakeClient:
            api_key = "sk-test"
            chat = type("Chat", (), {"completions": None})()

        from tardis.capture.llm_proxy import TardisClient

        wrapped = TardisClient(FakeClient(), FakeRecorder())
        assert wrapped.api_key == "sk-test"


# ---------------------------------------------------------------------------
# Anthropic Proxy
# ---------------------------------------------------------------------------


class TestAnthropicProxy:
    def test_wrap_anthropic(self):
        recorded = []

        class FakeRecorder:
            def log(self, step_type, **kwargs):
                recorded.append((step_type, kwargs))

        class FakeUsage:
            input_tokens = 10
            output_tokens = 20

        class FakeResponse:
            usage = FakeUsage()

            def model_dump(self):
                return {"content": [{"text": "hello"}]}

        class FakeMessages:
            def create(self, *args, **kwargs):
                return FakeResponse()

        class FakeClient:
            messages = FakeMessages()

        from tardis.capture.anthropic_proxy import TardisAnthropicClient

        wrapped = TardisAnthropicClient(FakeClient(), FakeRecorder())
        wrapped.messages.create(model="claude-3-sonnet", messages=[])
        assert len(recorded) == 1
        assert recorded[0][0] == StepType.llm_call

    def test_anthropic_error(self):
        recorded = []

        class FakeRecorder:
            def log(self, step_type, **kwargs):
                recorded.append((step_type, kwargs))

        class FakeMessages:
            def create(self, *args, **kwargs):
                raise RuntimeError("Rate limited")

        class FakeClient:
            messages = FakeMessages()

        from tardis.capture.anthropic_proxy import TardisAnthropicClient

        wrapped = TardisAnthropicClient(FakeClient(), FakeRecorder())
        with pytest.raises(RuntimeError):
            wrapped.messages.create(model="claude-3-opus", messages=[])
        assert recorded[0][0] == StepType.error


# ---------------------------------------------------------------------------
# AsyncRecorder
# ---------------------------------------------------------------------------


class TestAsyncRecorder:
    def test_start_stop(self):
        from tardis.capture.async_recorder import AsyncRecorder

        rec = AsyncRecorder(session_name="test_async")
        rec.start()
        assert rec.is_recording
        trace = asyncio.run(rec.stop())
        assert trace is not None
        assert not rec.is_recording

    def test_log_when_not_running(self):
        from tardis.capture.async_recorder import AsyncRecorder

        rec = AsyncRecorder()
        result = asyncio.run(rec.log(StepType.thought, thought="test"))
        assert result is None

    def test_log_llm_call(self):
        from tardis.capture.async_recorder import AsyncRecorder

        rec = AsyncRecorder().start()
        step = asyncio.run(
            rec.log(
                StepType.llm_call,
                input={"prompt": "prompt"},
                output={"completion": "completion"},
                metadata={"model": "gpt-4o"},
            )
        )
        assert step is not None
        asyncio.run(rec.stop())

    def test_log_tool_call(self):
        from tardis.capture.async_recorder import AsyncRecorder

        rec = AsyncRecorder().start()
        step = asyncio.run(rec.log_tool_call("search", {"q": "test"}, {"results": []}))
        assert step is not None
        asyncio.run(rec.stop())

    def test_log_error(self):
        from tardis.capture.async_recorder import AsyncRecorder

        rec = AsyncRecorder().start()
        step = asyncio.run(
            rec.log(
                StepType.error,
                input={"error": "fail"},
                output={"error": "RuntimeError: fail"},
            )
        )
        assert step is not None
        asyncio.run(rec.stop())

    def test_log_thought(self):
        from tardis.capture.async_recorder import AsyncRecorder

        rec = AsyncRecorder().start()
        step = asyncio.run(
            rec.log(
                StepType.thought,
                input={"thought": "analyzing..."},
                output={"thought": "analyzing..."},
            )
        )
        assert step is not None
        asyncio.run(rec.stop())

    def test_get_current_trace(self):
        from tardis.capture.async_recorder import AsyncRecorder

        rec = AsyncRecorder().start()
        trace = rec.get_current_trace()
        assert trace is not None
        asyncio.run(rec.stop())

    def test_async_context_manager(self):
        from tardis.capture.async_recorder import async_record

        async def run():
            async with async_record("ctx_test") as rec:
                assert rec.is_recording
            assert not rec.is_recording

        asyncio.run(run())
