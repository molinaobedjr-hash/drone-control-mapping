from __future__ import annotations
import time
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(slots=True, frozen=True)
class Timestamp:
    monotonic_ns: int
    utc_ns: int

    @property
    def monotonic_seconds(self) -> float:
        return self.monotonic_ns / 1_000_000_000

    @property
    def utc_iso(self) -> str:
        return datetime.fromtimestamp(
            self.utc_ns / 1_000_000_000, tz=timezone.utc
        ).isoformat()

class MasterClock:
    @staticmethod
    def now() -> Timestamp:
        return Timestamp(time.perf_counter_ns(), time.time_ns())
