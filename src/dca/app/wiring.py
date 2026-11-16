"""Builds the Turn API with the local adapters of the prototype (HLD 19)."""

from dotenv import load_dotenv

from dca.adapters import chaos
from dca.adapters.bigquery_warehouse import BigQueryWarehouse
from dca.adapters.gemini_llm import GeminiLLMClient
from dca.adapters.local_stores import InMemorySessionStore, JsonConfigStore, SchemaKnowledgeStore
from dca.adapters.otel_tracer import JsonlTracer
from dca.adapters.sqlite_reports import SQLiteReportStore
from dca.agent.adk_loop import AdkAgentLoop, gemini_factory
from dca.app.turn_api import TurnAPI
from dca.config import Settings


def build_turn_api(settings: Settings | None = None) -> TurnAPI:
    load_dotenv()  # google-genai and ADK read GOOGLE_API_KEY from the environment.
    settings = settings or Settings()
    knowledge = SchemaKnowledgeStore()
    llm, model_factory, warehouse = chaos.wrap(
        settings.chaos,
        settings.chaos_seed,
        GeminiLLMClient(settings.google_api_key, settings.timeout.llm_call_s),
        gemini_factory,
        BigQueryWarehouse(settings.google_cloud_project),
    )
    return TurnAPI(
        settings=settings,
        config_store=JsonConfigStore(settings.paths.executives),
        session_store=InMemorySessionStore(),
        warehouse=warehouse,
        tracer=JsonlTracer(settings.paths.trace_file),
        knowledge=knowledge,
        llm=llm,
        agent_loop=AdkAgentLoop(model_factory, knowledge),
        report_store=SQLiteReportStore(settings.paths.reports_db),
    )
