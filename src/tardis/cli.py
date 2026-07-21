import click
from rich import print as rprint
from rich.table import Table

from .autopsy.classifier import Autopsy
from .causal.graph import CausalGraph
from .replay.engine import ReplayEngine
from .store.sqlite_store import Store


@click.group()
def main():
    pass


@main.command()
def health():
    from .store.lancedb_store import FailurePatternStore

    store = Store()
    rprint("[green]TARDIS OK[/green]")
    rprint(f"DB: {store.db_path} exists={store.db_path.exists()}")

    fp = FailurePatternStore()
    status = (
        "[green]available[/green]"
        if fp.available
        else "[yellow]not installed (pip install lancedb pyarrow)[/yellow]"
    )
    rprint(f"LanceDB: {status} — {fp.count()} indexed patterns")


@main.command()
def init():
    """Initialize .tardis/ directory"""
    import sys
    from pathlib import Path

    p = Path(".tardis")
    p.mkdir(exist_ok=True)
    # Set restrictive permissions on Unix (owner-only read/write/execute)
    if sys.platform != "win32":
        try:
            import os

            os.chmod(p, 0o700)
        except OSError:
            pass
    print("Initialized .tardis/")


@main.command()
def list():
    store = Store()
    traces = store.list_traces()
    if not traces:
        rprint("[yellow]No traces found. Run your agent with tardis.wrap()[/yellow]")
        return
    rprint(f"[bold]Total traces: {len(traces)}[/bold]")
    for t in traces:
        steps = len(t.get("steps", []))
        success = t.get("success", True)
        status = "[green]OK[/green]" if success else "[red]FAIL[/red]"
        cost = t.get("total_cost_usd", 0.0)
        tokens = t.get("total_tokens", 0)
        rprint(
            f"{status} {t['id']}  steps={steps}  cost=${cost:.4f}  tokens={tokens}  created={t.get('created_at')}"
        )


@main.command()
@click.argument("trace_id")
@click.option("--export-dot", default=None, help="Export causal graph as DOT file")
def show(trace_id, export_dot):
    store = Store()
    trace = store.get_trace(trace_id)
    if not trace:
        rprint(f"[red]Trace {trace_id} not found[/red]")
        return
    g = CausalGraph(trace)
    g.render()
    if export_dot:
        g.export_dot(export_dot)


@main.command()
@click.argument("trace_id")
@click.option("--from", "from_idx", default=0, help="Start step")
@click.option("--to", "to_idx", default=None, type=int, help="End step")
@click.option("--edit-tool-output", default=None, help="JSON string to inject")
def replay(trace_id, from_idx, to_idx, edit_tool_output):
    import json

    edit = json.loads(edit_tool_output) if edit_tool_output else None
    engine = ReplayEngine(trace_id)
    engine.replay(from_idx=from_idx, to_idx=to_idx, edit_tool_output=edit)


@main.command()
@click.argument("trace_id")
def autopsy(trace_id):
    store = Store()
    trace = store.get_trace(trace_id)
    if not trace:
        rprint(f"[red]Trace {trace_id} not found[/red]")
        return
    Autopsy(trace).report()


@main.command()
@click.argument("trace_id")
@click.option(
    "--format", "fmt", default="json", type=click.Choice(["json", "negative-pair"])
)
def export(trace_id, fmt):
    store = Store()
    trace = store.get_trace(trace_id)
    if not trace:
        return
    if fmt == "negative-pair":
        # generate contrastive pair
        import json
        import pathlib

        out = {
            "trace_id": trace.id,
            "failure": trace.steps[-1].model_dump() if trace.steps else {},
            "success_hint": "human fix needed",
            "steps": [s.model_dump() for s in trace.steps[-3:]],
        }
        pathlib.Path(f"{trace.id}.negative.json").write_text(json.dumps(out, indent=2))
        rprint(f"[green]Wrote {trace.id}.negative.json for RL[/green]")
    else:
        rprint(trace.model_dump_json(indent=2))


