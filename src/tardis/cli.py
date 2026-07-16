import click
from rich import print as rprint
from .store.sqlite_store import Store
from .replay.engine import ReplayEngine
from .causal.graph import CausalGraph
from .autopsy.classifier import Autopsy

@click.group()
def main():
    pass

@main.command()
def health():
    from pathlib import Path
    store = Store()
    rprint("[green]TARDIS OK[/green]")
    rprint(f"DB: {store.db_path} exists={store.db_path.exists()}")

@main.command()
def init():
    """Initialize .tardis/ directory"""
    from pathlib import Path
    Path(".tardis").mkdir(exist_ok=True)
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
        status = "[green]✓[/green]" if success else "[red]✗[/red]"
        cost = t.get("total_cost_usd", 0.0)
        tokens = t.get("total_tokens", 0)
        rprint(f"{status} {t['id']}  steps={steps}  cost=${cost:.4f}  tokens={tokens}  created={t.get('created_at')}")

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
@click.option("--format", "fmt", default="json", type=click.Choice(["json", "negative-pair"]))
def export(trace_id, fmt):
    store = Store()
    trace = store.get_trace(trace_id)
    if not trace:
        return
    if fmt == "negative-pair":
        # generate contrastive pair
        import json, pathlib
        out = {
            "trace_id": trace.id,
            "failure": trace.steps[-1].model_dump() if trace.steps else {},
            "success_hint": "human fix needed",
            "steps": [s.model_dump() for s in trace.steps[-3:]]
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

if __name__ == "__main__":
    main()
