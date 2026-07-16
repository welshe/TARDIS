# TARDIS — Time-Travel Debugger for AI Agents

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

## Contents
- [20 second demo](#the-20-second-demo)
- [Why TARDIS](#why-tardis)
- [How It Works](#how-it-works)
- [Install](#install)
- [Quickstart](#quickstart)
- [CLI Reference](#cli-reference)
- [Core Concepts](#core-concepts)
- [Project Structure](#project-structure)
- [Roadmap](#roadmap)

**The flight recorder that lets you rewind agent failures.**

Every computer-use agent fails at step 147 of 150. When it does, you get a screen recording and a guess. TARDIS gives you deterministic replay, causal graphs, and automatic autopsy.

> `npm ERR! EBUSY` once is a bug. Twice is a dataset you should have captured.

### The 20 second demo

```bash
git clone https://github.com/welshe/TARDIS
cd TARDIS
pip install -e ".[dev]"

# Wrap your agent - zero code change for OpenAI / Anthropic
tardis init

# Run your agent normally
python examples/basic_agent.py

# It failed at step 23? Rewind to step 20 and see exactly what the model saw
tardis replay <trace_id> --from 20

# What actually broke?
tardis autopsy <trace_id>

# Output: ROOT CAUSE: grounding_failure - clicked [842, 410] but true button was at [842, 460] - window moved between frames
```

---

## Why TARDIS

Computer-use agents fail — often at step 147 of 150. Standard observability logs text. TARDIS logs **causality**:

- Every LLM prompt, completion, token count, and cost
- Every tool call, result, and error with duration
- Every screen frame, pixel diff, and layout shift
- Every DOM and accessibility tree snapshot for grounding analysis
- Content-addressed hashing for byte-for-byte deterministic replay
- Automatic failure classification with evidence and fix suggestions

---

## How It Works

![Architecture](assets/arch.png)

**Capture** → **Store** → **Replay** → **Autopsy**

1. **Capture** — Proxy wrappers intercept OpenAI and Anthropic calls, tool invocations, screen frames via Win32 hooks, DOM/accessibility tree snapshots — all with zero code changes to your agent logic.
2. **Store** — Every step is recorded in an append-only SQLite store with content-addressed hashing. Traces are immutable and time-indexed.
3. **Replay** — Deterministic engine rewinds to any step, injects edited tool outputs to explore what-if scenarios, and replays forward with breakpoint support and cross-trace diff.
4. **Autopsy** — A multi-pattern classifier scores confidence across 8 failure detection methods, collects supporting evidence, and generates specific fix suggestions.

---

## Install

```bash
git clone https://github.com/welshe/TARDIS
cd TARDIS
pip install -e ".[dev]"
tardis health
```

### Dependencies

| Dependency | Purpose |
|---|---|
| `pydantic>=2.5` | Data models (Trace, Step, FailureType) |
| `click>=8.1` | CLI framework |
| `rich>=13.0` | Terminal formatting |
| `mss>=9.0` | Cross-platform screen capture |
| `Pillow>=10.0` | Image diff, hashing, analysis |
| `openai>=1.0` | OpenAI API proxy |
| `lancedb>=0.6` | Vector store for failure patterns |

### Optional Backends

| Dependency | Extras | Purpose |
|---|---|---|
| `playwright>=1.40` | `dom` | Browser DOM snapshot capture |
| `websockets>=12.0` | `cdp` | Chrome DevTools Protocol DOM capture (lighter alternative) |
| `uiautomation>=2.0` | `accessibility` | Windows UI Automation accessibility tree capture |

Install extras: `pip install -e ".[dom]"` or `pip install -e ".[all]"`

---

## Quickstart
All snapshots are content-hashed and PII-redacted by default (password inputs -> ***). Enable full capture with `capture_dom(redact=False)`.
```python
import tardis
from openai import OpenAI

rec = tardis.Recorder().start()
client = tardis.wrap(OpenAI())

# your agent loop — unchanged
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "fix the EBUSY error"}],
)

trace = rec.stop()
# tardis replay <id> --from 5
# tardis autopsy <id>
```

For Anthropic:

```python
from anthropic import Anthropic
client = tardis.wrap_anthropic(Anthropic())
```

For DOM/accessibility snapshots:

```python
from tardis.capture.dom_snapshot import capture_dom, capture_accessibility, diff_snapshots

dom = capture_dom(url="https://example.com")
rec.log_dom_snapshot(dom)

acc = capture_accessibility()
rec.log_accessibility_snapshot(acc)

# Detect layout shifts between snapshots
diff = diff_snapshots(snapshot_before, snapshot_after)
```

---

## CLI Reference

```
tardis init                                          Create .tardis/ storage directory
tardis health                                        Check database status
tardis list                                          List traces with success/cost/tokens
tardis show <id>                                     Render causal graph
tardis show <id> --export-dot graph.dot              Export causal graph as DOT
tardis replay <id> [--from N] [--to N]               Deterministic replay
tardis replay <id> --edit-tool-output '{"code": 0}'  Inject edited tool output
tardis autopsy <id>                                  Root-cause classification report
tardis analyze <id>                                  Pattern analysis (LLM, errors, tools)
tardis export <id> --format json                     Export trace as JSON
tardis export <id> --format negative-pair            Export contrastive pair for RL
```

---

## Core Concepts

### Traces & Steps

A `Trace` is an ordered sequence of `Step` objects. Each step captures a single event:

| Step Type | Description |
|---|---|
| `llm_call` | LLM prompt + completion with token/cost metadata |
| `tool_call` | Tool invocation with input/output |
| `tool_result` | Tool execution result |
| `screen_frame` | Screen capture at a point in time |
| `dom_snapshot` | Browser DOM tree snapshot |
| `accessibility_snapshot` | Windows UI Automation accessibility tree |
| `user_action` | User intervention |
| `thought` | Agent internal reasoning |
| `error` | Captured exception with context |

Every step carries a content-addressed hash for change detection and replay integrity.

### Failure Classification

The autopsy classifier checks 8 failure modes and returns the highest-confidence match:

| Failure Type | Detection Method |
|---|---|
| `reasoning_failure` | Hash repetition detection, pattern similarity |
| `grounding_failure` | UI element interaction errors, screen diff, snapshot layout shift |
| `tool_failure` | Repeated error hash chains, timeout detection |
| `memory_failure` | Context-length exceeded, long conversation heuristics |
| `environment_drift` | Auth errors, rate limits, network failures, resource exhaustion |
| `unknown` | Fallback with trace summary |

### Causal Graph

Edges encode semantic relationships between steps:

- `tool_informs_llm` — tool results influence subsequent LLM reasoning
- `llm_calls_tool` — LLM decisions trigger tool invocations
- `causes_error` / `error_propagation` — failure chains
- `context_chain` — sequential LLM context windows
- `llm_uses_screen` — screen frame used for visual grounding
- `llm_uses_snapshot` — DOM/accessibility snapshot used for grounding
- `tool_triggers_snapshot` — tool call triggers a snapshot capture
- `temporal` — sequential ordering (baseline)

The graph supports critical-path analysis (trace failure chains backward), loop detection (DFS-based cycle finding), DOT export for GraphViz visualization, and influence mapping.

### Replay Engine

- Rewind to any step index with `--from` / `--to`
- Inject edited tool outputs to test hypothetical fixes
- Breakpoints with interactive inspect (`i`), continue, quit
- Pattern analysis across LLM calls, error types, tool usage, and snapshots
- Cross-trace diff to find divergences between runs

---

## Project Structure

```
src/tardis/
  __init__.py          # Package exports: Recorder, record, wrap, wrap_anthropic
  models.py            # Pydantic models: Trace, Step, StepType, FailureType
  config.py            # TOML-based configuration loader
  cli.py               # Click CLI with 8 commands

  capture/
    recorder.py        # Flight recorder: start/stop/log with thread-local context
    llm_proxy.py       # OpenAI client wrapper with token/cost tracking
    anthropic_proxy.py # Anthropic client wrapper with token/cost tracking
    tool_wrapper.py    # Decorator for instrumenting tool calls
    screen.py          # Screen capture (mss), pixel diff, layout shift detection
    dom_snapshot.py    # DOM & accessibility tree snapshots, tree diff for grounding

  store/
    sqlite_store.py    # Append-only SQLite with prefix ID matching

  replay/
    engine.py          # Deterministic replay with breakpoints, inspect, diff, analysis

  causal/
    graph.py           # Multi-relationship causal graph with critical path, loops, DOT

  autopsy/
    classifier.py      # 8-method failure classifier with confidence scoring & evidence

  utils/
    hashing.py         # Content-addressed SHA-256 hashing
    platform.py        # Cross-platform: Windows/macOS/Linux detection, screen, window, fs

examples/
  basic_agent.py               # Minimal OpenAI recording example
  anthropic_agent.py           # Anthropic client usage
  tool_tracing_example.py      # Tool call tracing with error handling
  replay_example.py            # Replay + causal graph demonstration
  advanced_analysis_example.py # Full analysis workflow (patterns, graph, autopsy)
  dom_snapshot_example.py      # DOM/accessibility snapshot capture and diff

tests/
  test_models.py               # Model validation, aggregation, error tracking
  test_causal_graph.py         # Graph construction, critical path, loops, DOT export
  test_autopsy.py              # Classifier accuracy, evidence, fix suggestions, reports
  test_dom_snapshot.py         # Snapshot capture, tree diff, layout shift detection
```

---

## Roadmap

- **v0.1** — OpenAI + Anthropic wrappers, SQLite store, deterministic replay, heuristic autopsy, screen diff, causal graph analysis
- **v0.2** — DOM/accessibility snapshots, tree diff for grounding analysis, cross-platform window management *(current)*
- **v0.3** — ML-assisted classification, distributed trace aggregation
- **v1.0** — eBPF integration, multi-agent orchestration, real-time monitoring dashboards

---

## License

MIT