@main.command()
@click.argument("trace_id")
def analyze(trace_id):
    """Run pattern analysis on a trace"""
    engine = ReplayEngine(trace_id)
    engine.analyze_patterns()


@main.command()
@click.option("--duration", default=10, help="Seconds to capture input events")
def hook(duration):
    """Start Win32 keyboard/mouse hooks and display captured events"""
    import sys

    if sys.platform != "win32":
        rprint("[red]Win32 hooks are only available on Windows[/red]")
        return
    from .capture.win32_hooks import Win32HookManager

    rprint(f"[bold green]Win32 hooks active for {duration}s[/bold green]")
    rprint("[dim]Press Ctrl+C to stop early[/dim]")

    mgr = Win32HookManager()
    mgr.start()

    try:
        import time

        time.sleep(duration)
    except KeyboardInterrupt:
        pass
    finally:
        mgr.stop()

    events = mgr.get_events()
    kb = [e for e in events if "vk_code" in e]
    ms = [e for e in events if "x" in e and "y" in e]

    rprint(
        f"\n[bold]Captured {len(events)} events: {len(kb)} keyboard, {len(ms)} mouse[/bold]\n"
    )

    if kb:
        table = Table(title="Keyboard Events")
        table.add_column("Type", style="cyan")
        table.add_column("Key", style="yellow")
        table.add_column("Char", style="green")
        table.add_column("VK", style="dim")
        for e in kb[-20:]:
            table.add_row(
                e.get("type", "?"),
                e.get("vk_name", "?"),
                str(e.get("character") or ""),
                str(e.get("vk_code")),
            )
        rprint(table)

    if ms:
        table = Table(title="Mouse Events")
        table.add_column("Type", style="cyan")
        table.add_column("X", style="yellow")
        table.add_column("Y", style="yellow")
        table.add_column("Delta", style="dim")
        for e in ms[-20:]:
            table.add_row(
                e.get("type", "?"),
                str(e.get("x")),
                str(e.get("y")),
                str(e.get("wheel_delta", "")),
            )
        rprint(table)


@main.group()
def orch():
    """Multi-agent orchestration commands"""
    pass


@orch.command()
def status():
    """Show orchestration status for the current session"""
    rprint(
        "[yellow]No active orchestration session. Use tardis orch run to start one.[/yellow]"
    )


@orch.command()
@click.option("--agents", default=2, help="Number of agents to simulate")
@click.option("--tasks", default=5, help="Number of tasks to simulate")
def demo(agents, tasks):
    """Run a demo orchestration session with simulated agents"""
    import random
    import time

    from .orchestration import Agent, AgentCapability, Orchestrator, Task

    orch = Orchestrator(max_workers=min(agents, 4))

    capabilities_pool = [
        {AgentCapability.browser, AgentCapability.vision},
        {AgentCapability.terminal, AgentCapability.code_execution},
        {AgentCapability.file_system, AgentCapability.web_search},
        {AgentCapability.screen_control, AgentCapability.reasoning},
    ]

    for i in range(agents):
        caps = capabilities_pool[i % len(capabilities_pool)]
        orch.register(Agent(f"agent-{i + 1}", capabilities=caps, model="gpt-4o"))

    tasks_list = []
    task_descriptions = [
        "browse the login page",
        "run the test suite",
        "search for error documentation",
        "fix the configuration file",
        "screenshot the dashboard",
        "analyze code quality",
        "deploy to staging",
        "check logs for errors",
    ]
    for i in range(tasks):
        desc = task_descriptions[i % len(task_descriptions)]
        # Map task description to appropriate capability requirement
        if "browse" in desc or "screenshot" in desc:
            caps = {"browser"}
        elif "run" in desc or "deploy" in desc or "check" in desc:
            caps = {"terminal"}
        elif "search" in desc or "documentation" in desc:
            caps = {"web_search"}
        elif "fix" in desc or "quality" in desc:
            caps = {"file_system", "code_execution"}
        else:
            caps = {"browser"}
        t = Task(desc, required_capabilities=caps, payload={"index": i})
        tasks_list.append(t)
        orch.submit(t)

    rprint(
        f"[bold]Running orchestration with {agents} agents and {len(tasks_list)} tasks[/bold]\n"
    )

    def agent_fn(task):
        time.sleep(random.uniform(0.3, 1.5))
        return {"status": "ok", "task": task.description, "agent": "simulated"}

    fn_map = {a.name: agent_fn for a in orch.agents.values()}
    results = orch.run_parallel(fn_map)

    table = Table(title=f"Orchestration Results ({len(results)} tasks)")
    table.add_column("Task", style="cyan")
    table.add_column("Status", style="yellow")
    table.add_column("Agent", style="green")
    table.add_column("Duration", style="dim")

    for t in results:
        status_style = (
            "[green]OK[/green]" if t.status == "completed" else "[red]FAIL[/red]"
        )
        dur = f"{t.duration_seconds:.2f}s" if t.duration_seconds else "-"
        table.add_row(t.description, status_style, t.assigned_agent or "-", dur)

    rprint(table)
    rprint(
        f"\n[dim]Memory keys: {len(orch.memory)} | Shared memory version: {orch.memory.version}[/dim]"
    )


