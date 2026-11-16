# Data Chat Assistant

**Documentation site:** https://modvala.github.io/data-chat-assistant/

A CLI chat agent for the Executives of a retail company. An Executive asks a question about the sales data in BigQuery in plain language. The agent writes the SQL at run time, runs it in the Brand scope of the Executive and gives an Answer with analysis and, on request, Action items. The prototype also has the four required features: safety and PII masking, a strict confirmation for deletes, resilience and observability.

## Start here

- [Get started](docs/site/get-started.md): install, set up GCP, run the chat (with uv or with Docker), the tests and the configuration.
- [Executive guide](docs/site/guide.md): how to ask questions, read Answers and use the commands.
- [Demo tour](docs/site/demo-tour.md): one scenario for each required feature.

## Documentation

- [High-level design](docs/design/hld.md): the architecture of the whole solution.
- [CLI design](docs/design/cli.md): how the CLI shows Answers.
- [Requirements coverage](docs/requirements-coverage.md): each acceptance criterion with its design, code, tests and demo.
- [Tech stack](docs/tech-stack.md)
- [Architecture decision records](docs/adr/)
- [Design principles](docs/design-principles.md)
- [Glossary](CONTEXT.md)

## Assumptions

These are our assumptions in addition to the [client decisions](docs/requirements/2026-11-12-client-decisions.md) (P3):

- "Client X" in "Delete all reports mentioning Client X" means a Customer. Each Saved Report records the IDs of the Customers in the result rows of its queries, and the delete matches on these IDs. For a name, the agent asks for the Customer ID.
- The prototype has no real login. The CLI selects the Executive with `--executive <id>`, from `executives.json`.
- The prototype keeps its state in one process and in local files: sessions in memory, Saved Reports and the audit log in SQLite (`data/dca_reports.sqlite`), traces in `data/dca_traces.jsonl`. Production keeps them in Firestore and Cloud Trace (P21). Each Turn still loads and saves its state through the ports.
- The prototype uses the Gemini API free tier. On the free tier, Google can use prompts and responses to improve its products. This is acceptable for the public synthetic dataset. Production uses Gemini on Vertex AI. Reviewers must use their own API key. On the free tier, `gemini-3.8-flash` often answers "high demand"; the agent then retries and uses the backup model.
- The prototype has no Metric catalog (the industry name is "semantic layer"). The LLM interprets terms such as "churn" from the schema description ([ADR 0007](docs/adr/0007-no-metric-catalog-in-prototype.md)). The Golden Bucket and Trio retrieval are bonus features and are not in the prototype.
- A row list of Customers that shows age, gender, state or city gets a refusal `pii`, also with no filter on these columns. A demographic aggregate is permitted.
- The conversation context keeps the earlier answered Turns in full and a handle for each earlier query, within 6 k tokens. There is no LLM summary of older Turns. A refused Turn does not come back into the context.
- After the second failed SQL correction, the Executive gets an error notice, not a refusal `budget`. The trace records it as a budget stop.
- When the intent classifier fails, the message goes on as an analysis question. The SQL guard and the Output guard still check each query and each Answer.
- The prices for the "cost for each Turn" metric are starting values in the configuration, not quotes.
