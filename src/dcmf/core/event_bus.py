from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from PySide6.QtCore import QObject, Signal
from dcmf.utils.timestamps import MasterClock, Timestamp

@dataclass(slots=True, frozen=True)
class DcmfEvent:
    source: str
    kind: str
    payload: Any
    timestamp: Timestamp

class EventBus(QObject):
    event_published = Signal(object)

    def publish(self, source: str, kind: str, payload: Any) -> DcmfEvent:
        event = DcmfEvent(source, kind, payload, MasterClock.now())
        self.event_published.emit(event)
        return event
