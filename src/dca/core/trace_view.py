"""The C15 trace view (cli.md, HLD 16.1): the span tree of one Turn, from the trace records.

Only these spans get a row. `context.assemble`, `tool.run_query` and `bq.dry_run` are parent or
detail spans with no row of their own.
"""

from datetime import datetime
from typing import Any

from dca.core.answer import TraceRow, TraceView


def _fmt_bytes(value: int) -> str:
    for unit, size in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if value >= size:
            return f"{value / size:.1f} {unit}"
    return f"{value} B"


def _retries(count: int) -> str:
    return f"{count} {'retry' if count == 1 else 'retries'}"


def _row(span: dict[str, Any]) -> TraceRow | None:
    name = span["name"]
    a = span.get("attributes", {})
    duration = float(span.get("duration_ms", 0))
    if name == "guard.input":
        blocked = a.get("decision") == "blocked"
        return TraceRow(label="input classifier", status="refusal" if blocked else "ok",
                        detail=f"{a.get('intent', '')} {a.get('reason', '')}".strip(), duration_ms=duration)
    if name == "llm.generate":
        detail = f"{a.get('tokens_in', 0):,} → {a.get('tokens_out', 0):,} tokens"
        if a.get("retries"):
            detail += f" · {_retries(a['retries'])}"
        if a.get("fallback_used"):
            detail += " · backup model"
        if a.get("error") and span.get("status") == "ERROR":
            detail = f"{a['error']} · {_retries(a.get('retries', 0))}"
        status = "error" if span.get("status") == "ERROR" else "ok"
        return TraceRow(label=f"llm {a.get('model', '')}", status=status, detail=detail, duration_ms=duration)
    if name == "guard.sql":
        if a.get("decision") == "allowed":
            return TraceRow(label="sql validation", status="ok", detail=a.get("route", ""), duration_ms=duration)
        refused = a.get("reason") in ("pii", "scope")
        return TraceRow(label="sql validation", status="refusal" if refused else "error",
                        detail=a.get("detail") or a.get("reason", ""), duration_ms=duration)
    if name == "bq.dry_run" and a.get("error"):
        return TraceRow(label="dry run", status="error", detail=str(a["error"])[:60], duration_ms=duration)
    if name == "bq.query":
        if a.get("error") or a.get("cancelled"):
            return TraceRow(label="bigquery", status="error", detail=str(a.get("error", "cancelled"))[:60],
                            duration_ms=duration)
        rows = int(a.get("rows", 0))
        detail = f"{_fmt_bytes(int(a.get('bytes', 0)))} · {rows} {'row' if rows == 1 else 'rows'}"
        return TraceRow(label="bigquery", status="ok", detail=detail, duration_ms=duration)
    if name == "bq.diagnostic":
        found = "the value exists" if a.get("exists") else f"{a.get('values', 0)} other values"
        return TraceRow(label="empty result check", status="info", detail=f"{a.get('column', '')}: {found}",
                        duration_ms=duration)
    if name == "guard.output":
        blocked = a.get("decision") == "blocked"
        dropped = a.get("dropped_blocks") or []
        detail = a.get("reason", "") if blocked else (f"dropped {', '.join(dropped)}" if dropped else "")
        return TraceRow(label="output check", status="refusal" if blocked else "ok", detail=detail,
                        duration_ms=duration)
    if name in ("confirmation", "undo"):
        return TraceRow(label=name, status="info", detail=str(a.get("state", "")), duration_ms=duration)
    if name == "report.save":
        return TraceRow(label="save report", status="ok", detail=f"{a.get('customers', 0)} Customers",
                        duration_ms=duration)
    return None


def build(records: list[dict[str, Any]]) -> TraceView | None:
    """The trace view of one trace, or None when no root span is in the records."""
    spans = sorted((r for r in records if r.get("type") == "span"), key=lambda r: r["start"])
    root = next((span for span in spans if span.get("parent_id") is None), None)
    if root is None:
        return None
    attributes = root.get("attributes", {})
    outcome = attributes.get("turn.outcome") or (f"/{attributes['command']}" if "command" in attributes else "")
    limit = attributes.get("budget.limit")
    rows: list[TraceRow] = []
    failures = corrections = 0
    for span in spans:
        row = _row(span) if span is not root else None
        if row is None:
            continue
        if row.label.startswith("llm ") and failures > corrections:
            corrections = failures
            row.detail = f"correction {corrections} · {row.detail}"
        if row.status == "error" and row.label in ("sql validation", "dry run", "bigquery"):
            failures += 1
        rows.append(row)
    return TraceView(
        trace_id=root["trace_id"],
        started=datetime.fromisoformat(root["start"]),
        duration_ms=float(root.get("duration_ms", 0)),
        outcome=f"{outcome} ({limit})" if limit else outcome,
        rows=rows,
    )
