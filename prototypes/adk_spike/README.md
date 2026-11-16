# PROTOTYPE: ADK spike (ADR 0003)

Throwaway code. It answers one question: can Google ADK be the agent loop adapter, and does the BigQuery aggregation threshold work on a view over the public dataset? Do not import this code from `src/`.

## Run

```bash
PROJECT_ID=<your-project-id> scripts/setup-gcp.sh
```

```bash
gcloud auth application-default login --impersonate-service-account=dca-agent@<your-project-id>.iam.gserviceaccount.com
```

```bash
sed 's/PROJECT_ID/<your-project-id>/g' scripts/threshold-views.sql | bq query --use_legacy_sql=false
```

```bash
uv run python prototypes/adk_spike/spike_bq_threshold.py
```

```bash
uv run python prototypes/adk_spike/spike_adk.py
```

`spike_adk.py` needs `GOOGLE_API_KEY` in `.env` (see `.env.example`). It writes spans to `PROTOTYPE_wipe_me_traces.jsonl`, which Git ignores.

| File | Check |
| --- | --- |
| `spike_adk.py` | 1. `before_tool_callback` blocks a query that selects PII. 2. The session state carries the Brand scope, also in a second Runner. 3. Spans get to the JSONL file, and our guard span is in the same trace as the ADK spans. |
| `spike_bq_threshold.py` | 4. `SELECT WITH AGGREGATION_THRESHOLD` on a view over `thelook_ecommerce`, with the Brand scope as a query parameter and as a CTE. |
| `guard.py` | A minimal PII guard with no ADK imports (P6). |
| `jsonl_exporter.py` | An OpenTelemetry span exporter to a JSONL file. |
