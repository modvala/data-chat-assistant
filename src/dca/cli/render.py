"""The CLI renderer (cli.md). It only draws the Answer that the core made (DS1).

Each component uses only named tokens (DS5). Meaning never depends on color alone (DS4).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich import box
from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.measure import Measurement
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table as RichTable
from rich.text import Text as RichText
from rich.theme import Theme

from dca.app.turn_api import SessionInfo
from dca.core.answer import (
    ActionItems,
    Answer,
    Bullets,
    Confirmation,
    Heading,
    Kpi,
    Notice,
    Provenance,
    Refusal,
    Result,
    SqlView,
    Table,
    Text,
    TraceView,
)

THEME = Theme(
    {
        "dca.text": "default",
        "dca.muted": "dim",
        "dca.strong": "bold",
        "dca.accent": "cyan",
        "dca.success": "green",
        "dca.warning": "yellow",
        "dca.danger": "bold red",
        "dca.refusal": "magenta",
        "dca.scope": "blue",
        "dca.title": "bold cyan",
        "dca.label": "bold",
        "dca.caption": "dim",
        "dca.delta.up": "green",
        "dca.delta.down": "red",
    }
)

SYMBOLS = {
    "agent": ("◆", "*"),
    "ok": ("✓", "[ok]"),
    "warn": ("!", "[!]"),
    "error": ("✗", "[x]"),
    "refusal": ("⊘", "[no]"),
    "danger": ("⚠", "[!!]"),
    "up": ("▲", "+"),
    "down": ("▼", "-"),
    "bullet": ("•", "-"),
    "sep": ("·", "|"),
    "bar": ("▌", "|"),
    "prompt": ("›", ">"),
    "dash": ("—", "-"),
    "more": ("…", "..."),
    "arrow": ("→", "->"),
}

NOTICE_STYLE = {"info": ("dca.accent", "agent"), "warning": ("dca.warning", "warn"), "error": ("dca.danger", "error")}

COMMANDS = [
    ("/help", "Show the commands."),
    ("/scope", "Show your Brand scope."),
    ("/sql [all]", "Show the SQL of the last Answer. With all: each attempt and its error."),
    ("/save [title]", "Save the last Answer as a Saved Report."),
    ("/list", "List your Saved Reports."),
    ("/undo", "Restore the reports of the last delete."),
    ("/trace [id]", "Show the steps of a Turn. With no ID: the last Turn."),
    ("/exit", "End the session."),
]

WIDTH_MAX = 100

# C3 Turn status. The text never contains SQL or data.
STATUS_TEXT = {
    "thinking": "Reading the question",
    "sql": "Writing SQL",
    "dry_run": "Checking the query",
    "query": "Running the query",
    "correction": "Fixing the query {sep} attempt {attempt} of {of}",
    "retry": "Service is busy, trying again in {seconds} s",
    "fallback": "Using the backup model",
    "writing": "Writing the answer",
}
WARNING_STATES = frozenset({"correction", "retry", "fallback"})


@dataclass(frozen=True)
class Mode:
    color: bool = True
    plain: bool = False
    ascii: bool = False
    animation: bool = True


def fmt_value(value: Any, column_type: str, dash: str) -> str:
    if value is None:
        return dash
    if column_type == "customer":
        return f"Customer {value}"
    if column_type == "money" and isinstance(value, int | float):
        return f"${value:,.0f}" if abs(value) >= 1000 else f"${value:,.2f}"
    if column_type == "int" and isinstance(value, int):
        return f"{value:,}"
    if column_type == "number" and isinstance(value, int | float):
        return f"{value:,.2f}"
    return str(value)


def fmt_bytes(value: int) -> str:
    for unit, size in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if value >= size:
            return f"{value / size:.1f} {unit}"
    return f"{value} B"


def scope_label(brands: list[str] | tuple[str, ...] | None, all_brands: bool, max_brands: int) -> str:
    if all_brands or brands is None:
        return "all brands"
    if len(brands) > max_brands:
        return f"{len(brands)} brands (/scope to list)"
    return ", ".join(brands)


class Renderer:
    def __init__(self, console: Console, mode: Mode, header_max_brands: int) -> None:
        self.console = console
        self.mode = mode
        self.header_max_brands = header_max_brands

    def out(self, renderable: RenderableType) -> None:
        """Plain mode writes the text as it is: no styles, and tabs stay tabs."""
        if self.mode.plain:
            text = renderable.plain if isinstance(renderable, RichText) else str(renderable)
            self.console.file.write(text + "\n")
            self.console.file.flush()
        else:
            self.console.print(renderable)

    def sym(self, name: str) -> str:
        unicode, ascii_ = SYMBOLS[name]
        return ascii_ if self.mode.ascii else unicode

    @property
    def _box(self) -> box.Box:
        return box.ASCII if self.mode.ascii else box.ROUNDED

    # C1
    def header(self, info: SessionInfo) -> None:
        sep = self.sym("sep")
        scope = scope_label(info.brands, info.role == "ceo", self.header_max_brands)
        line = RichText.assemble(
            "  ",
            (f"Executive {info.executive_id}", "dca.text"),
            f" {sep} ",
            ("CEO" if info.role == "ceo" else "Manager", "dca.text"),
            f" {sep} ",
            (f"Brand scope: {scope}", "dca.scope"),
        )
        self.out(RichText(f"{self.sym('agent')} Data Chat Assistant", style="dca.title"))
        self.out(line)
        self.out(RichText("  Type a question, or /help for commands.", style="dca.muted"))

    def unknown_executive(self, valid_ids: list[str]) -> None:
        self.notice(
            Notice(level="error", title="Unknown Executive ID", body="Valid IDs: " + ", ".join(valid_ids) + ".")
        )

    # C3
    def status_text(self, event: str, data: dict[str, Any]) -> str | None:
        template = STATUS_TEXT.get(event)
        return template.format(sep=self.sym("sep"), **data) if template else None

    def start_status(self) -> "TurnStatus":
        return TurnStatus(self)

    # C2
    def prompt(self, pending: bool) -> str:
        return f"{'confirm' if pending else 'you'} {self.sym('prompt')} "

    # C4
    def separator(self, number: int) -> None:
        if not self.mode.plain:
            self.out(Rule(f"{number}", align="right", style="dca.muted", characters="-" if self.mode.ascii else "─"))

    # C17
    def help(self) -> None:
        if self.mode.plain:
            for command, description in COMMANDS:
                self.out(f"{command}\t{description}")
            return
        table = RichTable(box=None, show_header=False, padding=(0, 2, 0, 0))
        for command, description in COMMANDS:
            table.add_row(RichText(command, style="dca.accent"), RichText(description, style="dca.text"))
        self.out(table)

    # C5
    def answer(self, answer: Answer) -> None:
        for block in answer.blocks:
            if isinstance(block, SqlView):
                self.sql_view(block)
            elif isinstance(block, TraceView):
                self.trace_view(block)
        if any(isinstance(block, SqlView | TraceView) for block in answer.blocks):
            return
        for block in answer.blocks:
            if isinstance(block, Confirmation):
                self.confirmation(block)
            elif isinstance(block, Result):
                self.result(block)
        # A notice before the content (for example "Nothing was deleted.") prints first.
        leading = []
        for block in answer.blocks:
            if not isinstance(block, Notice):
                break
            leading.append(block)
        for block in leading:
            self.notice(block, answer.provenance.trace_id)
        rest = answer.blocks[len(leading) :]
        notices = [block for block in rest if isinstance(block, Notice | Refusal)]
        content = [block for block in rest if not isinstance(block, Notice | Refusal | Confirmation | Result)]
        if content:
            self._content(content, answer.provenance)
        for block in notices:
            if isinstance(block, Refusal):
                self.refusal(block, answer.provenance.trace_id)
            else:
                self.notice(block, answer.provenance.trace_id)
        scoped = answer.provenance.brand_scope or answer.provenance.all_brands
        if content and answer.kind == "answer" and answer.provenance.trace_id and scoped:
            self.provenance(answer.provenance, report=answer.report)

    def _content(self, blocks: list, provenance: Provenance) -> None:
        heading = next((block.text for block in blocks if isinstance(block, Heading)), None)
        body = [block for block in blocks if not (isinstance(block, Heading) and block.text == heading)]
        renderables = [self._block(block) for block in body]
        short = heading is None and all(isinstance(block, Text | Bullets) for block in body)
        if self.mode.plain:
            if heading:
                self.out(heading)
            for renderable in renderables:
                self.out(renderable)
                self.out("")
            return
        if short:
            for renderable in renderables:
                self.out(renderable)
            return
        spaced: list[RenderableType] = []
        for renderable in renderables:
            if spaced:
                spaced.append(RichText(""))
            spaced.append(renderable)
        title = f"{self.sym('agent')} {heading}" if heading else self.sym("agent")
        # width.max is for text. A wider table makes the panel wider, up to the terminal width (C6).
        tables = [r for block, r in zip(body, renderables, strict=True) if isinstance(block, Table)]
        needed = max((Measurement.get(self.console, self.console.options, t).maximum + 4 for t in tables), default=0)
        self.out(
            Panel(
                Group(*spaced),
                title=RichText(title, style="dca.title"),
                title_align="left",
                box=self._box,
                padding=(0, 1),
                width=min(self.console.width, max(WIDTH_MAX, needed)),
            )
        )

    def _block(self, block: Any) -> RenderableType:
        if isinstance(block, Text):
            # Markdown draws Unicode bullets and rules, so plain and ASCII modes show the text as it is.
            return RichText(block.markdown) if self.mode.plain or self.mode.ascii else Markdown(block.markdown)
        if isinstance(block, Heading):
            return RichText(block.text, style="dca.strong")
        if isinstance(block, Bullets):
            bullet = self.sym("bullet")
            return RichText("\n".join(f"{bullet} {item}" for item in block.items))
        if isinstance(block, ActionItems):
            lines = RichText()
            for number, item in enumerate(block.items, start=1):
                if lines:
                    lines.append("\n")
                lines.append(f"{number}. {item.action}")
                lines.append(f"\n   Watch: {item.metric}", style="dca.caption")
            return lines
        if isinstance(block, Kpi):
            return self._kpi(block)
        if isinstance(block, Table):
            return self._table(block)
        return RichText(str(block))

    # C7
    def _kpi(self, block: Kpi) -> RenderableType:
        value, unit = block.value, block.unit or ""
        if unit.upper() in ("USD", "$"):
            value, unit = "$" + value.removeprefix("$"), ""  # cli.md fmt.money: "$19,554.14"
        elif unit and not unit.startswith("%"):
            unit = " " + unit  # "532 orders", but "12%"
        line = RichText.assemble((block.label + " ", "dca.label"), (value + unit, "dca.strong"))
        if block.delta:
            down = block.delta.strip().startswith("-")
            good = not down if block.good_direction == "up" else down
            symbol = self.sym("down" if down else "up")
            line.append(f" {symbol} {block.delta}", style="dca.delta.up" if good else "dca.delta.down")
        if block.period:
            line.append(f"\n{block.period}", style="dca.caption")
        return line

    # C6
    def _table(self, block: Table) -> RenderableType:
        dash = self.sym("dash")
        rows = [[fmt_value(value, column.type, dash) for value, column in zip(row, block.columns, strict=False)] for row in block.rows]
        hint = None
        if block.truncated:
            hint = f"Showing {len(block.rows)} of {block.total_rows} rows. Ask to filter or group them."
        if self.mode.plain:
            lines = ["\t".join(column.name for column in block.columns), *("\t".join(row) for row in rows)]
            if hint:
                lines.append(hint)
            return RichText("\n".join(lines))
        table = RichTable(box=box.ASCII if self.mode.ascii else box.SIMPLE_HEAD, header_style="dca.label")
        for column in block.columns:
            numeric = column.type in ("money", "int", "number")
            # "fold" wraps a long value onto the next line. It never cuts a value with "…".
            table.add_column(column.name, justify="right" if numeric else "left", overflow="fold")
        for row in rows:
            table.add_row(*row)
        if hint:
            return Group(table, RichText(hint, style="dca.warning"))
        return table

    # C10
    def provenance(self, provenance: Provenance, *, report: bool = False) -> None:
        sep = f" {self.sym('sep')} "
        parts = [RichText("Scope: " + scope_label(provenance.brand_scope, provenance.all_brands, self.header_max_brands))]
        if provenance.corrections:
            word = "correction" if provenance.corrections == 1 else "corrections"
            parts.append(RichText(f"{provenance.corrections} {word}", style="dca.warning"))
        if provenance.fallback_used:
            parts.append(RichText("backup model", style="dca.warning"))
        parts.append(RichText(f"trace {provenance.trace_id[:8]}"))
        if provenance.sql:
            parts.append(RichText("/sql", style="dca.accent"))
        if report:
            parts.append(RichText("/save", style="dca.accent"))
        line = RichText("  ", style="dca.caption")
        for index, part in enumerate(parts):
            if index:
                line.append(sep)
            line.append_text(part)
        self.out(line)
        for assumption in provenance.assumptions:
            self.out(RichText(f"  Assumed: {assumption}", style="dca.caption"))

    # C14
    def sql_view(self, block: SqlView) -> None:
        parts = [fmt_bytes(block.bytes_scanned)] if block.bytes_scanned else []
        if block.row_count is not None:
            parts.append(f"{block.row_count:,} {'row' if block.row_count == 1 else 'rows'}")
        if block.error:
            parts.append(f"{self.sym('error')} {block.error}")
        elif not parts:
            parts.append(f"{self.sym('ok')} ran")
        caption = f" {self.sym('sep')} ".join(parts)
        if self.mode.plain:
            self.out(block.sql)
            self.out(caption)
            return
        syntax = Syntax(block.sql, "sql", theme="ansi_dark", line_numbers=True, word_wrap=True)
        self.out(Panel(syntax, box=self._box, padding=(0, 1), width=min(self.console.width, WIDTH_MAX)))
        self.out(RichText(f"  {caption}", style="dca.caption"))

    # C12
    def confirmation(self, block: Confirmation) -> None:
        noun = "Saved Report" if block.count == 1 else "Saved Reports"
        title = f"{self.sym('danger')} Delete {block.count} {noun}?"
        lines = [block.description, ""]
        bullet = self.sym("bullet")
        width = max((len(item.title) for item in block.items), default=0)
        lines += [f" {bullet} {item.title:<{width}}    {item.date}" for item in block.items]
        if block.count > len(block.items):
            lines.append(f" {bullet} {self.sym('more')} and {block.count - len(block.items)} more (/list to see all)")
        minutes = max(1, round((block.expires_at - datetime.now(block.expires_at.tzinfo)).total_seconds() / 60))
        footer = [
            "",
            f"To delete, type:  {block.reply_text}",
            f"Any other message cancels. This request expires in {minutes} minutes.",
            f"You can undo for {block.undo_window_h} hours.",
        ]
        if self.mode.plain:
            for line in [title, *lines, *footer]:
                self.out(line)
            return
        body = RichText("\n".join(lines))
        body.append("\n\nTo delete, type:  ")
        body.append(block.reply_text, style="dca.strong")
        body.append("\n" + "\n".join(footer[2:]))
        self.out(
            Panel(
                body,
                title=RichText(title, style="dca.danger"),
                title_align="left",
                box=box.ASCII if self.mode.ascii else box.HEAVY,
                border_style="dca.danger",
                padding=(0, 1),
                width=min(self.console.width, WIDTH_MAX),
            )
        )

    # C13
    def result(self, block: Result) -> None:
        noun = "Saved Report" if block.count == 1 else "Saved Reports"
        text = f"Deleted {block.count} {noun}." if block.action == "deleted" else f"Restored {block.count} {noun}."
        if block.undo_until is not None:
            local = block.undo_until.astimezone().strftime("%Y-%m-%d %H:%M")
            text += f" Type /undo before {local} to restore them."
        line = RichText(f"{self.sym('ok')} ", style="dca.success")
        line.append(text, style="dca.text")
        self.out(line)

    # C15
    def trace_view(self, view: TraceView) -> None:
        sep = self.sym("sep")
        status = {"ok": "ok", "error": "error", "refusal": "refusal", "info": "agent"}
        styles = {"ok": "dca.success", "error": "dca.danger", "refusal": "dca.refusal", "info": "dca.muted"}
        started = view.started.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        self.out(RichText(f"trace {view.trace_id[:8]} {sep} {started} {sep} {view.duration_ms / 1000:.1f} s {sep} {view.outcome}"))
        width = max((len(row.label) for row in view.rows), default=0)
        for index, row in enumerate(view.rows):
            branch = ("`-" if self.mode.ascii else "└─") if index == len(view.rows) - 1 else ("|-" if self.mode.ascii else "├─")
            duration = f"{row.duration_ms:,.0f} ms" if row.duration_ms < 1000 else f"{row.duration_ms / 1000:.1f} s"
            line = RichText(f"{branch} {row.label:<{width}}  ")
            line.append(f"{self.sym(status[row.status])} ", style=styles[row.status])
            detail = row.detail.replace("→", self.sym("arrow"))
            line.append(f"{detail:<38} {duration:>8}")
            self.out(line)

    # C11
    def notice(self, notice: Notice, trace_id: str = "") -> None:
        style, symbol = NOTICE_STYLE[notice.level]
        lines = [f"{self.sym(symbol)} {notice.title}"]
        if notice.body:
            lines.append(notice.body)
        if notice.trace_id or trace_id:
            lines.append(f"trace {(notice.trace_id or trace_id)[:8]}")
        self._bar(lines, style)

    def refusal(self, refusal: Refusal, trace_id: str) -> None:
        lines = [f"{self.sym('refusal')} {refusal.title}", refusal.body]
        if refusal.suggestion:
            lines.append(refusal.suggestion)
        if trace_id:
            lines.append(f"trace {trace_id[:8]}")
        self._bar(lines, "dca.refusal")

    def _bar(self, lines: list[str], style: str) -> None:
        bar = self.sym("bar")
        for index, line in enumerate(lines):
            text = RichText(f"{bar} ", style=style)
            text.append(line, style="dca.strong" if index == 0 else "dca.text")
            self.out(text)


class TurnStatus:
    """C3: one animated status line on a TTY, else one static line for each new state (motion.none)."""

    def __init__(self, renderer: Renderer) -> None:
        self.renderer = renderer
        self.last: str | None = None
        self.live = None
        if renderer.mode.animation and not renderer.mode.plain:
            self.live = renderer.console.status("", spinner="dots", refresh_per_second=8)
            self.live.start()

    def update(self, event: str, data: dict[str, Any]) -> None:
        text = self.renderer.status_text(event, data)
        if text is None or text == self.last:
            return
        self.last = text
        style = "dca.warning" if event in WARNING_STATES else "dca.muted"
        if self.live is not None:
            self.live.update(RichText(text, style=style))
        else:
            self.renderer.out(RichText(f"{self.renderer.sym('sep')} {text}", style="dca.caption"))

    def stop(self) -> None:
        if self.live is not None:
            self.live.stop()
