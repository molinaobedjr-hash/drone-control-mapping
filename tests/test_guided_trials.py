"""State-machine tests for Milestone 8 guided mapping trials."""

from __future__ import annotations

import unittest

from dcmf.core.guided_trials import (
    GUIDED_ACTIONS,
    GuidedTrialTracker,
)


class GuidedTrialTrackerTests(unittest.TestCase):
    def test_assigns_interval_labels_and_repeat_numbers(
        self,
    ) -> None:
        tracker = GuidedTrialTracker(
            target_repetitions=3
        )

        first = tracker.begin("ROLL_RIGHT")
        self.assertEqual(first.trial_number, 1)
        self.assertEqual(
            first.start_label,
            "ROLL_RIGHT_START",
        )
        self.assertEqual(
            first.end_label,
            "ROLL_RIGHT_END",
        )
        tracker.end()

        second = tracker.begin("ROLL_RIGHT")
        self.assertEqual(second.trial_number, 2)
        tracker.end()

        self.assertEqual(
            tracker.completed["ROLL_RIGHT"],
            2,
        )
        self.assertEqual(tracker.completed_total, 2)
        self.assertEqual(
            tracker.target_total,
            len(GUIDED_ACTIONS) * 3,
        )

    def test_rejects_overlapping_and_unmatched_trials(
        self,
    ) -> None:
        tracker = GuidedTrialTracker()

        with self.assertRaises(RuntimeError):
            tracker.end()

        tracker.begin("PITCH_FORWARD")
        with self.assertRaises(RuntimeError):
            tracker.begin("YAW_LEFT")

        tracker.end()
        with self.assertRaises(ValueError):
            tracker.begin("NOT_AN_ACTION")

    def test_selects_next_action_after_target_is_met(
        self,
    ) -> None:
        tracker = GuidedTrialTracker(
            target_repetitions=1
        )
        tracker.begin("ROLL_RIGHT")
        tracker.end()

        self.assertEqual(
            tracker.next_incomplete_action(
                "ROLL_RIGHT"
            ),
            "ROLL_LEFT",
        )


if __name__ == "__main__":
    unittest.main()
