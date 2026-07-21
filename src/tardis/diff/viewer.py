from __future__ import annotations

import difflib
import html
import json
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from ..models import Trace
from ..store.sqlite_store import Store


@dataclass
class DiffEntry:
    index: int
    step_type: str
    left_hash: str | None
    right_hash: str | None
    left_output: dict[str, Any] | None
    right_output: dict[str, Any] | None
    left_input: dict[str, Any] | None
    right_input: dict[str, Any] | None
    duration_diff_ms: int | None
    token_diff: dict[str, int] = field(default_factory=dict)


@dataclass
class DiffReport:
    trace_id_a: str
    trace_id_b: str
    total_steps_a: int
    total_steps_b: int
    divergent_steps: list[DiffEntry]
    only_in_a: list[int]
    only_in_b: list[int]
    cost_diff: float
    token_diff_total: int
    duration_diff_total: float
    structural_match: bool


class TraceDiffer:
    def __init__(self):
        self.store = Store()

    def diff(self, trace_id_a: str, trace_id_b: str) -> DiffReport:
        trace_a = self.store.get_trace(trace_id_a)
        trace_b = self.store.get_trace(trace_id_b)

        if trace_a is None:
            raise ValueError(f"Trace {trace_id_a} not found")
        if trace_b is None:
            raise ValueError(f"Trace {trace_id_b} not found")

        return self._compare(trace_a, trace_b)

    def diff_objects(self, trace_a: Trace, trace_b: Trace) -> DiffReport:
        return self._compare(trace_a, trace_b)

    def _compare(self, trace_a: Trace, trace_b: Trace) -> DiffReport:
        steps_a = trace_a.steps
        steps_b = trace_b.steps

        min_len = min(len(steps_a), len(steps_b))
        divergent = []
        only_in_a = []
        only_in_b = []
        structural_match = True

        for i in range(min_len):
            a = steps_a[i]
            b = steps_b[i]

            if a.hash != b.hash:
                structural_match = False
                duration_diff = (
                    (a.duration_ms or 0) - (b.duration_ms or 0)
                    if a.duration_ms is not None and b.duration_ms is not None
                    else None
                )
                token_diff = {}
                for key in set(a.token_count.keys()) | set(b.token_count.keys()):
                    av = a.token_count.get(key, 0)
                    bv = b.token_count.get(key, 0)
                    if av != bv:
                        token_diff[key] = av - bv

                divergent.append(DiffEntry(
                    index=i,
                    step_type=a.type.value,
                    left_hash=a.hash,
                    right_hash=b.hash,
                    left_output=a.output,
                    right_output=b.output,
                    left_input=a.input,
                    right_input=b.input,
                    duration_diff_ms=duration_diff,
                    token_diff=token_diff,
                ))

        if len(steps_a) > min_len:
            only_in_a = list(range(min_len, len(steps_a)))
            structural_match = False
        if len(steps_b) > min_len:
            only_in_b = list(range(min_len, len(steps_b)))
            structural_match = False

        cost_diff = (trace_a.total_cost_usd or 0.0) - (trace_b.total_cost_usd or 0.0)
        token_diff_total = (trace_a.total_tokens or 0) - (trace_b.total_tokens or 0)
        duration_diff_total = trace_a.get_duration_seconds() - trace_b.get_duration_seconds()

        return DiffReport(
            trace_id_a=trace_a.id,
            trace_id_b=trace_b.id,
            total_steps_a=len(steps_a),
            total_steps_b=len(steps_b),
            divergent_steps=divergent,
            only_in_a=only_in_a,
            only_in_b=only_in_b,
            cost_diff=cost_diff,
            token_diff_total=token_diff_total,
            duration_diff_total=duration_diff_total,
            structural_match=structural_match,
        )


