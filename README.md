# Data Chat Assistant

Early-stage project. Customer requirements will be collected in [`docs/requirements/`](docs/requirements/).

Tasks are tracked as GitHub Issues on the project board.

## Documentation

- [Requirements coverage](docs/requirements-coverage.md): the acceptance criteria for each requirement.
- [Tech stack](docs/tech-stack.md)
- [Architecture decision records](docs/adr/)
- [Design principles](docs/design-principles.md)
- [Glossary](CONTEXT.md)

## Assumptions

These are our assumptions in addition to the [client decisions](docs/requirements/2026-11-12-client-decisions.md) (P3):

- "Client X" in "Delete all reports mentioning Client X" means a Customer. Each Saved Report records the IDs of the Customers that it mentions, and the delete matches on these IDs.
- The prototype has no real login. The CLI selects the Executive with `--executive <id>`, from `executives.json`.
- The prototype keeps its state in one process and in local files. Production keeps it in Firestore (P21).
- The prototype uses the Gemini API free tier. On the free tier, Google can use prompts and responses to improve its products. This is acceptable for the public synthetic dataset. Production uses Gemini on Vertex AI. Reviewers must use their own API key.
- The prototype has no semantic layer. Trios carry the interpretation of terms such as "churn" ([ADR 0007](docs/adr/0007-no-semantic-layer-in-prototype.md)).
