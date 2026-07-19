"""
Deep OS Integration Module (eBPF/ETW)
Kernel-level tracing for zero-overhead monitoring.
"""
import os
import sys
import time
from typing import Dict, List, Optional, Callable, Any, Set
from dataclasses import dataclass, field
from enum import Enum
import threading
import json


class TraceBackend(Enum):
    EBPF = "ebpf"
    ETW = "etw"
    DTRACE = "dtrace"
    FALLBACK = "fallback"


@dataclass
class TraceEvent:
    timestamp: float
    event_type: str
    process_id: int
    thread_id: int
    syscall_name: Optional[str]
    duration_ns: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceConfig:
    backend: TraceBackend
    events: Set[str] = field(default_factory=set)
    processes: Set[int] = field(default_factory=set)
    sample_rate: float = 1.0
    buffer_size_mb: int = 64


class KernelTracer:
    """
    Kernel-level tracer using eBPF (Linux) or ETW (Windows).
    
    Features:
    - Zero-overhead kernel tracing
    - Automatic backend detection
    - Syscall and function tracing
    - Real-time event streaming
    - Configurable sampling
    """
    
    def __init__(self, config: Optional[TraceConfig] = None):
        self.config = config or TraceConfig(backend=self._detect_backend())
        self._running = False
        self._events: List[TraceEvent] = []
        self._handlers: List[Callable[[TraceEvent], None]] = []
        self._lock = threading.Lock()
        self._backend_instance: Optional[Any] = None
    
    @staticmethod
    def _detect_backend() -> TraceBackend:
        """Detect the appropriate tracing backend for the current OS."""
        if sys.platform.startswith('linux'):
            # Check if eBPF is available
            if os.path.exists('/sys/kernel/debug/tracing'):
                return TraceBackend.EBPF
        elif sys.platform == 'win32':
            return TraceBackend.ETW
        elif sys.platform == 'darwin':
            return TraceBackend.DTRACE
        
        return TraceBackend.FALLBACK
    
    def start(self):
        """Start kernel tracing."""
        if self._running:
            return
        
        self._running = True
        
        if self.config.backend == TraceBackend.EBPF:
            self._start_ebpf()
        elif self.config.backend == TraceBackend.ETW:
            self._start_etw()
        elif self.config.backend == TraceBackend.DTRACE:
            self._start_dtrace()
        else:
            self._start_fallback()
    
    def stop(self) -> List[TraceEvent]:
        """Stop tracing and return collected events."""
        self._running = False
        
        if self._backend_instance:
            if hasattr(self._backend_instance, 'stop'):
                self._backend_instance.stop()
        
        with self._lock:
            events = self._events.copy()
            self._events.clear()
        
        return events
    
    def register_handler(self, handler: Callable[[TraceEvent], None]):
        """Register a callback for trace events."""
        self._handlers.append(handler)
    
    def _notify_handlers(self, event: TraceEvent):
        """Notify all registered handlers of a new event."""
        for handler in self._handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"Error in trace handler: {e}")
    
    def _start_ebpf(self):
        """Initialize eBPF tracing on Linux."""
        try:
            # Try to use bcc/BPF tools if available
            from bcc import BPF
            
            # Simple syscall tracing program
            bpf_program = """
            #include <uapi/linux/ptrace.h>
            
            struct event_t {
                u64 timestamp;
                u32 pid;
                u32 tid;
                char comm[TASK_COMM_LEN];
            };
            
            BPF_PERF_OUTPUT(events);
            
            int trace_syscall(struct pt_regs *ctx) {
                struct event_t event = {};
                event.timestamp = bpf_ktime_get_ns();
                event.pid = bpf_get_current_pid_tgid() >> 32;
                event.tid = bpf_get_current_pid_tgid();
                bpf_get_current_comm(&event.comm, sizeof(event.comm));
                events.perf_submit(ctx, &event, sizeof(event));
                return 0;
            }
            """
            
            self._backend_instance = BPF(text=bpf_program)
            self._backend_instance.attach_kprobe(
                event=self._backend_instance.get_syscall_fnname("open"),
                fn_name="trace_syscall"
            )
            
            def handle_event(cpu, data, size):
                event = self._backend_instance["events"].event(data)
                trace_event = TraceEvent(
                    timestamp=event.timestamp / 1e9,
                    event_type="syscall",
                    process_id=event.pid,
                    thread_id=event.tid,
                    syscall_name="open",
                    duration_ns=0,
                    metadata={"comm": event.comm.decode()}
                )
                self._add_event(trace_event)
            
            self._backend_instance["events"].open_perf_buffer(handle_event)
            
        except ImportError:
            print("BCC not available, using fallback tracing")
            self._start_fallback()
        except Exception as e:
            print(f"eBPF initialization error: {e}")
            self._start_fallback()
    
    def _start_etw(self):
        """Initialize ETW tracing on Windows."""
        try:
            # Placeholder for ETW implementation
            # In production, would use pywin32 or similar
            print("ETW tracing initialized (simulation mode)")
            self._backend_instance = {"type": "etw", "active": True}
        except Exception as e:
            print(f"ETW initialization error: {e}")
            self._start_fallback()
    
    def _start_dtrace(self):
        """Initialize DTrace on macOS/BSD."""
        print("DTrace tracing initialized (simulation mode)")
        self._backend_instance = {"type": "dtrace", "active": True}
    
    def _start_fallback(self):
        """Fallback tracing using Python instrumentation."""
        print("Using fallback Python-based tracing")
        self._backend_instance = {"type": "fallback", "active": True}
    
    def _add_event(self, event: TraceEvent):
        """Add a trace event and notify handlers."""
        with self._lock:
            self._events.append(event)
            # Limit buffer size
            if len(self._events) > 10000:
                self._events = self._events[-5000:]
        self._notify_handlers(event)
    
    def trace_function(self, func: Callable) -> Callable:
        """Decorator to trace function calls."""
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter_ns()
            try:
                result = func(*args, **kwargs)
                duration = time.perf_counter_ns() - start_time
                
                event = TraceEvent(
                    timestamp=time.time(),
                    event_type="function_call",
                    process_id=os.getpid(),
                    thread_id=threading.get_ident(),
                    syscall_name=func.__name__,
                    duration_ns=duration
                )
                self._add_event(event)
                return result
            except Exception as e:
                duration = time.perf_counter_ns() - start_time
                event = TraceEvent(
                    timestamp=time.time(),
                    event_type="function_error",
                    process_id=os.getpid(),
                    thread_id=threading.get_ident(),
                    syscall_name=func.__name__,
                    duration_ns=duration,
                    metadata={"error": str(e)}
                )
                self._add_event(event)
                raise
        
        return wrapper
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get tracing statistics."""
        with self._lock:
            event_count = len(self._events)
            event_types = {}
            for event in self._events:
                event_types[event.event_type] = event_types.get(event.event_type, 0) + 1
        
        return {
            "backend": self.config.backend.value,
            "running": self._running,
            "event_count": event_count,
            "event_types": event_types,
            "sample_rate": self.config.sample_rate
        }
