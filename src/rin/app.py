"""Application bootstrap.

Phase 0 produces a no-op ``QApplication`` that launches and exits
cleanly. Subsequent phases attach the system tray (Phase 4), capture
services (Phases 2-3), and the analysis scheduler (Phase 6) here.
"""
from __future__ import annotations

import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from . import __app_name__, __version__
from .config import RinConfig
from .storage import init_db
from .utils.logging import get_logger, setup_logging
from .utils.telemetry import install as install_telemetry

log = get_logger(__name__)


def build_app(cfg: RinConfig | None = None) -> QApplication:
    """Return the singleton ``QApplication`` and apply the global theme."""

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    if cfg is not None:
        apply_theme(app, cfg)
    return app


def apply_theme(app: QApplication, cfg: RinConfig) -> None:
    """Render and install the current theme's stylesheet on ``app``."""

    from .ui import palette_to_qss, resolve, with_accent

    theme = resolve(cfg.ui.theme)
    theme = with_accent(theme, cfg.ui.accent)
    app.setStyleSheet(palette_to_qss(theme, density=cfg.ui.density))
    app.setFont(QFont("Segoe UI Variable", theme.font_size_pt))
    log.debug(
        f"Applied theme: name={theme.name} accent={cfg.ui.accent} density={cfg.ui.density}"
    )


def _install_sigint_handler(app: QApplication) -> QTimer:
    """Make Ctrl+C in the launching terminal cleanly quit the Qt app.

    Qt's C++ event loop blocks the Python interpreter from running its
    own signal handlers, so SIGINT (Ctrl+C) is normally lost. The classic
    workaround is to (a) install a Python signal handler that calls
    ``app.quit()`` and (b) wake the interpreter every ~200 ms with a
    no-op ``QTimer`` so it gets a chance to deliver the pending signal.
    """

    def _handle_sigint(_signum, _frame) -> None:
        log.info("Received SIGINT — shutting down")
        app.quit()

    signal.signal(signal.SIGINT, _handle_sigint)
    # Also wire SIGTERM (e.g. `Stop-Process -Id <pid>` with -PassThru / service stop).
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_sigint)

    timer = QTimer()
    timer.start(200)
    timer.timeout.connect(lambda: None)  # noop — just yields control to Python
    return timer


def run(*, smoke: bool = False) -> int:
    """Boot the application. Returns the Qt exit code."""

    setup_logging()
    log.info(f"{__app_name__} {__version__} starting")

    cfg = RinConfig.load()
    install_telemetry(cfg.telemetry)
    log.debug(f"Loaded config: trigger.source={cfg.trigger.source} paused={cfg.paused}")

    init_db()
    app = build_app(cfg)
    _sigint_timer = _install_sigint_handler(app)  # keep timer alive

    if not smoke and not cfg.first_run_completed and cfg.trigger.source == "unset":
        from .input import InputManager
        from .ui.wizard import FirstRunWizard

        learn_manager = InputManager(cfg)
        learn_manager.start()
        try:
            wizard = FirstRunWizard(
                cfg,
                learn_callback=lambda on_captured: learn_manager.start_learn(on_captured=on_captured),
            )
            wizard.exec()
        finally:
            learn_manager.stop()

    tray = None
    if not smoke:
        from .ui import TrayApp

        tray = TrayApp(cfg)
        tray.start()

    if smoke:
        log.info("Smoke mode — scheduling immediate shutdown")
        QTimer.singleShot(0, app.quit)

    rc = app.exec()
    if tray is not None:
        tray.stop()
    _sigint_timer.stop()
    log.info(f"{__app_name__} exited with code {rc}")
    return rc
