# Google ADK is the agent framework, with a spike first

Scope: both

We use Google ADK (`google-adk`) to run the agent loop. It is made for Gemini and GCP, and it gives callbacks before each tool call (a place for our guardrails), session services for a stateless service (P21), built-in OpenTelemetry and `adk eval`. We have no earlier experience with ADK. Our experience is with LangChain, and its concepts map almost one-to-one to ADK. To control this risk, ADK is only a thin adapter (P6). All safety logic is plain Python with no ADK imports.

Before we commit to ADK, a time-boxed spike of 1–2 hours must pass these checks:

1. A `before_tool_callback` blocks a query that selects PII.
2. The session state carries the Brand scope.
3. A span gets to the JSONL trace file.
4. `SELECT WITH AGGREGATION_THRESHOLD` works on a view over the public dataset (see ADR 0005).

If checks 1–3 fail, the adapter changes to a plain `google-genai` loop. The core does not change.

## Considered options

- **LangGraph**: closest to our experience, but weaker GCP story.
- **PydanticAI inside ADK**: two frameworks, two sets of concepts and two upgrade cycles, for no gain.
- **Plain `google-genai` first, ADK later**: double work in a 6–12 hour assignment.
