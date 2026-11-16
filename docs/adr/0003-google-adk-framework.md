# Google ADK is the agent framework, with a spike first

Scope: both

We use Google ADK (`google-adk`) to run the agent loop. It is made for Gemini and GCP, and it gives callbacks before each tool call (a place for our guardrails), session services for a stateless service (P21), built-in OpenTelemetry and `adk eval`. We have no earlier experience with ADK. Our experience is with LangChain, and its concepts map almost one-to-one to ADK. To control this risk, ADK is only a thin adapter (P6). All safety logic is plain Python with no ADK imports.

Before we commit to ADK, a time-boxed spike of 1–2 hours must pass these checks:

1. A `before_tool_callback` blocks a query that selects PII.
2. The session state carries the Brand scope.
3. A span gets to the JSONL trace file.
4. `SELECT WITH AGGREGATION_THRESHOLD` works on a view over the public dataset (see ADR 0005).

If checks 1–3 fail, the adapter changes to a plain `google-genai` loop. The core does not change.

## Spike result

On 2026-11-16, all four checks passed with `google-adk` 2.14.1 and `gemini-3.5-flash`. Thus we use ADK. The spike code is on the branch [`prototype/adk-spike`](https://github.com/modvala/data-chat-assistant/tree/prototype/adk-spike) and is not in `main`.

| Check | Result |
| --- | --- |
| 1. PII block | The callback calls a plain Python guard with no ADK imports, and returns an error dict. The tool body does not run. |
| 2. Brand scope in the session | The tool reads the scope from `tool_context.state`. A second `Runner` on the same session service gets the same state and the state that the tool wrote. This is the shape of P21. |
| 3. JSONL trace | ADK uses the global OpenTelemetry tracer provider. Each Turn is one trace. Our `guard.sql` span is in the same trace as the ADK spans. By default, ADK writes no prompt text, answer text or tool arguments to the span attributes (P9). |
| 4. Threshold view | Passed. The details are in ADR 0005. |

What the spike also showed:

- On the free tier, `gemini-3.8-flash` often returned 503 "high demand", and `gemini-3.5-flash-lite` sometimes did too. The default retry of `google-genai` hid a 503 for minutes. Set `retry_options` on the ADK `Gemini` model to bound the retries (P15).
- After the retries, a 503 stops the whole ADK run. ADK does not change to a different model. Our Turn error handler must catch the error and run the Turn again with the fallback model (P15).

## Considered options

- **LangGraph**: closest to our experience, but weaker GCP story.
- **PydanticAI inside ADK**: two frameworks, two sets of concepts and two upgrade cycles, for no gain.
- **Plain `google-genai` first, ADK later**: double work in a 6–12 hour assignment.
