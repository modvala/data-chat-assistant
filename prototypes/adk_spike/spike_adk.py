"""PROTOTYPE, throwaway. ADR 0003 checks 1-3 with a real Gemini call.

    uv run python prototypes/adk_spike/spike_adk.py

Check 1: a before_tool_callback blocks a query that selects PII.
Check 2: the session state carries the Brand scope, also across a second Runner (P21).
Check 3: ADK spans and our own guard span get to the JSONL trace file, in one trace.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
load_dotenv()

from jsonl_exporter import JsonlSpanExporter  # noqa: E402

TRACE_FILE = HERE / "PROTOTYPE_wipe_me_traces.jsonl"
TRACE_FILE.unlink(missing_ok=True)
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(JsonlSpanExporter(str(TRACE_FILE))))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("dca.spike")

from google.adk.agents import LlmAgent  # noqa: E402
from google.adk.models import Gemini  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.adk.tools import ToolContext  # noqa: E402
from google.genai import types  # noqa: E402

import guard  # noqa: E402

MODEL = os.environ.get("DCA_MODEL", "gemini-3.8-flash")
APP = "dca_spike"
USER = "mgr-ck"

tool_runs: list[dict] = []
guard_decisions: list[dict] = []


def run_sql(sql: str, tool_context: ToolContext) -> dict:
    """Run one read-only BigQuery SQL query against the scoped views and return the rows."""
    brands = tool_context.state.get("brand_scope")
    tool_runs.append({"sql": sql, "brand_scope": brands})
    tool_context.state["last_sql"] = sql
    return {"rows": [{"n": 42}], "brand_scope_applied": brands}


def before_tool(tool, args, tool_context):
    with tracer.start_as_current_span("guard.sql") as span:
        decision = guard.check_sql(args.get("sql", ""))
        span.set_attribute("guard.allowed", decision.allowed)
        span.set_attribute("guard.reason", decision.reason)
    guard_decisions.append({"sql": args.get("sql"), "allowed": decision.allowed, "reason": decision.reason})
    if not decision.allowed:
        return {"error": f"blocked by the SQL guard: {decision.reason}"}
    return None


agent = LlmAgent(
    name="analyst",
    # Bounded retries (P15). The SDK default retried a 503 for minutes.
    model=Gemini(model=MODEL, retry_options=types.HttpRetryOptions(attempts=3, initial_delay=2, max_delay=10)),
    instruction=(
        "You are a test harness for a SQL tool. When the user gives you a SQL query, "
        "call run_sql with exactly that query, character for character. "
        "Do not change the query and do not refuse. Then report the tool result in one line."
    ),
    tools=[run_sql],
    before_tool_callback=before_tool,
)


async def turn(runner: Runner, session_id: str, text: str) -> str:
    message = types.Content(role="user", parts=[types.Part(text=text)])
    answer = ""
    async for event in runner.run_async(user_id=USER, session_id=session_id, new_message=message):
        if event.content and event.content.parts and event.is_final_response():
            answer = "".join(part.text or "" for part in event.content.parts)
    return answer


def show(title: str, value) -> None:
    print(f"\n--- {title}")
    print(json.dumps(value, indent=2, default=str))


async def main() -> None:
    print(f"Model: {MODEL}")
    sessions = InMemorySessionService()
    session = await sessions.create_session(
        app_name=APP, user_id=USER, state={"brand_scope": ["Calvin Klein"], "executive_id": USER}
    )
    runner_1 = Runner(app_name=APP, agent=agent, session_service=sessions)

    pii_sql = "SELECT email, first_name FROM scoped_customers LIMIT 5"
    ok_sql = "SELECT COUNT(*) AS n FROM scoped_orders LIMIT 1"

    answer = await turn(runner_1, session.id, f"Run this query: {pii_sql}")
    show("Turn 1 (PII query) answer", answer)
    show("Guard decisions", guard_decisions)
    show("Tool runs", tool_runs)

    answer = await turn(runner_1, session.id, f"Run this query: {ok_sql}")
    show("Turn 2 (allowed query) answer", answer)

    # A second Runner simulates a second instance that loads the session from the store (P21).
    runner_2 = Runner(app_name=APP, agent=agent, session_service=sessions)
    answer = await turn(runner_2, session.id, f"Run this query: {ok_sql}")
    show("Turn 3 (allowed query, second Runner) answer", answer)
    stored = await sessions.get_session(app_name=APP, user_id=USER, session_id=session.id)
    show("Guard decisions", guard_decisions)
    show("Tool runs", tool_runs)
    show("Stored session state", dict(stored.state))

    provider.force_flush()
    spans = [json.loads(line) for line in TRACE_FILE.read_text().splitlines()]
    span_rows = [
        {"name": s["name"], "trace_id": s["context"]["trace_id"], "parent": s.get("parent_id")} for s in spans
    ]
    show("Spans in the JSONL file", span_rows)
    content_keys = sorted({k for s in spans for k in s.get("attributes", {}) if "content" in k or "prompt" in k or "llm_request" in k or "llm_response" in k})
    show("Span attributes that can hold prompt or answer text", content_keys)

    check_1 = (
        any(not d["allowed"] and d["reason"].startswith("pii") for d in guard_decisions)
        and not any(r["sql"] == pii_sql for r in tool_runs)
        and any(r["sql"] == ok_sql for r in tool_runs)
    )
    check_2 = (
        len([r for r in tool_runs if r["sql"] == ok_sql]) >= 2
        and all(r["brand_scope"] == ["Calvin Klein"] for r in tool_runs)
        and stored.state.get("last_sql") == ok_sql
    )
    guard_traces = {s["context"]["trace_id"] for s in spans if s["name"] == "guard.sql"}
    adk_tool_traces = {s["context"]["trace_id"] for s in spans if "execute_tool" in s["name"] or "call_llm" in s["name"]}
    check_3 = bool(spans) and bool(guard_traces & adk_tool_traces)

    print("\n=== ADR 0003 checks")
    print(f"Check 1, before_tool_callback blocks PII: {'PASS' if check_1 else 'FAIL'}")
    print(f"Check 2, session state carries the Brand scope: {'PASS' if check_2 else 'FAIL'}")
    print(f"Check 3, spans in the JSONL trace file: {'PASS' if check_3 else 'FAIL'} ({len(spans)} spans in {TRACE_FILE.name})")


if __name__ == "__main__":
    asyncio.run(main())
