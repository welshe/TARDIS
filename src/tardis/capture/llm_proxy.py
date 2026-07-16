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
            self._rec.log(StepType.llm_call, input=step_in, output=out, duration_ms=duration, metadata={"model": kwargs.get("model")})
            return result
        except Exception as e:
            duration = int((time.time() - start)*1000)
            self._rec.log(StepType.error, input=step_in, output={"error": str(e)}, duration_ms=duration)
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
