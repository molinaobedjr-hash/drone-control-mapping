"""State and invariants for guided control-mapping trials."""

from __future__ import annotations

from dataclasses import dataclass


GUIDED_ACTIONS = (
    "ROLL_RIGHT",
    "ROLL_LEFT",
    "PITCH_FORWARD",
    "PITCH_BACK",
    "YAW_RIGHT",
    "YAW_LEFT",
    "THROTTLE_UP",
    "THROTTLE_DOWN",
)


@dataclass(slots=True, frozen=True)
class GuidedTrial:
    """One numbered action interval."""

    action: str
    trial_number: int

    @property
    def start_label(self) -> str:
        return f"{self.action}_START"

    @property
    def end_label(self) -> str:
        return f"{self.action}_END"


class GuidedTrialTracker:
    """Prevent overlapping trials and assign repeat numbers."""

    def __init__(
        self,
        target_repetitions: int = 3,
    ) -> None:
        self.target_repetitions = 3
        self.completed: dict[str, int] = {}
        self.active_trial: GuidedTrial | None = None
        self.reset(target_repetitions)

    def reset(
        self,
        target_repetitions: int | None = None,
    ) -> None:
        if target_repetitions is not None:
            self.set_target_repetitions(
                target_repetitions
            )

        self.completed = {
            action: 0
            for action in GUIDED_ACTIONS
        }
        self.active_trial = None

    def set_target_repetitions(
        self,
        value: int,
    ) -> None:
        if self.active_trial is not None:
            raise RuntimeError(
                "Cannot change the repetition target during a trial."
            )
        if value < 1:
            raise ValueError(
                "Target repetitions must be at least one."
            )
        self.target_repetitions = int(value)

    def begin(self, action: str) -> GuidedTrial:
        if action not in GUIDED_ACTIONS:
            raise ValueError(
                f"Unknown guided action: {action}"
            )
        if self.active_trial is not None:
            raise RuntimeError(
                "End the active guided trial before starting another."
            )

        trial = GuidedTrial(
            action=action,
            trial_number=(
                self.completed[action] + 1
            ),
        )
        self.active_trial = trial
        return trial

    def end(self) -> GuidedTrial:
        trial = self.active_trial
        if trial is None:
            raise RuntimeError(
                "No guided trial is active."
            )

        self.completed[trial.action] = max(
            self.completed[trial.action],
            trial.trial_number,
        )
        self.active_trial = None
        return trial

    @property
    def completed_total(self) -> int:
        return sum(self.completed.values())

    @property
    def target_total(self) -> int:
        return (
            len(GUIDED_ACTIONS)
            * self.target_repetitions
        )

    def next_incomplete_action(
        self,
        after: str,
    ) -> str:
        """Return the next action below its target, wrapping once."""
        start = GUIDED_ACTIONS.index(after)

        for offset in range(1, len(GUIDED_ACTIONS) + 1):
            action = GUIDED_ACTIONS[
                (start + offset) % len(GUIDED_ACTIONS)
            ]
            if (
                self.completed[action]
                < self.target_repetitions
            ):
                return action

        return after
