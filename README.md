# TARDIS — Time-Travel Debugger for AI Agents

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![Version](https://img.shields.io/badge/version-0.9.1-purple)
![CI](https://github.com/welshe/TARDIS/actions/workflows/ci.yml/badge.svg)

> **Security:** See [SECURITY.md](SECURITY.md) for threat model, vulnerability reporting, and known limitations.

## Contents
- [The 20 second demo](#the-20-second-demo)
- [Feature Status](#feature-status)
- [Security Warnings](#security-warnings)
- [Install](#install)
- [Quickstart](#quickstart)
- [Core Features](#core-features)
- [v0.6.0 Features](#v060-features)
- [v0.7.0 Features](#v070-features)
- [v0.8.1 Test Coverage](#v081-test-coverage)
- [v0.9.0 Features](#v090-features)
- [v0.9.1 Features](#v091-features)
- [CLI Reference](#cli-reference)
- [Core Concepts](#core-concepts)
- [Project Structure](#project-structure)
- [Roadmap](#roadmap)
- [License](#license)

---

**The flight recorder that lets you rewind agent failures.**

Every computer-use agent fails at step 147 of 150. When it does, you get a screen recording and a guess. TARDIS gives you deterministic replay, causal graphs, automatic autopsy, OS-level input hooks, and multi-agent orchestration — all traced and time-travel-debuggable.

> `npm ERR! EBUSY` once is a bug. Twice is a dataset you should have captured.

### The 20 second demo

```bash
git clone https://github.com/welshe/TARDIS
cd TARDIS
pip install -e ".[dev]"
tardis init
python examples/basic_agent.py
tardis replay <trace_id> --from 20
tardis autopsy <trace_id>
```

---

## Feature Status

| Feature | Status | Since | Notes |
|---------|--------|-------|-------|
| LLM Proxy (OpenAI/Anthropic) | **Implemented** | v0.1 | Token/cost tracking, zero code changes |
| SQLite Store | **Implemented** | v0.1 | Append-only, parameterized queries |
| Deterministic Replay | **Implemented** | v0.1 | Breakpoints, edit injection, diff |
| Causal Graph | **Implemented** | v0.1 | Critical path, loop detection, DOT export |
| Failure Classifier | **Implemented** | v0.1 | 8-method classifier with confidence |
| DOM/Accessibility Snapshots | **Implemented** | v0.2 | Playwright, CDP, UI Automation |
| Win32 Keyboard/Mouse Hooks | **Implemented** | v0.3 | OS-level input via SetWindowsHookEx |
| Multi-Agent Orchestration | **Implemented** | v0.3 | Capability routing, shared memory |
| LanceDB Vector Store | **Implemented** | v0.3 | Failure pattern similarity search |
| Real-Time Anomaly Detection | **Implemented** | v0.5 | Z-score, rolling windows, alerts |
| Async Recorder | **Implemented** | v0.5 | asyncio/Playwright compatible |
| Plugin System | **Implemented** | v0.5 | Custom failure checks |
| Feedback Loop / Fine-Tuning | **Implemented** | v0.5 | OpenAI, Anthropic, RLHF export |
| Predictive Failure Prevention | **Implemented** | v0.6 | Vector similarity risk scoring via real store lookups |
| Autonomous Repair | **Implemented** | v0.6 | LLM-powered hypothesis generation + structural validation |
| eBPF/ETW Kernel Tracing | **Implemented** | v0.6 | Privilege drop, fail-closed, cross-platform |
| Swarm Debugging | **Implemented** | v0.6 | LLM-powered or rule-based fallback, per-agent timeouts |
| Production Shadow Mode | **Implemented** | v0.6 | Read-only, anomaly detection, regression test generation |
| Red-Teaming & Adversarial Defense | **Implemented** | v0.7 | Heuristic detection, sandboxed execution |
| Cost-Aware Model Routing | **Implemented** | v0.7 | Complexity scoring, budget enforcement |
| Time-Travel Replay Engine | **Implemented** | v0.7 | System state snapshots, bidirectional stepping |
| Compliance Auto-Auditor | **Implemented** | v0.7 | GDPR, HIPAA, EU AI Act, SOC2, PCI DSS, CCPA |
| Knowledge Graph Memory | **Implemented** | v0.7 | Cross-agent shared knowledge with BFS traversal |
| **ML-Assisted Classification** | **Implemented** | v0.8 | scikit-learn (optional) + statistical fallback, model persistence |
| **Semantic Response Cache** | **Implemented** | v0.8 | Trigram vector similarity, TTL, LRU eviction, per-model isolation |
| **Agent Tool Registry** | **Implemented** | v0.8 | Security-scanned registration, schema validation, rate limiting |
| **Real-Time Web Dashboard** | **Implemented** | v0.8 | Localhost HTTP server with live monitoring, alert visualization |
| **Distributed Tracing** | **Implemented** | v0.9 | OpenTelemetry-compatible span propagation, cross-process traces |
| **Cross-Platform Input Hooks** | **Implemented** | v0.9 | macOS (CGEventTap) + Linux (evdev/X11) keyboard/mouse capture |
| **Dashboard Analytics** | **Implemented** | v0.9 | Time-series metrics, trend analysis, forecast, model usage breakdown |
| **Agent-to-Agent Protocol** | **Implemented** | v0.9 | Message bus, blackboard shared state, capability negotiation |
| **Automated Regression Test Generator** | **Implemented** | v0.9.1 | Trace-to-pytest with SHA-256 digest, overwrite protection, batch generation |
| **Trace Diff Viewer** | **Implemented** | v0.9.1 | Side-by-side step comparison, divergence reporting, HTML export |
| **Natural Language Trace Search** | **Implemented** | v0.9.1 | Query expansion, LanceDB vector + keyword fallback, failure type filtering |
| **Real-Time Trace Streaming** | **Implemented** | v0.9.1 | WebSocket server/client, session management, rate limiting, collaboration support |

---

## Security Warnings

> **This tool captures sensitive data by design.** Read this section before enabling any features.

### Win32 Keyboard/Mouse Hooks

**Risk:** Captures ALL keystrokes system-wide, including passwords, PINs, and private messages. This is an OS-level keylogger. Even with character redaction, key positions (vk_code/scan_code) can leak passwords via timing analysis.

**Mitigations:**
- Opt-in only — never enabled by default
- Character redaction (`redact_characters=True`) — replaces typed characters with *
- VK code redaction (`redact_vk_codes=True`) — zeros vk_code and scan_code to prevent key-position reconstruction
- PII redaction in Recorder strips password/token/SSN/credit card fields before storage
- Events stored in memory only (deque) — buffer is **zeroed on `stop()`** to prevent crash-dump leaks
- `hook_keyboard_and_mouse()` requires explicit call

**Never enable in production environments without user consent.**

### Kernel Tracing (eBPF/ETW)

**Risk:** Requires root/admin privileges. Captures system calls, file access, and process activity.

**Mitigations:**
- Privilege drop: After bpftrace starts, privileges dropped to `nobody` (Linux). Admin check on Windows.
- Fail-closed: raises RuntimeError if backend fails to initialize
- No arbitrary filter strings — trace scripts are hardcoded
- BPF verifier safety checked before loading on Linux
- ETW backend falls back to psutil userspace monitoring (full ETW consumer requires platform-specific deps)

### DOM Snapshot Capture

**Risk:** Captures page content including form data, credentials in autofill, and session tokens.

**Mitigations:**
- PII redaction enabled by default (`redact=True`) — masks passwords, tokens, emails, SSNs, card numbers
- URL validation: localhost-only by default. Blocks `file://`, `gopher://`, `ftp://` schemes and RFC 1918/link-local IP ranges
- Custom allowlists supported via `url_allowlist` parameter

### Compliance & Governance Auto-Auditor

> **LEGAL DISCLAIMER:** This tool provides automated compliance checking guidance only. It is **NOT** legal advice. Always consult qualified legal counsel.

### Semantic Cache

**Risk:** Cached LLM responses may contain sensitive data and persist on disk.

**Mitigations:** Local-only (SHA-256 content-addressed), no external sync, TTL expiry, explicit `clear()`.

### Web Dashboard

**Risk:** Exposes monitoring data over HTTP.

**Mitigations:** Localhost-only binding (127.0.0.1), read-only API, designed for local dev only.

### Cross-Platform Input Hooks

**Risk:** Same as Win32 hooks — captures all keyboard/mouse input system-wide on macOS and Linux.

**Mitigations:** Same as Win32 — opt-in only, character/vk_code redaction, memory-only buffer, cleared on stop. macOS requires Accessibility permissions (prompted by OS). Linux evdev requires `input` group membership.

### Distributed Tracing

**Risk:** Span data may contain sensitive request/response payloads.

**Mitigations:** Span attributes are bounded (128 per span, 1KB resource). Exported spans stored locally only by default. TardisSpanExporter applies the same PII redaction as the core recorder.

### A2A Protocol

**Risk:** In-process message bus could leak data between agents if misconfigured.

**Mitigations:** Rate limiting (100 msgs/min per agent), bounded queues (100 per agent), message TTL (max 24h), blackboard value size cap (10KB), namespace limits (10,000). All in-process — no network exposure.

### Trace Streaming

**Risk:** WebSocket server could expose trace data if bound to non-loopback address.

**Mitigations:** Localhost-only binding (127.0.0.1) by default. Rate limiting (200 events/sec per session). Max 50 subscribers per session. Session TTL (1 hour inactivity). Clients cannot mutate trace state — read-only streaming only.

### Regression Test Generator

**Risk:** Generated test files written to disk could contain sensitive trace data.

**Mitigations:** Output defaults to `.tardis/regression_tests/` directory. Generated tests reference traces by ID and load from local SQLite only — no sensitive data embedded in test files. SHA-256 digest for overwrite protection.

### Natural Language Trace Search

**Risk:** Query expansion and search could expose failure patterns.

**Mitigations:** All search is local — no external API calls. Queries expanded locally with hardcoded synonyms. LanceDB results bounded by limit parameter. Keyword fallback operates on local SQLite store only.

### General

- All data stored locally in `.tardis/` with owner-only permissions on Unix
- SQLite queries are parameterized (SQL injection prevented)
- LanceDB trace IDs validated against regex patterns
- Database paths resolved and checked against working directory (path traversal blocked)
- SHA-256 hashing used throughout
- Environment variables in time-travel snapshots are redacted (secrets, tokens, API keys masked)
- Tool Registry security-scans every registration for injection patterns
- ML Classifier training data stays local — no external model loading

---

## Install

```bash
git clone https://github.com/welshe/TARDIS
cd TARDIS
pip install -e ".[dev]"
tardis health
```

### Core Dependencies

| Dependency | Purpose |
|---|---|
| `pydantic>=2.5` | Data models |
| `click>=8.1` | CLI framework |
| `rich>=13.0` | Terminal formatting |
| `mss>=9.0` | Screen capture |
| `Pillow>=10.0` | Image analysis |
| `openai>=1.0` | LLM proxy |
| `lancedb>=0.6` | Vector store |
| `psutil>=5.9` | Process monitoring |

### Install Extras

```bash
pip install -e ".[dev]"            # Testing (pytest, ruff)
pip install -e ".[dom]"            # Browser DOM capture (playwright)
pip install -e ".[accessibility]"  # Windows accessibility tree (uiautomation)
pip install -e ".[cdp]"            # Chrome DevTools Protocol (websockets)
pip install -e ".[all]"            # Everything
pip install -e ".[redteam]"        # Red-teaming
pip install scikit-learn           # Optional: ML-assisted classification
pip install evdev                  # Optional: Linux input hook backend
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TARDIS_ENABLE_HOOKS` | `0` | Enable keyboard/mouse hook CLI commands |
| `TARDIS_ENABLE_KERNEL_TRACING` | `0` | Enable eBPF/ETW backend selection |
| `TARDIS_REDACT_PII` | `1` | Disable automatic PII redaction |
| `TARDIS_LOG_LEVEL` | `INFO` | Logging verbosity |

---

## Quickstart

```python
import tardis
from openai import OpenAI

rec = tardis.Recorder().start()
client = tardis.wrap(OpenAI())

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "fix the EBUSY error"}],
)

trace = rec.stop()
```

### ML-Assisted Classification

```python
from tardis.ml_classifier import MLFailureClassifier

classifier = MLFailureClassifier()
classifier.train([
    (trace_1, FailureType.grounding_failure),
    (trace_2, FailureType.tool_failure),
])
ftype, confidence = classifier.classify(new_trace)
```

### Agent Tool Registry

```python
from tardis.orchestration.tool_registry import ToolRegistry, ToolParameter

registry = ToolRegistry(recorder=my_recorder)

@registry.register(
    name="read_file",
    description="Read contents of a file",
    parameters=[ToolParameter(name="path", type="string", required=True)],
)
def read_file(path: str) -> str:
    with open(path) as f:
        return f.read()

result = registry.execute("read_file", {"path": "data.txt"})
```

### Semantic Cache

```python
from tardis.capture.cache import SemanticCache

cache = SemanticCache(similarity_threshold=0.9, ttl_seconds=3600)
cached = cache.find_similar(messages, model="gpt-4o")
if cached:
    response = cached.response
else:
    response = client.chat.completions.create(...)
    cache.store(messages, response, model="gpt-4o")
```

### Web Dashboard

```python
from tardis.monitoring import LiveMonitor, MonitorConfig
from tardis.monitoring.dashboard import DashboardServer

monitor = LiveMonitor(MonitorConfig(refresh_interval=1.0)).start()
dashboard = DashboardServer(monitor=monitor, port=9090)
dashboard.start()
# Open http://localhost:9090
```

---

## Core Features

### Win32 Hooks

**The differentiator.** Most frameworks log API calls. TARDIS captures every keyboard press and mouse movement at the OS level.

> **WARNING:** Captures system-wide keyboard input including passwords. Opt-in only.

```python
from tardis.capture.win32_hooks import hook_keyboard_and_mouse

rec = tardis.Recorder().start()
mgr = hook_keyboard_and_mouse(
    recorder=rec,
    redact_characters=True,
    redact_vk_codes=True,
)
mgr.stop()
trace = rec.stop()
```

### Multi-Agent Orchestration

```python
from tardis.orchestration import Agent, AgentCapability, Task, Orchestrator

orch = Orchestrator()
orch.register(Agent("browser", capabilities={AgentCapability.browser}))
orch.submit(Task("browse login page", required_capabilities={"browser"}))
results = orch.run_parallel(fn_map={"browser": my_fn})
```

### Agent Tool Registry

Secure registration with security scanning, schema validation, and rate limiting.

```python
from tardis.orchestration.tool_registry import ToolRegistry, ToolParameter, ToolPermission

registry = ToolRegistry()

@registry.register(
    name="search",
    permission=ToolPermission.SANDBOXED,
    rate_limit=60,
)
def search(query: str) -> list:
    return perform_search(query)
# Blocked names: shell_exec, eval, os.system
# Warned params: "command", path traversal
```

### LanceDB Failure Pattern Store

```python
from tardis.store.lancedb_store import FailurePatternStore

store = FailurePatternStore()
store.index_trace(trace)
similar = store.search_similar(trace, limit=5)
```

### ML-Assisted Classification

Three-tier engine: scikit-learn RandomForest (when installed) > statistical trigram vectors > fallback.

```python
from tardis.ml_classifier import MLFailureClassifier

classifier = MLFailureClassifier()
classifier.train([(t1, FailureType.grounding_failure), (t2, FailureType.tool_failure)])
classifier.save_model("my_model")
classifier.load_model("my_model")
print(classifier.backend)  # "sklearn", "statistical", or "none"
```

### Semantic Response Cache

```python
from tardis.capture.cache import SemanticCache

cache = SemanticCache(similarity_threshold=0.92, ttl_seconds=3600, max_entries=5000)
cached = cache.find_similar(messages, model="gpt-4o")
stats = cache.get_statistics()
print(f"Hit rate: {stats['hit_rate']:.1%}, Tokens saved: {stats['tokens_saved']}")
```

### Real-Time Anomaly Detection

```python
from tardis.monitoring import LiveMonitor, MonitorConfig

config = MonitorConfig(refresh_interval=1.0, anomaly_threshold=0.7)
monitor = LiveMonitor(config).start()
```

### Real-Time Web Dashboard

```python
from tardis.monitoring.dashboard import DashboardServer

dashboard = DashboardServer(monitor=monitor, port=9090)
dashboard.start()
# Visit http://localhost:9090 for live metrics and alerts
```

### Async Support

```python
async with tardis.async_record("my_session") as rec:
    response = await client.chat.completions.create(...)
```

### Plugin System

```python
from tardis.autopsy.plugins import register_check, CheckResult

@register_check("api_rate_limit", priority=2)
def check_rate_limit(trace, steps):
    ...
```

### Feedback Loop for Fine-Tuning

```python
from tardis.feedback import FeedbackLoop

feedback = FeedbackLoop()
feedback.export_fine_tuning_dataset("training.jsonl", model_format="openai")
```

---

## v0.6.0 Features

### Predictive Failure Prevention (Pre-cog Mode)

Uses real LanceDB vector similarity search — no hardcoded IDs.

```python
from tardis.predictive.preventer import PredictiveFailurePrevention

precog = PredictiveFailurePrevention(vector_store=store, threshold=0.85)
result = precog.analyze_action(action, current_state)
print(f"Risk: {result.risk_level}, Action: {result.suggested_action}")
```

### Autonomous Repair

LLM-powered hypothesis generation or advisory fallback. Sandboxed structural validation.

```python
from tardis.repair.repair_engine import AutonomousRepairEngine

engine = AutonomousRepairEngine(agent_executor=my_llm)
hypotheses = engine.generate_hypotheses(root_cause, trace)
engine.apply_fix(best_hypothesis, confirm=True)
```

### Deep OS Integration (eBPF/ETW)

| Backend | Platform | Requirements |
|---|---|---|
| `ebpf` | Linux | root + bpftrace |
| `etw` | Windows | admin (falls back to psutil) |
| `oslog` | macOS | root |
| `userspace` | All | psutil |

### Collaborative Swarm Debugging

```python
from tardis.swarm.swarm_debugger import CollaborativeSwarmDebugger

swarm = CollaborativeSwarmDebugger(llm_client=client, agent_timeout=60)
report = swarm.diagnose(trace)
```

### Production Shadow Mode

```python
from tardis.production.shadow_mode import ProductionIntelligence, ShadowModeStatus

shadow = ProductionIntelligence()
shadow.set_mode(ShadowModeStatus.ACTIVE)
shadow.record_trace(trace_dict)
```

---

## v0.7.0 Features

### Red-Teaming & Adversarial Defense

```python
from tardis.redteam import enable_red_team, enable_adversarial_defense

redteam = enable_red_team(target_system=agent, continuous=True, sandbox=True)
defense = enable_adversarial_defense(alert_callback=print)
report = redteam.get_report()
```

### Cost-Aware Model Routing

```python
from tardis.routing import create_router

router = create_router(budget_limit=100.0)
router.register_model(router.models["gpt-4o"], client=openai_client)
result = await router.route_and_execute("Explain quantum computing")
```

### Time-Travel Replay Engine

```python
from tardis.replay.time_travel import enable_time_travel_tracing, create_replay_engine

tracer = enable_time_travel_tracing()
replay = create_replay_engine(trace_id="my_trace")
replay.rewind_to(step_index=20)
event = replay.step_forward()
```

### Compliance Auto-Auditor

> **LEGAL DISCLAIMER:** Guidance only. Not legal advice. Consult qualified counsel.

Supported: GDPR, HIPAA, EU AI Act, SOC2, PCI DSS, CCPA.

### Knowledge Graph Memory

```python
from tardis.memory import enable_knowledge_sharing

memory = enable_knowledge_sharing(agent_id="agent_01")
memory.store_failure_pattern("DOM Element Not Found", "Selector fails after nav",
    pattern_data={"error": "element_missing"}, tags=["dom", "navigation"])
similar = memory.find_similar_failures("Element not found", tags=["dom"])
```

---

## v0.8.1 Test Coverage

Comprehensive test coverage across 21 previously untested modules, bringing the test suite from 185 to **484 tests**.

| Test File | Module(s) Covered | Tests |
|---|---|---|
| `test_replay.py` | `replay/engine.py` — ReplayEngine, breakpoints, pattern analysis | 14 |
| `test_time_travel.py` | `replay/time_travel.py` — Tracer, Replay, SystemState, env redaction | 35 |
| `test_repair_engine.py` | `repair/repair_engine.py` — Hypothesis generation, simulation, injection blocking | 20 |
| `test_redteam_full.py` | `security/red_team.py` — Attack execution, adversarial defense, blocklist | 25 |
| `test_win32_hooks.py` | `platform/win32_hooks.py` — VK codes, mouse events, character redaction | 14 |
| `test_kernel_tracer.py` | `os_integration/kernel_tracer.py` — Backend selection, lifecycle, integrity | 18 |
| `test_monitoring.py` | `monitoring/live_monitor.py` — Anomaly detector, dashboard server, alerts | 24 |
| `test_memory.py` | `memory/knowledge_graph.py`, `memory/shared_memory.py` — Graph CRUD, shared state | 26 |
| `test_feedback.py` | `feedback/feedback_loop.py` — Export formats, statistics, training pairs | 18 |
| `test_swarm.py` | `orchestration/swarm_debugger.py` — LLM/rule-based diagnosis, injection detection | 21 |
| `test_shadow_mode.py` | `security/shadow_mode.py` — Shadow modes, regression suite, anomaly detection | 16 |
| `test_preventer.py` | `replay/predictive_preventer.py` — Risk scoring, cache, what-if simulation | 16 |
| `test_capture_proxies.py` | `capture/llm_proxy.py`, `anthropic_proxy.py`, `tool_wrapper.py`, `async_recorder.py` | 16 |
| `test_plugins.py` | `plugins/autopsy.py` — Check registration, priority sorting, error handling | 9 |
| `test_platform.py` | `os_integration/platform_detector.py` — Platform detection, screen capture, filesystem | 13 |
| `test_cli.py` | `cli.py` — CLI commands: health, init, list, show, replay, orch, hook | 11 |

### Source Fixes

- **`replay/time_travel.py`**: Fixed `SystemState` dataclass field ordering (`thread_id`, `memory_hash` now have defaults), added `thread_id` to serialization/deserialization

---

## v0.9.0 Features

### Distributed Tracing

OpenTelemetry-compatible span propagation for cross-process and cross-machine traces.

```python
from tardis.distributed import Tracer, TextMapPropagator, TardisSpanExporter

tracer = Tracer(name="my-service", exporter=TardisSpanExporter())

with tracer.start_as_current_span("http_request") as span:
    span.set_attribute("http.method", "GET")
    span.set_attribute("http.url", "/api/users")

# Propagate context across processes
propagator = TextMapPropagator()
headers = {}
propagator.inject(span.context, headers)
# Send headers to remote service...
remote_ctx = propagator.extract(headers)
```

### Cross-Platform Input Hooks

Unified keyboard/mouse capture across Windows, macOS, and Linux.

```python
from tardis.os_integration.input_hooks import hook_input

manager = hook_input(
    redact_characters=True,
    redact_vk_codes=True,
)
# Auto-detects platform: Win32 (Windows), CGEventTap (macOS), evdev/X11 (Linux)
events = manager.get_recent(seconds=30)
manager.stop()
```

| Platform | Backend | Requirements |
|---|---|---|
| Windows | `Win32HookManager` | None (uses existing win32_hooks) |
| macOS | `MacOSHookManager` | Accessibility permissions (CGEventTap) or polling fallback |
| Linux | `LinuxHookManager` | `evdev` (preferred) or X11 record extension |

### Dashboard Analytics

Time-series metrics collection, trend analysis, and forecasting.

```python
from tardis.monitoring.analytics import AnalyticsCollector, TrendAnalyzer

collector = AnalyticsCollector(interval=1.0)
collector.register_collector(lambda: {"total_steps": 100, "error_count": 3})
collector.start()

# Get trend analysis
analytics = collector.get_dashboard_analytics()
print(analytics["trends"]["total_cost_usd"]["direction"])  # "increasing"/"decreasing"/"stable"

# Linear regression
result = TrendAnalyzer.linear_regression([1, 2, 3], [2, 4, 6])
print(result["slope"])  # 2.0
```

### Agent-to-Agent Protocol (A2A)

Structured inter-agent communication with message bus, shared blackboard, and capability negotiation.

```python
from tardis.a2a import MessageBus, Blackboard, A2ACoordinator, AgentProtocol, A2AMessage, MessageType

class MyAgent(AgentProtocol):
    def handle_message(self, message: A2AMessage) -> A2AMessage:
        return A2AMessage(
            type=MessageType.RESPONSE,
            from_agent=self.agent_id,
            to_agent=message.from_agent,
            subject="reply",
            payload={"result": "done"},
            reply_to=message.id,
        )
    def get_capabilities(self):
        return ["browser", "code"]

bus = MessageBus()
blackboard = Blackboard()
coordinator = A2ACoordinator(bus=bus, blackboard=blackboard)

agent = MyAgent(agent_id="agent_01", name="Browser Agent")
coordinator.register_agent(agent)

# Share state between agents
coordinator.share_state("task", "url", "https://example.com")

# Delegate tasks to capable agents
result = coordinator.delegate_task("browse login page", "browser")
```

---

## v0.9.1 Features

### Automated Regression Test Generator

Generates pytest test suites from failed traces with deterministic replay validation and autopsy classification checks.

```python
from tardis.regression import RegressionTestGenerator

gen = RegressionTestGenerator(output_dir=".tardis/regression_tests", overwrite=True)
case = gen.generate_from_trace("my_trace_id")
print(f"Generated: {case.test_file}")

# Batch generate for all failed traces
cases = gen.generate_from_all_failed_traces(limit=100)
```

```bash
tardis gen-test <trace_id>              Generate regression test for one trace
tardis gen-all-tests --limit 50        Generate tests for all failed traces
```

### Trace Diff Viewer

Side-by-side comparison of two traces with step-level divergence reporting and HTML export.

```python
from tardis.diff import TraceDiffer, TraceDiffViewer

differ = TraceDiffer()
report = differ.diff("trace_a", "trace_b")
print(f"Divergent steps: {len(report.divergent_steps)}")
print(f"Cost delta: ${report.cost_diff:+.4f}")

viewer = TraceDiffViewer()
viewer.render(report)
html = viewer.render_html(report)
```

```bash
tardis trace-diff <trace_id> --target <other_trace_id>
```

### Natural Language Trace Search

Search your trace history using natural language queries with automatic failure-synonym expansion and LanceDB vector similarity.

```python
from tardis.search import PromptTraceSearcher

searcher = PromptTraceSearcher(min_score=0.15)
results = searcher.search("stuck in loop after timeout", limit=10)
for r in results:
    print(f"[{r.confidence_pct}%] {r.trace_id}: {r.description[:80]}")

# Filter by failure type
results = searcher.search("auth error", failure_type="environment_drift")
```

```bash
tardis search "stuck in tool loop" --limit 10
tardis search "permission denied" --type tool_failure
```

### Real-Time Trace Streaming

WebSocket-based live streaming for collaborative debugging sessions.

```python
from tardis.streaming import TraceStreamer, StreamEvent, StreamEventType

streamer = TraceStreamer(host="127.0.0.1", port=9876)
streamer.create_session("my_trace")
streamer.start()

# Publish events as trace progresses
event = StreamEvent(
    trace_id="my_trace",
    event_type=StreamEventType.STEP_ADDED,
    data={"step_index": 42, "type": "tool_call"},
)
streamer.publish_event(event)
```

```bash
tardis stream <trace_id> --port 9876 --duration 60
```

---

## CLI Reference

```
tardis init                                          Create storage
tardis health                                        Check DB + LanceDB
tardis list                                          List recent traces
tardis show <id>                                     Render causal graph
tardis show <id> --export-dot graph.dot              Export as DOT
tardis replay <id> [--from N] [--to N]               Deterministic replay
tardis replay <id> --edit-tool-output '{"code": 0}'  Inject edited output
tardis autopsy <id>                                  Root-cause classification
tardis similar <id> [--limit N]                      Find similar failures
tardis vector-stats                                  LanceDB statistics
tardis analyze <id>                                  Pattern analysis
tardis export <id> --format json                     Export trace
tardis hook --duration 10                            Win32 input capture
tardis orch demo --agents 2 --tasks 5                Orchestration demo
tardis gen-test <id>                                 Generate regression test
tardis gen-all-tests [--limit N]                     Batch generate tests
tardis trace-diff <id> --target <id>                 Compare two traces
tardis search <query> [--limit N] [--type TYPE]      Natural language search
tardis stream <id> [--port N] [--duration N]         Live trace streaming
```

---

## Core Concepts

### Traces & Steps

| Step Type | Description |
|---|---|
| `llm_call` | LLM prompt + completion |
| `tool_call` | Tool invocation |
| `error` | Captured exception |
| `screen_frame` | Screen capture |
| `dom_snapshot` | Browser DOM tree |
| `accessibility_snapshot` | UI Automation tree |
| `raw_input` | OS-level keyboard/mouse event |
| `orchestration_event` | Multi-agent decision |

### Failure Classification

| Type | Detection |
|---|---|
| `reasoning_failure` | Hash repetition |
| `grounding_failure` | UI element errors, layout shift |
| `tool_failure` | Error hash chains, timeouts |
| `memory_failure` | Context-length exceeded |
| `environment_drift` | Auth/rate limit/network errors |

### Causal Graph

Edges: `tool_informs_llm`, `llm_calls_tool`, `causes_error`, `error_propagation`, `context_chain`, `llm_uses_screen`, `llm_uses_snapshot`, `temporal`.

---

## Project Structure

```
src/tardis/
  __init__.py, models.py, config.py, cli.py
  ml_classifier.py              # ML-assisted classification (v0.8)
  capture/
    recorder.py, async_recorder.py, llm_proxy.py
    anthropic_proxy.py, tool_wrapper.py, screen.py
    dom_snapshot.py, win32_hooks.py
    cache.py                    # Semantic response cache (v0.8)
  orchestration/
    agent.py, task.py, memory.py, orchestrator.py
    tool_registry.py            # Secure tool registration (v0.8)
  store/                        # SQLite + LanceDB
  replay/                       # Deterministic + time-travel
  causal/                       # Causal graph
  autopsy/                      # Failure classifier + plugins
  monitoring/                   # Anomaly detection + dashboard + analytics (v0.9)
  feedback/                     # Fine-tuning export
  utils/                        # Hashing, platform detection
  os_integration/               # Kernel tracing + cross-platform input hooks (v0.9)
  predictive/                   # Pre-cog mode
  repair/                       # Autonomous repair
  swarm/                        # Swarm debugging
  production/                   # Shadow mode
  redteam/                      # Red-teaming
  routing/                      # Model routing
  compliance/                   # Compliance auditor
  memory/                       # Knowledge graph
  distributed/                  # Distributed tracing (v0.9)
  a2a/                          # Agent-to-agent protocol (v0.9)
  regression/                   # Automated regression test generation (v0.9.1)
  diff/                         # Trace diff viewer (v0.9.1)
  search/                       # Natural language trace search (v0.9.1)
  streaming/                    # Real-time trace streaming (v0.9.1)

tests/                          # 796 tests
examples/                       # 6 example scripts
```

---

## Roadmap

- **v0.1** — LLM wrappers, SQLite store, deterministic replay, causal graph
- **v0.2** — DOM/accessibility snapshots, tree diff, window management
- **v0.3** — Win32 hooks, multi-agent orchestration, LanceDB
- **v0.4** — Thread-safe recorder, SQL injection prevention
- **v0.5** — Anomaly detection, async recorder, plugins, feedback loop
- **v0.6** — Pre-cog mode, autonomous repair, eBPF/ETW, swarm, shadow mode
- **v0.7** — Red-teaming, cost-aware routing, time-travel, compliance, knowledge graph
- **v0.8.0** — ML classification, semantic cache, tool registry, web dashboard, security audit
- **v0.8.1** — Comprehensive test coverage: 484 tests across 16 new test files, source fixes for dataclass field ordering, replay trace cleanup
- **v0.9** — Distributed tracing, cross-platform input hooks (macOS/Linux), dashboard analytics, A2A protocol, 679 tests
- **v0.9.1** *(current)* — Regression test generator, trace diff viewer, natural language search, real-time streaming, 796 tests
- **v1.0** — Session replay with branching, visual diff engine, agent capability marketplace, zero-trust sandbox, deterministic time-travel snapshots

---

## License

MIT
