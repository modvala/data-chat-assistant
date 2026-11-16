# Data Chat Assistant

**Documentation site:** https://modvala.github.io/data-chat-assistant/

A CLI chat agent for the Executives of a retail company. An Executive asks a question about the sales data in BigQuery in plain language. The agent writes the SQL at run time, runs it in the Brand scope of the Executive and gives an Answer with analysis and, on request, Action items. The prototype also has the four required features: safety and PII masking, a strict confirmation for deletes, resilience and observability.

## Start here

- [Get started](docs/site/get-started.md): install, set up GCP, run the chat (with uv or with Docker), the tests and the configuration.
- [Executive guide](docs/site/guide.md): how to ask questions, read Answers and use the commands.
- [Demo tour](docs/site/demo-tour.md): one scenario for each required feature.

## Documentation

- [High-level design](docs/design/hld.md): the architecture of the whole solution.
- [Assumptions and starting values](docs/design/hld.md#3-assumptions-and-starting-values): what we selected because the customer did not give it.
- [CLI design](docs/design/cli.md): how the CLI shows Answers.
- [Requirements coverage](docs/requirements-coverage.md): each acceptance criterion with its design, code, tests and demo.
- [Tech stack](docs/tech-stack.md)
- [Architecture decision records](docs/adr/)
- [Design principles](docs/design-principles.md)
- [Glossary](CONTEXT.md)
