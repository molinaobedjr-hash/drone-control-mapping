"""Application bootstrap for DCMF."""

from __future__ import annotations
import sys
from PySide6.QtWidgets import QApplication

from dcmf.config.settings import AppSettings
from dcmf.gui.main_window import MainWindow
from dcmf.utils.logger import setup_logger


def run() -> None:
    settings = AppSettings()
    logger = setup_logger(settings.log_directory)

    logger.info("Starting %s v%s", settings.application_name, settings.version)

    app = QApplication(sys.argv)
    app.setApplicationName(settings.application_name)
    app.setOrganizationName(settings.organization_name)
    app.setApplicationVersion(settings.version)
    app.setStyle("Fusion")

    window = MainWindow(settings=settings)
    window.show()

    exit_code = app.exec()
    logger.info("Application exited with code %s", exit_code)
    raise SystemExit(exit_code)