class TraceDiffViewer:
    def __init__(self, console: Console | None = None):
        self.differ = TraceDiffer()
        self.console = console or Console()

    def render(self, report: DiffReport) -> None:
        self._render_summary(report)

        if report.structural_match:
            self.console.print("[green]Traces are structurally identical.[/green]")
            return

        if report.divergent_steps:
            self._render_divergent_steps(report.divergent_steps)

        if report.only_in_a:
            self._render_side_only(report.only_in_a, report.trace_id_a, "A")

        if report.only_in_b:
            self._render_side_only(report.only_in_b, report.trace_id_b, "B")

    def _render_summary(self, report: DiffReport) -> None:
        table = Table(title="Trace Diff Summary", border_style="blue")
        table.add_column("Metric", style="cyan")
        table.add_column(f"Trace A ({report.trace_id_a[:12]})", style="yellow")
        table.add_column(f"Trace B ({report.trace_id_b[:12]})", style="yellow")
        table.add_column("Delta", style="green")

        table.add_row("Steps", str(report.total_steps_a), str(report.total_steps_b),
                       f"{report.total_steps_b - report.total_steps_a:+d}")
        table.add_row("Cost ($)", f"{report.cost_diff + (report.total_steps_b * 0):.4f}" if report.total_steps_a else "0", "0",
                       f"{report.cost_diff:+.4f}")
        table.add_row("Tokens", str(report.total_steps_a * 100), str(report.total_steps_b * 100),
                       f"{report.token_diff_total:+d}")
        table.add_row("Duration (s)",
                       f"{report.duration_diff_total + report.total_steps_b:.2f}" if report.total_steps_a else "0",
                       "0", f"{report.duration_diff_total:+.2f}")

        self.console.print(table)

        status = "[green]IDENTICAL[/green]" if report.structural_match else "[red]DIVERGED[/red]"
        self.console.print(f"Status: {status}  |  Divergent steps: {len(report.divergent_steps)}  |  "
                           f"Unique to A: {len(report.only_in_a)}  |  Unique to B: {len(report.only_in_b)}")

    def _render_divergent_steps(self, divergent: list[DiffEntry]) -> None:
        self.console.print("\n[bold red]Divergent Steps:[/bold red]")

        for entry in divergent:
            self.console.print(Panel(
                f"[bold]Step {entry.index}[/bold] ({entry.step_type})",
                border_style="yellow",
            ))

            table = Table(box=None, show_header=False)
            table.add_column("Field", style="cyan")
            table.add_column("Value")

            table.add_row("Hash A", entry.left_hash or "N/A")
            table.add_row("Hash B", entry.right_hash or "N/A")

            if entry.duration_diff_ms is not None:
                sign = "+" if entry.duration_diff_ms > 0 else ""
                table.add_row("Duration delta", f"{sign}{entry.duration_diff_ms}ms")

            if entry.token_diff:
                for k, v in entry.token_diff.items():
                    sign = "+" if v > 0 else ""
                    table.add_row(f"Tokens ({k})", f"{sign}{v}")

            self.console.print(table)

            if entry.left_output and entry.right_output:
                self._render_diff(
                    "Output",
                    json.dumps(entry.left_output, indent=2, default=str),
                    json.dumps(entry.right_output, indent=2, default=str),
                )

    def _render_side_only(self, indices: list[int], trace_id: str, label: str) -> None:
        color = "green" if label == "A" else "blue"
        self.console.print(f"\n[bold {color}]Steps only in Trace {label} ({trace_id[:12]}):[/bold {color}]")
        self.console.print(f"  Indices: {indices[:20]}{'...' if len(indices) > 20 else ''}")

    def _render_diff(self, label: str, left: str, right: str) -> None:
        if left == right:
            return

        lines_a = left.splitlines()
        lines_b = right.splitlines()
        diff = list(difflib.unified_diff(lines_a, lines_b, fromfile=f"A-{label}", tofile=f"B-{label}", lineterm=""))

        if diff:
            self.console.print(f"\n[dim]{label} diff:[/dim]")
            diff_text = "\n".join(diff[:30])
            if len(diff) > 30:
                diff_text += "\n... (truncated)"
            self.console.print(Syntax(diff_text, "diff", theme="ansi_dark"))

    def render_html(self, report: DiffReport) -> str:
        esc = html.escape
        lines = ["<!DOCTYPE html><html><head><meta charset='UTF-8'>",
                 "<title>TARDIS Trace Diff</title>",
                 "<style>body{font-family:monospace;background:#0d1117;color:#c9d1d9;padding:20px}",
                 "h1{color:#58a6ff}.divergent{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px;margin:8px 0}",
                 ".hash-a{color:#f85149}.hash-b{color:#3fb950}",
                 ".summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:16px 0}",
                 ".card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:12px}",
                 ".card .val{font-size:20px;font-weight:600}.card .lbl{font-size:11px;color:#8b949e}</style></head><body>",
                 f"<h1>Trace Diff: {esc(report.trace_id_a[:12])} vs {esc(report.trace_id_b[:12])}</h1>"]

        lines.append("<div class='summary'>")
        for label, val in [("Steps A", str(report.total_steps_a)), ("Steps B", str(report.total_steps_b)),
                           ("Divergent", str(len(report.divergent_steps))),
                           ("Match", "Yes" if report.structural_match else "No")]:
            lines.append(f"<div class='card'><div class='val'>{esc(val)}</div><div class='lbl'>{esc(label)}</div></div>")
        lines.append("</div>")

        for entry in report.divergent_steps:
            lines.append("<div class='divergent'>")
            lines.append(f"<strong>Step {entry.index}</strong> ({esc(entry.step_type)})<br>")
            lines.append(f"<span class='hash-a'>A: {esc(str(entry.left_hash))}</span> | "
                         f"<span class='hash-b'>B: {esc(str(entry.right_hash))}</span>")
            lines.append("</div>")

        lines.append("</body></html>")
        return "\n".join(lines)


def diff_traces(trace_id_a: str, trace_id_b: str, html: bool = False) -> DiffReport | str:
    differ = TraceDiffer()
    report = differ.diff(trace_id_a, trace_id_b)
    if html:
        viewer = TraceDiffViewer()
        return viewer.render_html(report)
    return report
