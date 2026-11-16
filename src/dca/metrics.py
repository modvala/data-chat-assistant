"""The agent metrics of HLD 16.2, from the JSONL trace file (AC-R7.2).

Each metric comes from a span attribute or a log field. No metric needs extra code in the Turn.

    uv run dca-metrics [data/dca_traces.jsonl]
"""

import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from dca.config import Settings


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return round(statistics.quantiles(values, n=100, method="inclusive")[percent - 1], 1)


def compute(records: list[dict[str, Any]]) -> dict[str, Any]:
    spans = [record for record in records if record.get("type") == "span"]
    turns = [span for span in spans if span["name"] == "turn"]
    named = {name: [span for span in spans if span["name"] == name] for name in {span["name"] for span in spans}}
    trace_of_turn = {span["trace_id"] for span in turns}

    def attr(span: dict, key: str, default: Any = None) -> Any:
        return span.get("attributes", {}).get(key, default)

    outcomes = Counter(attr(turn, "turn.outcome") for turn in turns)

    blocks: Counter[str] = Counter()
    for name in ("guard.input", "guard.sql", "guard.output"):
        for span in named.get(name, []):
            if attr(span, "decision") == "blocked":
                blocks[f"{name}:{attr(span, 'reason')}"] += 1

    tools = [span for span in named.get("tool.run_query", []) if span["trace_id"] in trace_of_turn]
    sql_turns = {span["trace_id"] for span in tools}
    corrected = [span for span in tools if attr(span, "correction", 0) > 0]
    # A corrected attempt ran when its tool.run_query span has a bq.query child with no error.
    ran = {
        query["parent_id"]
        for query in named.get("bq.query", [])
        if query["status"] != "ERROR" and "error" not in query.get("attributes", {})
    }

    queries = [span for span in named.get("bq.query", []) if "rows" in span.get("attributes", {})]
    llm_calls = named.get("llm.generate", [])
    confirmations = Counter(attr(span, "state") for span in named.get("confirmation", []))

    return {
        "turns": len(turns),
        "turn_success_rate": _rate(outcomes["answered"], len(turns)),
        "outcomes": dict(outcomes),
        "block_rate_by_reason": {reason: _rate(count, len(turns)) for reason, count in sorted(blocks.items())},
        "self_correction_rate": _rate(len({span["trace_id"] for span in corrected}), len(sql_turns)),
        "self_correction_success_rate": _rate(sum(span["span_id"] in ran for span in corrected), len(corrected)),
        "empty_result_rate": _rate(sum(attr(span, "rows") == 0 for span in queries), len(queries)),
        "llm_error_rate": _rate(sum(span["status"] == "ERROR" for span in llm_calls), len(llm_calls)),
        "llm_fallback_rate": _rate(sum(bool(attr(span, "fallback_used")) for span in llm_calls), len(llm_calls)),
        "latency_p50_ms": _percentile([float(turn["duration_ms"]) for turn in turns], 50),
        "latency_p95_ms": _percentile([float(turn["duration_ms"]) for turn in turns], 95),
        "cost_per_turn_usd": round(statistics.fmean(costs), 6)
        if (costs := [attr(turn, "turn.cost_usd") for turn in turns if attr(turn, "turn.cost_usd") is not None])
        else None,
        "confirmation_completion_rate": _rate(confirmations["done"], confirmations["pending"]),
        "confirmation_abort_rate": _rate(confirmations["cancelled"] + confirmations["expired"], confirmations["pending"]),
        "budget_stop_rate": _rate(sum(attr(turn, "budget.limit") is not None for turn in turns), len(turns)),
    }


def read(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Settings().paths.trace_file
    print(json.dumps(compute(read(path)), indent=2))