@main.command()
@click.argument("trace_id")
@click.option("--limit", default=5, help="Number of similar failures to show")
def similar(trace_id, limit):
    """Find traces similar to a given failure in the LanceDB vector store"""
    from .store.lancedb_store import FailurePatternStore

    store = Store()
    trace = store.get_trace(trace_id)
    if not trace:
        rprint(f"[red]Trace {trace_id} not found[/red]")
        return

    fp_store = FailurePatternStore()

    if not fp_store.available:
        rprint(
            "[yellow]LanceDB is not installed. Install with: pip install lancedb pyarrow[/yellow]"
        )
        rprint(
            "[dim]LanceDB enables vector similarity search for failure patterns.[/dim]"
        )
        return

    count = fp_store.count()
    rprint(f"[dim]LanceDB store has {count} indexed failure patterns[/dim]\n")

    similar = fp_store.search_similar(trace, limit=limit)

    if not similar:
        fp_store.index_trace(trace)
        rprint(
            "[yellow]No similar failures found. This trace has been indexed.[/yellow]"
        )
        return

    table = Table(title=f"Similar Failures to {trace_id}")
    table.add_column("#", style="dim")
    table.add_column("Trace ID", style="cyan")
    table.add_column("Failure Type", style="red")
    table.add_column("Description", style="white")
    table.add_column("Similarity", style="green")

    for i, s in enumerate(similar, 1):
        if not isinstance(s, dict):
            continue
        dist = s.get("_distance", 1.0)
        try:
            dist = float(dist)
        except (TypeError, ValueError):
            dist = 1.0
        # Clamp distance to [0, 1] so similarity stays within [0, 100]%.
        dist = min(1.0, max(0.0, dist))
        sim_pct = int((1.0 - dist) * 100)
        table.add_row(
            str(i),
            s.get("trace_id", "unknown"),
            s.get("failure_type", "unknown"),
            s.get("description", "")[:100],
            f"{sim_pct}%",
        )

    rprint(table)

    # Also index this trace
    fp_store.index_trace(trace)
    rprint("\n[dim]Current trace indexed for future searches.[/dim]")


@main.command()
def vector_stats():
    """Show LanceDB vector store statistics"""
    from .store.lancedb_store import FailurePatternStore

    store = FailurePatternStore()

    if not store.available:
        rprint(
            "[yellow]LanceDB is not installed. Install with: pip install lancedb pyarrow[/yellow]"
        )
        return

    count = store.count()
    rprint("[bold]LanceDB Failure Pattern Store[/bold]")
    rprint(f"  Path: {store.db_path}")
    rprint(f"  Indexed patterns: {count}")
    rprint(f"  Vector dimension: {store.vector_dim}")

    if count == 0:
        rprint(
            "\n[dim]No traces indexed yet. Run 'tardis autopsy <trace_id>' on a failed trace to start indexing.[/dim]"
        )


