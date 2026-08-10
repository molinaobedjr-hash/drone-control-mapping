"""Persistent TX16S axis mapping."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


CONTROL_NAMES = (
    "roll",
    "pitch",
    "yaw",
    "throttle",
)


@dataclass(slots=True)
class AxisMapping:
    axis_index: int
    inverted: bool = False


@dataclass(slots=True)
class ControllerMapping:
    roll: AxisMapping | None = None
    pitch: AxisMapping | None = None
    yaw: AxisMapping | None = None
    throttle: AxisMapping | None = None

    @property
    def complete(self) -> bool:
        return all(
            getattr(self, name) is not None
            for name in CONTROL_NAMES
        )

    def map_value(
        self,
        control: str,
        axes: tuple[float, ...],
    ) -> float | None:
        mapping = getattr(self, control, None)

        if mapping is None:
            return None

        if not 0 <= mapping.axis_index < len(axes):
            return None

        value = float(axes[mapping.axis_index])

        if mapping.inverted:
            value *= -1.0

        return max(-1.0, min(1.0, value))


def load_mapping(
    path: Path,
) -> ControllerMapping:
    """Load mapping JSON. Invalid/missing files fall back safely."""
    if not path.exists():
        return ControllerMapping()

    try:
        raw = json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        return ControllerMapping()

    mapping = ControllerMapping()

    for control in CONTROL_NAMES:
        item = raw.get(control)

        if not isinstance(item, dict):
            continue

        try:
            axis_index = int(item["axis_index"])
            inverted = bool(item.get("inverted", False))
        except (KeyError, TypeError, ValueError):
            continue

        setattr(
            mapping,
            control,
            AxisMapping(
                axis_index=axis_index,
                inverted=inverted,
            ),
        )

    return mapping


def save_mapping(
    path: Path,
    mapping: ControllerMapping,
) -> None:
    """Persist mapping as readable JSON."""
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload: dict[str, dict | None] = {}

    for control in CONTROL_NAMES:
        item = getattr(mapping, control)
        payload[control] = (
            asdict(item)
            if item is not None
            else None
        )

    path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
