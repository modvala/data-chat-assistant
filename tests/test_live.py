"""Opt-in tests against the reviewer project: `uv run pytest --live`.

They need GOOGLE_API_KEY and GOOGLE_CLOUD_PROJECT in .env, and ADC as dca-agent.
"""

import pytest

from dca.adapters.bigquery_warehouse import BigQueryWarehouse
from dca.app.wiring import build_turn_api
from dca.config import Settings
from dca.core.answer import Table

pytestmark = pytest.mark.live


class RecordingWarehouse(BigQueryWarehouse):
    def __init__(self, project: str) -> None:
        super().__init__(project)
        self.results = []

    def run(self, sql, params, *, max_bytes, timeout_s, job_id):  # type: ignore[no-untyped-def]
        result = super().run(sql, params, max_bytes=max_bytes, timeout_s=timeout_s, job_id=job_id)
        if not job_id.startswith("dca-brands-"):
            self.results.append(result)
        return result


def test_ac_r2_2_live_manager_figure_equals_the_reference_query() -> None:
    settings = Settings()
    api = build_turn_api(settings)
    warehouse = RecordingWarehouse(settings.google_cloud_project)
    api.warehouse = warehouse
    api.access.warehouse = warehouse
    session = api.start_session("mgr_ana")
    brands = api.access.grant("mgr_ana").brands

    result = api.send_message(
        session.session_id,
        "What is the total sale_price of all order items of my brands, for all statuses and all time? "
        "Give one number in a table.",
    )

    assert result.kind == "answer", result
    agent_figure = float(warehouse.results[-1].rows[0][-1])
    dataset = settings.warehouse.source_dataset
    reference = warehouse.run(
        f"SELECT SUM(oi.sale_price) FROM `{dataset}.order_items` AS oi "
        f"JOIN `{dataset}.products` AS p ON p.id = oi.product_id WHERE p.brand IN UNNEST(@brands)",
        {"brands": brands},
        max_bytes=settings.budget.query_bytes,
        timeout_s=settings.timeout.bq_job_s,
        job_id="dca-test-reference-" + session.session_id,
    )
    assert agent_figure == pytest.approx(float(reference.rows[0][0]), rel=1e-6)


def test_live_smoke_turn_with_the_real_gemini_model() -> None:
    api = build_turn_api(Settings())
    session = api.start_session("mgr_ana")
    result = api.send_message(session.session_id, "What is the monthly revenue of my brands in the last 3 months?")
    assert result.kind == "answer", result
    assert any(isinstance(block, Table) for block in result.blocks) or result.blocks
