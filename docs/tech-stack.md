# Tech stack

This page lists the selected tools and services. The reasons for the decisions that are hard to change are in the [ADRs](adr/). The design will give the alternatives for each building block in its "Key decisions" table (P18).

## Prototype

| Part | Selection |
| --- | --- |
| Language and dependencies | Python 3.12, uv with `pyproject.toml` and `uv.lock`, `requirements.txt` as a fallback (P19) |
| Agent framework | Google ADK 2.x; the spike passed ([ADR 0003](adr/0003-google-adk-framework.md)) |
| LLM | `gemini-3.8-flash` as the main model, `gemini-3.5-flash-lite` as the fallback, from the Gemini API free tier. The model IDs and rate limits are in the configuration (P17). |
| Embeddings | `gemini-embedding-2`, with an in-memory cosine search (numpy) over the Trios |
| CLI | Typer and Rich |
| SQL validation and rewrite | sqlglot, BigQuery dialect |
| Warehouse | BigQuery, `bigquery-public-data.thelook_ecommerce`. The BigQuery sandbox is sufficient. |
| GCP identity | The service account `dca-agent` with `bigquery.jobUser` on the project and read access to the `dca_views` dataset. Local runs impersonate it, so there is no key file. `scripts/setup-gcp.sh` makes it. |
| Local stores | SQLite for Saved Reports and the audit log; YAML for the Executive profiles, `persona.yaml` and `executives.json` |
| Configuration models | Pydantic |
| Tracing | OpenTelemetry SDK with a JSONL exporter. `/trace` reads the JSONL file. |
| Tests | pytest |

## Production (GCP)

| Part | Service |
| --- | --- |
| Turn service | Cloud Run, behind IAP ([ADR 0004](adr/0004-cloud-run-and-firestore.md)) |
| LLM | Gemini on Vertex AI (paid, so the data is not used to improve Google products) |
| Warehouse and scope | BigQuery with row access policies or authorized views, queried with the identity of the Executive ([ADR 0001](adr/0001-brand-scope-by-view-rewrite.md)) |
| State | Firestore: sessions, pending confirmations, Saved Reports, the audit log, Executive profiles and the Persona |
| Golden Bucket | GCS for the raw Trios, BigQuery `VECTOR_SEARCH` for retrieval |
| Extra guardrails | Sensitive Data Protection (DLP) and Model Armor |
| Observability | Cloud Trace, Logging and Monitoring, and a log sink to BigQuery for masked structured logs |
| Learning loop jobs | Pub/Sub, Cloud Run Jobs and Cloud Scheduler |
| Secrets | Secret Manager |

## Documentation site

| Part | Selection |
| --- | --- |
| Generator | Material for MkDocs 9.8 (end of life 2027-05-05; Zensical reads the same `mkdocs.yml`) |
| Hosting | GitHub Pages, built by a GitHub Action from `docs/` (P24) |
| Content | Architecture diagrams, the [coverage table](requirements-coverage.md), the ADRs, a VHS recording of the CLI and the eval report |
| Eval in CI | Workload Identity Federation for BigQuery, the Gemini key as a GitHub secret; runs on `workflow_dispatch` and on a push to `main` that changes `src/` or `eval/` |
