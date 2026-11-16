"""The `Warehouse` port on BigQuery, with the application default credentials.

Local runs impersonate the read-only service account `dca-agent`, so there is no key file.
"""

import concurrent.futures
from collections.abc import Sequence

from google.api_core import exceptions as gexc
from google.cloud import bigquery

from dca.core.ports import QueryResult, WarehouseCancelled, WarehouseError, WarehouseTransientError

_TRANSIENT = (
    gexc.InternalServerError,
    gexc.ServiceUnavailable,
    gexc.BadGateway,
    gexc.GatewayTimeout,
    gexc.TooManyRequests,
    gexc.DeadlineExceeded,
    concurrent.futures.TimeoutError,
    TimeoutError,
)


def _message(error: gexc.GoogleAPICallError) -> str:
    errors = getattr(error, "errors", None) or []
    if errors and isinstance(errors[0], dict) and errors[0].get("message"):
        return str(errors[0]["message"])
    return str(getattr(error, "message", error))


class BigQueryWarehouse:
    def __init__(self, project: str) -> None:
        self.project = project
        self._client: bigquery.Client | None = None

    @property
    def client(self) -> bigquery.Client:
        if self._client is None:
            self._client = bigquery.Client(project=self.project or None)
        return self._client

    @staticmethod
    def _params(params: dict[str, Sequence[str]]) -> list[bigquery.ArrayQueryParameter]:
        return [bigquery.ArrayQueryParameter(name, "STRING", list(values)) for name, values in params.items()]

    def dry_run(self, sql: str, params: dict[str, Sequence[str]]) -> int:
        config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False, query_parameters=self._params(params))
        try:
            job = self.client.query(sql, job_config=config)
        except gexc.BadRequest as error:
            raise WarehouseError(_message(error)) from None
        except _TRANSIENT as error:
            raise WarehouseTransientError(type(error).__name__) from None
        return int(job.total_bytes_processed or 0)

    def run(
        self, sql: str, params: dict[str, Sequence[str]], *, max_bytes: int, timeout_s: float, job_id: str
    ) -> QueryResult:
        config = bigquery.QueryJobConfig(query_parameters=self._params(params), maximum_bytes_billed=max_bytes)
        try:
            # job_retry=None: our core does the retries, each with a new job ID (V8).
            job = self.client.query(sql, job_config=config, job_id=job_id, job_retry=None)
            rows = job.result(timeout=timeout_s)
        except gexc.BadRequest as error:
            if "cancel" in _message(error).lower():
                raise WarehouseCancelled() from None
            raise WarehouseError(_message(error)) from None
        except _TRANSIENT as error:
            # The core cancels the job and decides on a retry (V8, V9).
            raise WarehouseTransientError(type(error).__name__, job_id=job_id) from None
        columns = [field.name for field in rows.schema]
        data = [list(row.values()) for row in rows]
        return QueryResult(job_id=job.job_id, columns=columns, rows=data, bytes_processed=int(job.total_bytes_processed or 0))

    def cancel(self, job_id: str) -> None:
        try:
            self.client.cancel_job(job_id)
        except Exception:  # noqa: BLE001 - a cancel is best effort
            pass
