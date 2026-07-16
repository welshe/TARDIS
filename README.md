# TARDIS - Time-Travel Debugger for AI Agents

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

**The flight recorder that lets you rewind agent failures.**

![TARDIS Architecture](assets/arch.png)

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

### Why labs need this

Current observability tools log text. TARDIS logs causality:
- Every LLM prompt/completion + logprobs + tool schema at that moment
- Every tool call input/output + exit code + hang detection
- Every screen frame diff + active window rect + DOM/accessibility snapshot
- Content-addressed hashes so replay is byte-for-byte deterministic

### How it works

**Capture** -> **Store** -> **Replay** -> **Autopsy**

1. **Capture:** Proxy wrapper around OpenAI/Anthropic + Win32 hooks + mss rolling buffer. No code change, just `tardis.wrap(client)`
2. **Store:** Append-only SQLite + file store in `.tardis/`. Each step hashed. Traces are immutable.
3. **Replay:** Deterministic engine. Rewind to any step, edit tool output, replay forward.
4. **Autopsy:** Classifies failure into: reasoning_failure, grounding_failure, tool_failure, memory_failure, environment_drift. Generates regression test + negative trace pair.

### Install

```bash
git clone https://github.com/welshe/TARDIS
cd TARDIS
pip install -e ".[dev]"
```

### Quickstart

```python
import tardis
from openai import OpenAI

client = tardis.wrap(OpenAI())  # that's it, now every call is recorded

# your agent loop stays identical
response = client.chat.completions.create(
  model="gpt-4o",
  messages=[{"role": "user", "content": "fix the EBUSY error"}],
  tools=[...]
)

# later
# tardis list
# tardis replay <id> --from 5 --edit-tool-output '{"success": true}'
```

### CLI

```
tardis init              # create .tardis/ in current dir
tardis list              # list traces
tardis show <id>         # show causal graph
tardis replay <id> --from 10 --to 20
tardis replay <id> --from 10 --edit-tool-output '{"code": 0}'
tardis autopsy <id>      # root cause + fix suggestion
tardis export <id> --format negative-pair  # for RL fine-tuning
```

### Project Structure

```
src/tardis/
  models.py         # Pydantic: Trace, Step, StepType
  config.py         # TOML loader
  store/            # SQLite append-only log + file blobs
  capture/          # LLM proxy, tool wrapper, screen diff
  replay/           # Deterministic replay engine
  causal/           # Builds DAG of what caused what
  autopsy/          # Failure classifier
```

### Roadmap v0.1 -> v1.0

- v0.1: OpenAI wrapper + SQLite store + replay + heuristic autopsy (THIS RELEASE)
- v0.2: Anthropic wrapper + screen diff + DOM snapshot
- v0.3: Win32 true click grounding (your TraceForge superpower)
- v1.0: eBPF + distributed trace merge for multi-agent

MIT License.
