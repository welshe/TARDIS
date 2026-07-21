import functools
import time

from ..models import StepType


def tool_traced(recorder, name: str):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = fn(*args, **kwargs)
                duration = int((time.time() - start) * 1000)
                recorder.log(
                    StepType.tool_call,
                    input={"name": name, "args": args, "kwargs": kwargs},
                    output={"result": str(result)[:4000]},
                    duration_ms=duration,
                )
                return result
            except Exception as e:
                duration = int((time.time() - start) * 1000)
                recorder.log(
                    StepType.error,
                    input={"name": name, "args": args},
                    output={"error": str(e)},
                    duration_ms=duration,
                )
                raise

        return wrapper

    return decorator
