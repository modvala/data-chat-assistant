"""The `Tracer` port on the OpenTelemetry SDK, with a JSONL exporter (HLD 16).

The exporter is on the global tracer provider, so the ADK spans and our spans are in one
trace. Log lines go to the same file. A failure to write never fails a Turn (HLD 15.3).
"""

import json
import logging
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode, format_span_id, format_trace_id

SCOPE = "dca"
# Spans of other libraries (ADK) keep only these attributes: no prompt, answer or tool text (P9).
FOREIGN_KEYS = frozenset(
    {
        "gen_ai.operation.name",
        "gen_ai.request.model",
        "gen_ai.agent.name",
        "gen_ai.tool.name",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
    }
)

log = logging.getLogger(__name__)


class _JsonlFile:
    """The file that the exporter and the logs write to. One file is active at a time."""

    def __init__(self) -> None:
        self.path: Path | None = None
        self.lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        if self.path is None:
            return
        try:
            line = json.dumps(record, default=str)
            with self.lock, self.path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
        except Exception:  # noqa: BLE001 - a trace failure must not fail a Turn
            log.warning("Could not write to the trace file", exc_info=True)


_FILE = _JsonlFile()


class JsonlSpanExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            _FILE.write(span_record(span))
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def span_record(span: ReadableSpan) -> dict[str, Any]:
    ours = span.instrumentation_scope is not None and span.instrumentation_scope.name == SCOPE
    attributes = {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in (span.attributes or {}).items()
        if ours or key in FOREIGN_KEYS
    }
    start, end = span.start_time or 0, span.end_time or 0
    return {
        "type": "span",
        "name": span.name,
        "trace_id": format_trace_id(span.context.trace_id),
        "span_id": format_span_id(span.context.span_id),
        "parent_id": format_span_id(span.parent.span_id) if span.parent else None,
        "start": datetime.fromtimestamp(start / 1e9, UTC).isoformat(),
        "duration_ms": round((end - start) / 1e6, 1),
        "status": span.status.status_code.name,
        "attributes": attributes,
    }


class JsonlLogHandler(logging.Handler):
    """Library log records (ADK, google-genai) go to the trace file as JSON, never to the terminal.

    The record keeps the logger, the level, the message and the error type, with no traceback,
    so the Executive never sees a stack trace (cli.md P-FAIL).
    """

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == __name__:
            return
        context = trace.get_current_span().get_span_context()
        _FILE.write(
            {
                "type": "log",
                "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "trace_id": format_trace_id(context.trace_id) if context.is_valid else "",
                "event": "library.log",
                "logger": record.name,
                "level": record.levelname,
                "message": record.getMessage()[:200],
                "error": record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else "",
            }
        )


_PROVIDER_LOCK = threading.Lock()
_INSTALLED = False


def _install_provider() -> None:
    global _INSTALLED
    with _PROVIDER_LOCK:
        if _INSTALLED:
            return
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
        provider.add_span_processor(SimpleSpanProcessor(JsonlSpanExporter()))
        root = logging.getLogger()
        root.addHandler(JsonlLogHandler(level=logging.WARNING))
        _INSTALLED = True


class _Span:
    def __init__(self, span: trace.Span) -> None:
        self._span = span

    def set(self, key: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, list | tuple):
            value = [item if isinstance(item, str | int | float | bool) else json.dumps(item, default=str) for item in value]
        elif isinstance(value, dict):
            value = json.dumps(value, default=str)
        self._span.set_attribute(key, value)


class JsonlTracer:
    def __init__(self, path: Path) -> None:
        _install_provider()
        _FILE.path = path
        self.path = path
        self._tracer = trace.get_tracer(SCOPE)

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[_Span]:
        with self._tracer.start_as_current_span(name, record_exception=False, set_status_on_exception=False) as otel:
            wrapper = _Span(otel)
            for key, value in attributes.items():
                wrapper.set(key, value)
            try:
                yield wrapper
            except GeneratorExit:
                raise  # The caller closed a generator inside the span (ADK after a tool ends the Turn): no error.
            except BaseException as error:
                otel.set_status(Status(StatusCode.ERROR, type(error).__name__))
                raise

    def current_trace_id(self) -> str:
        context = trace.get_current_span().get_span_context()
        return format_trace_id(context.trace_id) if context.is_valid else ""

    def log(self, event: str, **fields: Any) -> None:
        _FILE.write(
            {
                "type": "log",
                "time": datetime.now(UTC).isoformat(),
                "trace_id": self.current_trace_id(),
                "event": event,
                **fields,
            }
        )

    def read(self, trace_id: str) -> list[dict]:
        if not trace_id or not self.path.exists():
            return []
        records = []
        with self.path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(record.get("trace_id", "")).startswith(trace_id):
                    records.append(record)
        return records
