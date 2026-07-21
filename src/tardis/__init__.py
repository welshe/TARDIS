from .autopsy.plugins import (
    CheckResult,
    get_registered_checks,
    register_check,
    run_all_checks,
)
from .capture.anthropic_proxy import wrap_anthropic
from .capture.async_recorder import AsyncRecorder, async_record
from .capture.dom_snapshot import capture_accessibility, capture_dom, diff_snapshots
from .capture.llm_proxy import wrap
from .capture.recorder import Recorder, record
from .capture.win32_hooks import Win32HookManager, hook_keyboard_and_mouse
from .feedback import FeedbackEntry, FeedbackLoop
from .monitoring import (
    AnomalyDetector,
    AnomalyEvent,
    AnomalyType,
    LiveMonitor,
    MonitorConfig,
)
from .orchestration import (
    Agent,
    AgentCapability,
    AgentState,
    Orchestrator,
    SharedMemory,
    Task,
    TaskPriority,
    TaskStatus,
    orchestrate,
)
from .store.lancedb_store import FailurePatternStore

__all__ = [
    "Recorder",
    "record",
    "wrap",
    "wrap_anthropic",
    "capture_dom",
    "capture_accessibility",
    "diff_snapshots",
    "Win32HookManager",
    "hook_keyboard_and_mouse",
    "AsyncRecorder",
    "async_record",
    "Agent",
    "AgentState",
    "AgentCapability",
    "Task",
    "TaskStatus",
    "TaskPriority",
    "SharedMemory",
    "Orchestrator",
    "orchestrate",
    "FailurePatternStore",
    "AnomalyDetector",
    "AnomalyEvent",
    "AnomalyType",
    "LiveMonitor",
    "MonitorConfig",
    "register_check",
    "CheckResult",
    "run_all_checks",
    "get_registered_checks",
    "FeedbackLoop",
    "FeedbackEntry",
]
__version__ = "0.9.1"

# v0.6.0 Exports
# v0.9.0 Exports — Distributed Tracing, Cross-Platform Hooks, Analytics, A2A
from .a2a import (
    A2ACoordinator,
    A2AMessage,
    AgentProtocol,
    Blackboard,
    MessageBus,
    MessagePriority,
    MessageType,
)
from .capture.cache import SemanticCache
from .compliance import (
    ComplianceAuditor,
    ComplianceChecker,
    Regulation,
    ViolationSeverity,
    create_compliance_checker,
    enable_compliance_auditing,
)

# v0.9.1 Exports — Regression Testing, Trace Diff, Natural Language Search, Live Streaming
from .diff import TraceDiffer, TraceDiffViewer, diff_traces
from .distributed.tracer import (
    Span,
    SpanContext,
    SpanKind,
    SpanStatus,
    StatusCode,
    TardisSpanExporter,
    TextMapPropagator,
    Tracer,
    get_global_tracer,
    set_global_tracer,
)
from .memory import KnowledgeGraph, create_shared_memory, enable_knowledge_sharing
from .memory import SharedMemory as KnowledgeSharedMemory

# v0.8.0 Exports — ML Classification, Semantic Cache, Tool Registry, Dashboard
from .ml_classifier import MLFailureClassifier, StatisticalClassifier
from .monitoring.analytics import (
    AnalyticsCollector,
    MetricHistory,
    MetricSnapshot,
    TrendAnalyzer,
)
from .monitoring.dashboard import DashboardServer
from .orchestration.tool_registry import (
    SecurityError,
    ToolDefinition,
    ToolParameter,
    ToolPermission,
    ToolRegistry,
)
from .os_integration.input_hooks import InputEvent, PlatformHookManager, hook_input
from .os_integration.kernel_tracer import KernelTracer
from .predictive.preventer import PredictiveFailurePrevention, RiskLevel
from .production.shadow_mode import ProductionIntelligence, ShadowModeStatus
from .redteam import (
    AdversarialDefense,
    AttackResult,
    AttackType,
    RedTeamAgent,
    enable_adversarial_defense,
    enable_red_team,
)
from .regression import RegressionTestGenerator, RegressionTestSuite, TestCase
from .repair.repair_engine import AutonomousRepairEngine

# v0.7.0 Exports
from .replay.time_travel import (
    TimeTravelReplay,
    TimeTravelTracer,
    create_replay_engine,
    enable_time_travel_tracing,
)
from .routing import ComplexityAnalyzer, CostAwareRouter, create_router
from .search import PromptTraceSearcher, SearchResult
from .streaming import (
    StreamEvent,
    StreamEventType,
    StreamSession,
    TraceStreamClient,
    TraceStreamer,
    start_stream_server,
)
from .swarm.swarm_debugger import CollaborativeSwarmDebugger

__all__ += [
    # v0.6.0
    "PredictiveFailurePrevention",
    "RiskLevel",
    "AutonomousRepairEngine",
    "KernelTracer",
    "CollaborativeSwarmDebugger",
    "ProductionIntelligence",
    "ShadowModeStatus",
    # v0.7.0
    "TimeTravelTracer",
    "TimeTravelReplay",
    "create_replay_engine",
    "enable_time_travel_tracing",
    "CostAwareRouter",
    "ComplexityAnalyzer",
    "create_router",
    "ComplianceAuditor",
    "ComplianceChecker",
    "Regulation",
    "ViolationSeverity",
    "enable_compliance_auditing",
    "create_compliance_checker",
    "KnowledgeGraph",
    "KnowledgeSharedMemory",
    "create_shared_memory",
    "enable_knowledge_sharing",
    "RedTeamAgent",
    "AdversarialDefense",
    "AttackType",
    "AttackResult",
    "enable_red_team",
    "enable_adversarial_defense",
    # v0.8.0
    "MLFailureClassifier",
    "StatisticalClassifier",
    "SemanticCache",
    "ToolRegistry",
    "ToolParameter",
    "ToolPermission",
    "ToolDefinition",
    "SecurityError",
    "DashboardServer",
    # v0.9.0
    "Span",
    "SpanContext",
    "SpanKind",
    "SpanStatus",
    "StatusCode",
    "Tracer",
    "TextMapPropagator",
    "TardisSpanExporter",
    "get_global_tracer",
    "set_global_tracer",
    "hook_input",
    "InputEvent",
    "PlatformHookManager",
    "MetricSnapshot",
    "MetricHistory",
    "TrendAnalyzer",
    "AnalyticsCollector",
    "A2AMessage",
    "A2ACoordinator",
    "AgentProtocol",
    "Blackboard",
    "MessageBus",
    "MessageType",
    "MessagePriority",
    # v0.9.1
    "RegressionTestGenerator",
    "RegressionTestSuite",
    "TestCase",
    "TraceDiffer",
    "TraceDiffViewer",
    "diff_traces",
    "PromptTraceSearcher",
    "SearchResult",
    "TraceStreamer",
    "TraceStreamClient",
    "StreamEvent",
    "StreamEventType",
    "StreamSession",
    "start_stream_server",
]
