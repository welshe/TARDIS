import click
from rich import print as rprint
from .capture.recorder import init
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
def init_cmd():
    init()

main.add_command(init, name="init")

@main.command()
@click.argument("trace_id", required=False)
def list(trace_id):
    store = Store()
    traces = store.list_traces()
    if not traces:
        rprint("[yellow]No traces found. Run your agent with tardis.wrap()[/yellow]")
        return
    for t in traces:
        steps = len(t.get("steps", []))
        rprint(f"{t['id']}  steps={steps}  created={t.get('created_at')}")

@main.command()
@click.argument("trace_id")
def show(trace_id):
    store = Store()
    trace = store.get_trace(trace_id)
    if not trace:
        rprint(f"[red]Trace {trace_id} not found[/red]")
        return
    g = CausalGraph(trace)
    g.render()

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

if __name__ == "__main__":
    main()
