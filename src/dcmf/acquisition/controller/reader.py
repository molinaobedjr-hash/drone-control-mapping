"""USB game-controller acquisition for the RadioMaster TX16S.

The TX16S can present itself to Linux as a USB joystick/HID device.
This reader uses pygame/SDL so we do not have to hard-code Linux
/dev/input paths.

Milestone 2 intentionally exposes raw axis indexes rather than assuming
which axis means roll/pitch/yaw/throttle. Channel order can vary between
radio configurations, so mapping/calibration belongs in the next step.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Final

# Prevent pygame from trying to create a display window. We only use its
# joystick subsystem.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame
from PySide6.QtCore import QThread, Signal


POLL_INTERVAL_SECONDS: Final[float] = 0.02  # 50 Hz


@dataclass(slots=True, frozen=True)
class ControllerSample:
    """One raw controller sample."""

    device_name: str
    axes: tuple[float, ...]
    buttons: tuple[int, ...]
    hats: tuple[tuple[int, int], ...]


class ControllerReader(QThread):
    """Background thread that discovers and polls the first USB joystick."""

    connection_changed = Signal(bool, str)
    sample_received = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._running = False

    def stop(self) -> None:
        """Request a clean shutdown."""
        self._running = False
        self.wait(1500)

    def run(self) -> None:
        """Discover a joystick and poll it until stopped."""
        self._running = True

        try:
            pygame.init()
            pygame.joystick.init()
        except Exception as exc:
            self.error_occurred.emit(f"pygame initialization failed: {exc}")
            return

        joystick = None
        announced_disconnected = False

        try:
            while self._running:
                pygame.event.pump()

                count = pygame.joystick.get_count()

                if joystick is None:
                    if count < 1:
                        if not announced_disconnected:
                            self.connection_changed.emit(
                                False,
                                "No USB joystick detected",
                            )
                            announced_disconnected = True
                        time.sleep(0.5)
                        # SDL refreshes joystick list through the event pump.
                        continue

                    joystick = pygame.joystick.Joystick(0)
                    joystick.init()
                    announced_disconnected = False

                    self.connection_changed.emit(
                        True,
                        (
                            f"{joystick.get_name()} | "
                            f"{joystick.get_numaxes()} axes | "
                            f"{joystick.get_numbuttons()} buttons"
                        ),
                    )

                # A removed device may make polling fail; if so, drop back to
                # discovery instead of killing the application.
                try:
                    axes = tuple(
                        float(joystick.get_axis(index))
                        for index in range(joystick.get_numaxes())
                    )
                    buttons = tuple(
                        int(joystick.get_button(index))
                        for index in range(joystick.get_numbuttons())
                    )
                    hats = tuple(
                        tuple(joystick.get_hat(index))
                        for index in range(joystick.get_numhats())
                    )

                    self.sample_received.emit(
                        ControllerSample(
                            device_name=joystick.get_name(),
                            axes=axes,
                            buttons=buttons,
                            hats=hats,
                        )
                    )

                except pygame.error:
                    try:
                        joystick.quit()
                    except Exception:
                        pass
                    joystick = None
                    self.connection_changed.emit(
                        False,
                        "Controller disconnected",
                    )
                    time.sleep(0.5)

                time.sleep(POLL_INTERVAL_SECONDS)

        except Exception as exc:
            self.error_occurred.emit(str(exc))

        finally:
            if joystick is not None:
                try:
                    joystick.quit()
                except Exception:
                    pass

            try:
                pygame.joystick.quit()
                pygame.quit()
            except Exception:
                pass
