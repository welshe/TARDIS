"""Async support for TARDIS recording.

Provides AsyncRecorder with the same API as Recorder but designed for
async computer-use agents using Playwright, aiohttp, etc.
"""

import asyncio
import threading
from typing import Optional, Any, Dict, List
from datetime import datetime
import logging

from ..models import Trace, Step, StepType
from .recorder import Recorder


logger = logging.getLogger(__name__)


class AsyncRecorder:
    """Async-compatible flight recorder for TARDIS.
    
    Provides the same API as Recorder but is safe to use from async contexts.
    All I/O operations are run directly in the event loop with thread-safe
    SQLite handling via the underlying Recorder's error handling.
    
    Example:
        async def run_agent():
            rec = AsyncRecorder().start()
            
            # Your async agent code
            response = await client.chat.completions.create(...)
            await tool.call(...)
            
            trace = await rec.stop()
    """
    
    def __init__(self, session_name: str = ""):
        self._recorder = Recorder(session_name=session_name)
        self._running = False
        self._current_trace_id: Optional[str] = None
    
    def start(self) -> "AsyncRecorder":
        """Start the async recorder."""
        self._recorder.start()
        self._running = True
        self._current_trace_id = getattr(self._recorder.trace, 'id', None)
        return self
    
    async def log(self, step_type: StepType, **kwargs) -> Optional[Step]:
        """Log a step asynchronously.
        
        Args:
            step_type: Type of step to log
            **kwargs: Arguments passed to the underlying recorder
            
        Returns:
            The created Step, or None if logging failed
        """
        if not self._running:
            return None
        
        try:
            # Run recorder.log directly - it has internal error handling
            return self._recorder.log(step_type, **kwargs)
        except Exception as e:
            logger.warning(f"Failed to log step: {e}")
            return None
    
    async def log_llm_call(self, prompt: str, completion: str, **metadata) -> Optional[Step]:
        """Log an LLM call asynchronously."""
        return await self.log(StepType.llm_call, input={"prompt": prompt}, output={"completion": completion}, **metadata)
    
    async def log_tool_call(self, tool_name: str, input_data: Any, output: Any = None, **metadata) -> Optional[Step]:
        """Log a tool call asynchronously."""
        return await self.log(StepType.tool_call, input={"tool_name": tool_name, "args": input_data}, output={"result": output}, **metadata)
    
    async def log_tool_result(self, tool_name: str, result: Any, **metadata) -> Optional[Step]:
        """Log a tool result asynchronously."""
        return await self.log(StepType.tool_result, input={"tool_name": tool_name}, output={"result": result}, **metadata)
    
    async def log_screen_frame(self, frame_data: bytes, **metadata) -> Optional[Step]:
        """Log a screen frame asynchronously."""
        return await self.log(StepType.screen_frame, frame_data=frame_data, **metadata)
    
    async def log_dom_snapshot(self, dom_data: Dict, **metadata) -> Optional[Step]:
        """Log a DOM snapshot asynchronously."""
        return await self.log(StepType.dom_snapshot, dom_data=dom_data, **metadata)
    
    async def log_accessibility_snapshot(self, acc_data: Dict, **metadata) -> Optional[Step]:
        """Log an accessibility snapshot asynchronously."""
        return await self.log(StepType.accessibility_snapshot, acc_data=acc_data, **metadata)
    
    async def log_raw_input(self, event_type: str, data: Dict, **metadata) -> Optional[Step]:
        """Log a raw input event asynchronously."""
        return await self.log(StepType.raw_input, event_type=event_type, input_data=data, **metadata)
    
    async def log_error(self, error: Exception, **metadata) -> Optional[Step]:
        """Log an error asynchronously."""
        return await self.log(StepType.error, error=str(error), **metadata)
    
    async def log_thought(self, thought: str, **metadata) -> Optional[Step]:
        """Log a thought/reasoning step asynchronously."""
        return await self.log(StepType.thought, thought=thought, **metadata)
    
    async def log_user_action(self, action: str, **metadata) -> Optional[Step]:
        """Log a user action asynchronously."""
        return await self.log(StepType.user_action, action=action, **metadata)
    
    async def log_orchestration_event(self, event_type: str, task_id: str, **metadata) -> Optional[Step]:
        """Log an orchestration event asynchronously."""
        return await self.log(StepType.orchestration_event, orchestration_type=event_type, task_id=task_id, **metadata)
    
    async def stop(self) -> Trace:
        """Stop the recorder and return the trace.
        
        Returns:
            The completed Trace object
        """
        self._running = False
        trace = self._recorder.stop()
        return trace
    
    def get_current_trace(self) -> Optional[Trace]:
        """Get the current trace (non-async, for inspection)."""
        return self._recorder.trace if hasattr(self._recorder, 'trace') else None
    
    @property
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._running


# Context manager support
class async_record:
    """Async context manager for recording.
    
    Example:
        async with async_record("my_session") as rec:
            # Your async code
            response = await client.chat.completions.create(...)
        
        # Trace is automatically stopped and saved
    """
    
    def __init__(self, session_name: str = ""):
        self._session_name = session_name
        self._recorder: Optional[AsyncRecorder] = None
    
    async def __aenter__(self) -> AsyncRecorder:
        self._recorder = AsyncRecorder(session_name=self._session_name).start()
        return self._recorder
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._recorder:
            await self._recorder.stop()
        return False  # Don't suppress exceptions
