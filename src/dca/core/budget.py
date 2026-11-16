"""The Turn budget (V7, HLD 15.4). One Turn cannot cost too much.

A limit that runs out stops the Turn with a refusal `budget`. The refusal tells in plain words
which limit stopped the Turn, with no internal values (cli.md P-BUDGET).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from dca.config import Budget
from dca.core.turn import TurnStop

LIMIT_TEXT = {
    "llm_calls": "The question needed more steps than one question can use.",
    "llm_tokens": "The question needed more text than one question can use.",
    "turn_bytes": "The question needed to read more data than one question can use.",
    "query_bytes": "One query needed to read too much data.",
    "wall_time": "The question took longer than one question can take.",
}


@dataclass
class TurnBudget:
    limits: Budget
    clock: Callable[[], float] = time.monotonic
    started: float = field(default=0.0)
    llm_calls: int = 0
    llm_tokens: int = 0
    bytes_scanned: int = 0

    def __post_init__(self) -> None:
        self.started = self.started or self.clock()

    def remaining_s(self) -> float:
        return self.limits.wall_time_s - (self.clock() - self.started)

    def check_time(self) -> None:
        if self.remaining_s() <= 0:
            raise TurnStop("budget", "wall_time")

    def before_llm_call(self) -> None:
        self.check_time()
        if self.llm_calls >= self.limits.llm_calls:
            raise TurnStop("budget", "llm_calls")
        self.llm_calls += 1

    def add_tokens(self, tokens: int) -> None:
        self.llm_tokens += tokens
        if self.llm_tokens > self.limits.llm_tokens:
            raise TurnStop("budget", "llm_tokens")

    def before_query(self, estimate: int) -> None:
        self.check_time()
        if estimate > self.limits.query_bytes:
            raise TurnStop("budget", "query_bytes")
        if self.bytes_scanned + estimate > self.limits.turn_bytes:
            raise TurnStop("budget", "turn_bytes")

    def add_bytes(self, scanned: int) -> None:
        self.bytes_scanned += scanned
