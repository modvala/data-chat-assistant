"""Chaos mode (HLD 15.6): `CHAOS=llm_429:0.3,bq_timeout:0.1` injects failures into the adapters.

The wrappers go around the `LLMClient` adapter, the ADK model and the `Warehouse` adapter.
`CHAOS_SEED` makes the failures repeatable.
"""

import random
from collections.abc import AsyncGenerator, Callable, Sequence
from typing import Any

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from pydantic import ConfigDict

from dca.core.ports import LLMClient, LLMResult, LLMTransientError, QueryResult, Warehouse, WarehouseTransientError

FAULTS = {
    "llm_429": 429,
    "llm_503": 503,
    "llm_timeout": 504,
    "bq_timeout": "timeout",
    "bq_5xx": "server error",
}


class Chaos:
    def __init__(self, spec: str, seed: int | None = None) -> None:
        self.rates: dict[str, float] = {}
        for part in filter(None, (item.strip() for item in spec.split(","))):
            name, _, rate = part.partition(":")
            if name not in FAULTS:
                raise ValueError(f"Unknown CHAOS fault {name!r}. Known faults: {', '.join(FAULTS)}.")
            self.rates[name] = float(rate or 1)
        self.rng = random.Random(seed)

    def fault(self, prefix: str) -> str | None:
        """The name of the fault to inject now, or None."""
        for name, rate in self.rates.items():
            if name.startswith(prefix) and self.rng.random() < rate:
                return name
        return None


class ChaosLLMClient:
    def __init__(self, inner: LLMClient, chaos: Chaos) -> None:
        self.inner = inner
        self.chaos = chaos

    def generate(self, prompt: str, *, model: str, system: str = "", json_schema: dict | None = None) -> LLMResult:
        if fault := self.chaos.fault("llm_"):
            raise LLMTransientError(int(FAULTS[fault]))
        return self.inner.generate(prompt, model=model, system=system, json_schema=json_schema)


class ChaosModel(BaseLlm):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    inner: BaseLlm
    chaos: Any

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if fault := self.chaos.fault("llm_"):
            raise LLMTransientError(int(FAULTS[fault]))
        async for response in self.inner.generate_content_async(llm_request, stream):
            yield response


class ChaosWarehouse:
    def __init__(self, inner: Warehouse, chaos: Chaos) -> None:
        self.inner = inner
        self.chaos = chaos

    def dry_run(self, sql: str, params: dict[str, Sequence[str]]) -> int:
        if fault := self.chaos.fault("bq_"):
            raise WarehouseTransientError(str(FAULTS[fault]))
        return self.inner.dry_run(sql, params)

    def run(
        self, sql: str, params: dict[str, Sequence[str]], *, max_bytes: int, timeout_s: float, job_id: str
    ) -> QueryResult:
        if fault := self.chaos.fault("bq_"):
            raise WarehouseTransientError(str(FAULTS[fault]), job_id=job_id)
        return self.inner.run(sql, params, max_bytes=max_bytes, timeout_s=timeout_s, job_id=job_id)

    def cancel(self, job_id: str) -> None:
        self.inner.cancel(job_id)


def wrap(
    spec: str, seed: int | None, llm: LLMClient, model_factory: Callable[[str], BaseLlm], warehouse: Warehouse
) -> tuple[LLMClient, Callable[[str], BaseLlm], Warehouse]:
    """The three adapters with chaos, or the same adapters when `spec` is empty."""
    if not spec:
        return llm, model_factory, warehouse
    chaos = Chaos(spec, seed)
    return (
        ChaosLLMClient(llm, chaos),
        lambda model: ChaosModel(model=model, inner=model_factory(model), chaos=chaos),
        ChaosWarehouse(warehouse, chaos),
    )