@main.command()
@click.argument("trace_id")
@click.option("--overwrite", is_flag=True, help="Overwrite existing test file")
def gen_test(trace_id, overwrite):
    """Generate a regression test from a trace."""
    from .regression import RegressionTestGenerator

    gen = RegressionTestGenerator(overwrite=overwrite)
    try:
        case = gen.generate_from_trace(trace_id)
        rprint(f"[green]Generated regression test:[/green] {case.test_file}")
        rprint(f"[dim]Test class: {case.name}[/dim]")
        rprint(f"[dim]Digest: {case.digest}[/dim]")
    except ValueError as e:
        rprint(f"[red]{e}[/red]")


@main.command()
@click.option("--limit", default=50, help="Max traces to process")
def gen_all_tests(limit):
    """Generate regression tests for all failed traces."""
    from .regression import RegressionTestGenerator

    gen = RegressionTestGenerator(overwrite=True)
    cases = gen.generate_from_all_failed_traces(limit=limit)
    rprint(f"[green]Generated {len(cases)} regression tests[/green]")
    rprint(f"[dim]Location: {gen.suite.output_dir}[/dim]")


@main.command()
@click.argument("trace_id")
@click.option("--target", default=None, help="Target trace ID to diff against")
def trace_diff(trace_id, target):
    """Compare two traces side-by-side."""
    from .diff import TraceDiffer, TraceDiffViewer

    differ = TraceDiffer()
    if not target:
        store = Store()
        traces = store.list_traces()
        candidates = [t for t in traces if t["id"] != trace_id]
        if not candidates:
            rprint("[red]No other traces to diff against[/red]")
            return
        target = candidates[0]["id"]
    try:
        report = differ.diff(trace_id, target)
        viewer = TraceDiffViewer()
        viewer.render(report)
    except ValueError as e:
        rprint(f"[red]{e}[/red]")


@main.command()
@click.argument("query")
@click.option("--limit", default=10, help="Max results")
@click.option("--type", "failure_type", default=None, help="Filter by failure type")
@click.option("--load", is_flag=True, help="Load full traces")
def search(query, limit, failure_type, load):
    """Search traces using natural language."""
    from .search import PromptTraceSearcher

    searcher = PromptTraceSearcher()
    results = searcher.search(query, limit=limit, failure_type=failure_type, load_traces=load)
    if not results:
        rprint("[yellow]No matching traces found[/yellow]")
        return
    table = Table(title=f"Trace Search: '{query}'")
    table.add_column("Score", style="green")
    table.add_column("Trace ID", style="cyan")
    table.add_column("Failure Type", style="red")
    table.add_column("Match", style="yellow")
    table.add_column("Description", style="white")
    for r in results:
        terms = ", ".join(r.matched_terms[:3]) if r.matched_terms else r.match_field
        table.add_row(f"{r.confidence_pct}%", r.trace_id[:16],
                      r.failure_type, terms, r.description[:80])
    rprint(table)


@main.command()
@click.argument("trace_id")
@click.option("--port", default=9876, help="Stream server port")
@click.option("--duration", default=30, help="Stream duration in seconds")
def stream(trace_id, port, duration):
    """Stream a trace live for collaborative debugging."""
    import time

    from .streaming import TraceStreamer

    streamer = TraceStreamer(port=port)
    streamer.create_session(trace_id)
    streamer.start()
    rprint(f"[green]Streaming trace {trace_id} on port {port}[/green]")
    rprint("[dim]Press Ctrl+C to stop[/dim]")
    try:
        time.sleep(duration)
    except KeyboardInterrupt:
        pass
    finally:
        streamer.stop()
        rprint("[yellow]Stream ended[/yellow]")


if __name__ == "__main__":
    main()
