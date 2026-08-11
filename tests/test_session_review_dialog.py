"""Tests for user-friendly completed-session display formatting."""

from __future__ import annotations

import unittest

from dcmf.gui.session_review_dialog import (
    _friendly_datetime,
    _friendly_duration,
    _timestamp_tooltip,
)


class SessionReviewFormattingTests(unittest.TestCase):
    def test_datetime_hides_machine_oriented_iso_precision(self) -> None:
        formatted = _friendly_datetime(
            "2026-08-11T21:34:25.309752+00:00"
        )

        self.assertIn("Aug 11, 2026 at", formatted)
        self.assertNotIn("T21:", formatted)
        self.assertNotIn(".309752", formatted)

    def test_missing_datetime_is_explained(self) -> None:
        self.assertEqual(
            _friendly_datetime(None),
            "Not recorded",
        )

    def test_duration_uses_readable_units(self) -> None:
        self.assertEqual(
            _friendly_duration(
                1_000,
                111_971_001_000,
            ),
            "1 min 52 sec",
        )

    def test_tooltip_preserves_exact_stored_values(self) -> None:
        tooltip = _timestamp_tooltip(
            "2026-08-11T21:34:25.309752+00:00",
            1_786_484_065_309_752_176,
        )

        self.assertIn("Stored UTC:", tooltip)
        self.assertIn(
            "1,786,484,065,309,752,176",
            tooltip,
        )


if __name__ == "__main__":
    unittest.main()
