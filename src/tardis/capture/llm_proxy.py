import time, functools
from ..models import Step, StepType
from ..utils.hashing import stable_hash

class TardisChatCompletions:
    def __init__(self, original, recorder):
        self._orig = original
        self._rec = recorder

    def create(self, *args, **kwargs):
        start = time.time()
        step_in = {"args": args, "kwargs": kwargs}
        try:
            result = self._orig.create(*args, **kwargs)
            duration = int((time.time() - start)*1000)
            # normalize output
            try:
                out = result.model_dump() if hasattr(result, "model_dump") else result
            except Exception:
                out = {"content": str(result)}
            
            # Extract token usage and cost
            metadata = {"model": kwargs.get("model")}
            if hasattr(result, 'usage') and result.usage:
                metadata['token_count'] = {
                    'prompt_tokens': result.usage.prompt_tokens,
                    'completion_tokens': result.usage.completion_tokens,
                    'total_tokens': result.usage.total_tokens
                }
                # Rough cost estimation for OpenAI
                model = kwargs.get("model", "gpt-4o")
                if "gpt-4" in model and "o" not in model:
                    cost_per_input = 30.0 / 1_000_000
                    cost_per_output = 60.0 / 1_000_000
                elif "gpt-4o" in model:
                    cost_per_input = 5.0 / 1_000_000
                    cost_per_output = 15.0 / 1_000_000
                elif "gpt-3.5" in model:
                    cost_per_input = 0.5 / 1_000_000
                    cost_per_output = 1.5 / 1_000_000
                else:
                    cost_per_input = 5.0 / 1_000_000
                    cost_per_output = 15.0 / 1_000_000
                
                cost_usd = (result.usage.prompt_tokens * cost_per_input + 
                           result.usage.completion_tokens * cost_per_output)
                metadata['cost_usd'] = cost_usd
            
            self._rec.log(StepType.llm_call, input=step_in, output=out, 
                        duration_ms=duration, metadata=metadata)
            return result
        except Exception as e:
            duration = int((time.time() - start)*1000)
            self._rec.log(StepType.error, input=step_in, output={"error": str(e)}, 
                        duration_ms=duration, metadata={"model": kwargs.get("model")})
            raise

class TardisChat:
    def __init__(self, original_chat, recorder):
        self.completions = TardisChatCompletions(original_chat.completions, recorder)

class TardisClient:
    def __init__(self, original_client, recorder):
        self._orig = original_client
        self._rec = recorder
        self.chat = TardisChat(original_client.chat, recorder)
        # pass through everything else
    def __getattr__(self, name):
        return getattr(self._orig, name)

def wrap(client, recorder=None):
    from .recorder import get_current_recorder
    rec = recorder or get_current_recorder()
    if rec is None:
        from .recorder import Recorder
        rec = Recorder()
        rec.start()
    return TardisClient(client, rec)
