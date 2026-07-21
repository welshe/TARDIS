import time

from ..models import StepType


class TardisAnthropicMessages:
    def __init__(self, original, recorder):
        self._orig = original
        self._rec = recorder

    def create(self, *args, **kwargs):
        start = time.time()
        step_in = {"args": args, "kwargs": kwargs}
        try:
            result = self._orig.create(*args, **kwargs)
            duration = int((time.time() - start) * 1000)
            # normalize output
            try:
                out = result.model_dump() if hasattr(result, "model_dump") else result
            except Exception:
                out = {"content": str(result)}

            # Extract token usage and cost
            metadata = {"model": kwargs.get("model")}
            if hasattr(result, "usage"):
                metadata["token_count"] = {
                    "prompt_tokens": result.usage.input_tokens,
                    "completion_tokens": result.usage.output_tokens,
                    "total_tokens": result.usage.input_tokens
                    + result.usage.output_tokens,
                }
                # Rough cost estimation for Anthropic (pricing as of 2024)
                model = kwargs.get("model", "claude-3-sonnet-20240229")
                if "sonnet" in model:
                    cost_per_input = 3.00 / 1_000_000
                    cost_per_output = 15.00 / 1_000_000
                elif "opus" in model:
                    cost_per_input = 15.00 / 1_000_000
                    cost_per_output = 75.00 / 1_000_000
                elif "haiku" in model:
                    cost_per_input = 0.25 / 1_000_000
                    cost_per_output = 1.25 / 1_000_000
                else:
                    cost_per_input = 3.00 / 1_000_000
                    cost_per_output = 15.00 / 1_000_000

                cost_usd = (
                    result.usage.input_tokens * cost_per_input
                    + result.usage.output_tokens * cost_per_output
                )
                metadata["cost_usd"] = cost_usd

            self._rec.log(
                StepType.llm_call,
                input=step_in,
                output=out,
                duration_ms=duration,
                metadata=metadata,
            )
            return result
        except Exception as e:
            duration = int((time.time() - start) * 1000)
            self._rec.log(
                StepType.error,
                input=step_in,
                output={"error": str(e)},
                duration_ms=duration,
                metadata={"model": kwargs.get("model")},
            )
            raise


class TardisAnthropicClient:
    def __init__(self, original_client, recorder):
        self._orig = original_client
        self._rec = recorder
        self.messages = TardisAnthropicMessages(original_client.messages, recorder)
        # pass through everything else

    def __getattr__(self, name):
        return getattr(self._orig, name)


def wrap_anthropic(client, recorder=None):
    from .recorder import get_current_recorder

    rec = recorder or get_current_recorder()
    if rec is None:
        from .recorder import Recorder

        # Lazily create a recorder but keep a reference so it can be flushed
        # via stop_wrap_anthropic() — otherwise the trace would be lost.
        rec = Recorder()
        rec.start()
    wrapped = TardisAnthropicClient(client, rec)
    wrapped._tardis_recorder = rec
    return wrapped


def stop_wrap_anthropic(wrapped_client):
    """Flush and stop a recorder created by ``wrap_anthropic()``."""
    rec = getattr(wrapped_client, "_tardis_recorder", None)
    if rec is not None and rec.active:
        rec.stop()
        wrapped_client._tardis_recorder = None
