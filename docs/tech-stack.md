# Tech stack

This page lists the selected tools and services. The reasons for the decisions that are hard to change are in the [ADRs](adr/). The alternatives for each building block are in the [Key decisions](design/hld.md#24-key-decisions) table of the HLD (P18).

## Prototype

| Part | Selection |
| --- | --- |
| Language and dependencies | Python 3.12, uv with `pyproject.toml` and `uv.lock` (P19) |
| Agent framework | Google ADK 2.x; the spike passed ([ADR 0003](adr/0003-google-adk-framework.md)) |
| LLM | `gemini-3.8-flash` as the main model, `gemini-3.5-flash-lite` as the fallback, from the Gemini API free tier. The model IDs, the retries and the timeouts are in `config/defaults.toml` (P17). |
| CLI | Typer and Rich |
| SQL validation and rewrite | sqlglot, BigQuery dialect |
| Warehouse | BigQuery, `bigquery-public-data.thelook_ecommerce`. The BigQuery sandbox is sufficient. |
| GCP identity | The service account `dca-agent` with `bigquery.jobUser` on the project and read access to the `dca_views` dataset. Local runs impersonate it, so there is no key file. `scripts/setup-gcp.sh` makes it. |
| Local stores | SQLite (`data/dca_reports.sqlite`) for Saved Reports, the delete batches and the audit log. `executives.json` for the access mapping. The session state is in memory. |
| Configuration models | Pydantic |
| Tracing | OpenTelemetry SDK with a JSONL exporter. `/trace` reads the JSONL file. |
| Tests | pytest |
| Container (optional) | Docker: `docker/Dockerfile` with the app and the Google Cloud CLI, and `compose.yaml`. It is for a reviewer whose host has only Docker. The hosted mode does not use it. |

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
| Hosting | GitHub Pages, built by a GitHub Action from `docs/site/` only (P24) |
| Content | Home, Demo tour, Get started, Executive guide, How it works and Key decisions |
